"""Participants: how the match runner talks to bots (DESIGN.md section 8, in
the organisers' design notes, which are not in the starter kit).

InProcessBot runs trusted code (house bots, tests) in this process.
SubprocessBot runs untrusted team code in a child process (bot_host.py) for
the whole match, speaking JSON lines (section 9).

Every call is bounded in time: send() never blocks, start() and collect()
wait at most until their deadline (a time.monotonic() timestamp), stop()
kills the child's whole process tree and is safe to call more than once.

Runner loop sketch:

    start_all([(p, info_for(p)) for p in everyone], time.monotonic() + 15)
    for t in range(ticks):
        live = [p for p in everyone if p.status == "ok"]
        for p in live:
            p.send(t, state_for(p, t))
        deadline = time.monotonic() + 0.1
        for p in live:
            actions = p.collect(t, deadline)     # None = nothing in time
    stop_all(everyone)

Status/detail set here: start failures (crashed/import_error,
crashed/start_error, timeout/too_slow), the child exiting (crashed/exited)
and protocol violations (crashed/protocol). The max_timeouts / max_errors /
thinking-time policy belongs to the runner: p.fail("timeout", "too_slow")
etc., using SubprocessBot.think_time() for the last.
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import traceback

from . import sdk

HOST_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_host.py")
MAX_LINE = 64 * 1024
# A healthy child sends one line per tick; this many unread lines means flooding.
MAX_QUEUED_LINES = 1000
# Messages waiting for a child that has stopped reading; beyond this, drop.
MAX_QUEUED_SENDS = 1000
DEFAULT_MEMORY_MB = 1024
DEFAULT_MAX_PROCESSES = 8
# The whole job (the bot, plus the venv launcher and console host Windows
# adds, about 2 MB) may use this much more than one process may.
JOB_MEMORY_SLACK_MB = 64

# The child runs as `python -P -B bot_host.py ...`: -P keeps algomarket/ off
# sys.path, -B writes no .pyc files. Not -I: that also hides the per-user
# site-packages (where `pip install --user numpy` puts numpy) and ignores
# PYTHONHASHSEED. Other PYTHON* variables can't get in anyway, because the
# environment is this allowlist.
LAUNCH_FLAGS = ["-P", "-B"]
# -P is new in Python 3.11: an older python would print "Unknown option: -P"
# into every bot's log, and every bot would look as if it crashed. (The kit
# needs 3.12, the match laptop's; run_local.py checks that first.)
OLDEST_PYTHON = (3, 11)


def python_problem(version=None):
    """Why bots can't be started with this Python (version: a version_info
    tuple, default this one's), as a sentence, or None."""
    version = tuple(sys.version_info if version is None else version)
    if version[:2] >= OLDEST_PYTHON:
        return None
    return (f"bots need Python 3.12 or newer, but this is Python {version[0]}.{version[1]} "
            f"({sys.executable}), which can't start them: install Python 3.12 from "
            f"https://www.python.org/downloads/")

# Only these variables reach team code (no Supabase keys or other secrets).
# APPDATA (Windows) or HOME (macOS, Linux), or PYTHONUSERBASE if set, locate
# the per-user site-packages, so a bot imports what the same python imports
# for the user. (A venv, like the match laptop's, has no per-user packages.)
CHILD_ENV_KEYS = [
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "PYTHONUSERBASE",
    "LANG",
    "LC_ALL",
    "NUMBER_OF_PROCESSORS",
]
CHILD_ENV_FIXED = {
    # One maths thread per bot: twelve bots each starting twelve BLAS
    # threads would fight over the CPU.
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    # Fixed string hashing, so a bot that loops over a set of strings makes
    # the same choices every run, and a re-run gives the same match.
    "PYTHONHASHSEED": "0",
}


def child_env():
    env = {}
    for key in CHILD_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env.update(CHILD_ENV_FIXED)
    return env


class _Marker:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<{self.name}>"


_EOF = _Marker("eof")
_TOO_LONG = _Marker("too_long")
_FLOOD = _Marker("flood")


def _json_default(value):
    # numpy scalars/arrays sneaking into a state shouldn't kill the match.
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (set, frozenset)):
        return list(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


# Messages to bots are built fresh every tick, so they can't hold a reference
# cycle: skipping json's check for one makes each state about 30% quicker to
# encode, with the same bytes.
_ENCODER = json.JSONEncoder(separators=(",", ":"), default=_json_default, check_circular=False)


def _encode(message):
    text = _ENCODER.encode(message)
    return (text + "\n").encode("utf-8")


def _decode(line):
    try:
        return json.loads(line)
    except ValueError:
        return None


def _valid_actions(message):
    return (type(message) is dict
            and message.get("type") == "actions"
            and type(message.get("tick")) is int
            and type(message.get("actions")) is list
            and type(message.get("error", False)) is bool)


def _read_lines(stream, lines):
    """Reader thread: child's stdout -> queue of (arrival time, line), or a
    marker and stop."""
    reading = True
    while reading:
        try:
            line = stream.readline(MAX_LINE + 1)
        except (OSError, ValueError):
            line = b""
        if not line:
            lines.put(_EOF)
            reading = False
        elif not line.endswith(b"\n"):
            # Too long, or cut off by the child exiting mid-line.
            if len(line) > MAX_LINE:
                lines.put(_TOO_LONG)
            else:
                lines.put(_EOF)
            reading = False
        elif lines.qsize() >= MAX_QUEUED_LINES:
            lines.put(_FLOOD)
            reading = False
        else:
            # perf_counter, not monotonic: on Windows monotonic ticks every
            # 15.6 ms, too coarse for answers that take a millisecond.
            lines.put((time.perf_counter(), line))


def _write_lines(stream, outbox):
    """Writer thread: queue -> child's stdin, so send() never blocks."""
    writing = True
    while writing:
        data = outbox.get()
        if data is None:
            writing = False
        else:
            try:
                stream.write(data)
                stream.flush()
            except (OSError, ValueError):
                writing = False
    try:
        stream.close()
    except (OSError, ValueError):
        pass


# ------------------------------------------------------- Windows job objects

_kernel32 = None
_JobInfo = None

JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x0008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x0200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x0400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


def _win_api():
    global _kernel32, _JobInfo
    if _kernel32 is None:
        import ctypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        k.CreateJobObjectW.restype = ctypes.c_void_p
        k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                              ctypes.c_void_p, ctypes.c_uint32]
        k.SetInformationJobObject.restype = ctypes.c_int
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.OpenProcess.restype = ctypes.c_void_p
        k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k.AssignProcessToJobObject.restype = ctypes.c_int
        k.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.TerminateJobObject.restype = ctypes.c_int
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        k.CloseHandle.restype = ctypes.c_int
        _JobInfo = ExtendedLimits
        _kernel32 = k
    return _kernel32, _JobInfo


def _set_job_limits(k, job, info_type, flags, memory_mb, max_processes):
    import ctypes
    info = info_type()
    if memory_mb:
        # Per process and for the whole tree: otherwise a bot could start
        # max_processes children and use max_processes x the limit.
        flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
        info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        info.JobMemoryLimit = (int(memory_mb) + JOB_MEMORY_SLACK_MB) * 1024 * 1024
    if max_processes:
        flags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info.BasicLimitInformation.ActiveProcessLimit = int(max_processes)
    info.BasicLimitInformation.LimitFlags = flags
    return k.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                     ctypes.byref(info), ctypes.sizeof(info))


def _make_job(process_id, memory_mb, max_processes):
    """Windows: put the child in a Job Object (best-effort, None if it fails).

    Kill-on-close means the whole tree dies with the job handle, even if
    this process crashes. Limits: memory per process and for the whole
    tree (memory_mb, plus JOB_MEMORY_SLACK_MB for the tree), number of
    processes, no crash dialogs.
    """
    if os.name != "nt":
        return None
    job = None
    try:
        k, info_type = _win_api()
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None
        base = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        if not _set_job_limits(k, job, info_type, base, memory_mb, max_processes):
            if not _set_job_limits(k, job, info_type, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, 0, 0):
                k.CloseHandle(job)
                return None
        handle = k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, process_id)
        if not handle:
            k.CloseHandle(job)
            return None
        assigned = k.AssignProcessToJobObject(job, handle)
        k.CloseHandle(handle)
        if not assigned:
            k.CloseHandle(job)
            return None
        return job
    except Exception:
        if job:
            try:
                _kernel32.CloseHandle(job)
            except Exception:
                pass
        return None


def _terminate_job(job):
    try:
        _kernel32.TerminateJobObject(job, 1)
    except Exception:
        pass


def _close_job(job):
    try:
        _kernel32.CloseHandle(job)
    except Exception:
        pass


def _kill_tree(proc, job):
    """Kill the child and everything it started."""
    if job is not None:
        _terminate_job(job)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
    if os.name == "nt":
        if proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# ----------------------------------------------------------- participants


class Participant:
    """What the match runner sees. Subclasses implement start/send/collect/stop."""

    def __init__(self, name, kind="team"):
        self.name = name
        self.kind = kind
        self.pid = None          # set by the match
        self.status = "ok"       # ok | crashed | timeout | disqualified
        self.detail = None       # import_error, start_error, exited, protocol, too_slow,
                                 # over_budget, too_many_errors
        self.errors = 0          # exceptions raised by on_tick
        self.timeouts = 0        # ticks with no response by the deadline

    @property
    def active(self):
        return self.status == "ok"

    def fail(self, status, detail):
        """Stop the participant for good. The first reason given is kept."""
        if self.status == "ok":
            self.status = status
            self.detail = detail
        self.stop()

    def start(self, info, deadline):
        raise NotImplementedError

    def send(self, tick, state):
        raise NotImplementedError

    def collect(self, tick, deadline):
        raise NotImplementedError

    def stop(self):
        pass

    def __repr__(self):
        return f"{type(self).__name__}({self.name!r}, status={self.status!r}, detail={self.detail!r})"


class InProcessBot(Participant):
    """Trusted bot code run in this process (house bots, tests).

    bot has on_tick(state) and optionally on_start(info), exactly like a team
    file. Exceptions from on_tick count as errors (the tick gets no
    actions); the latest traceback is kept in last_error.
    """

    def __init__(self, name, bot, kind="house"):
        super().__init__(name, kind)
        self.bot = bot
        self.session = None
        self.last_error = None
        self._pending = None
        self._stopped = False

    def start(self, info, deadline):
        if self.status != "ok":
            return False
        self.session = sdk.Session(info)
        on_start = getattr(self.bot, "on_start", None)
        if callable(on_start):
            try:
                on_start(self.session.info)
            except Exception:
                self.last_error = traceback.format_exc()
                self.fail("crashed", "start_error")
                return False
        return True

    def send(self, tick, state):
        if self.status == "ok" and not self._stopped:
            self._pending = (tick, state)

    def collect(self, tick, deadline):
        # Runs on_tick here rather than in send(), so subprocess bots
        # (sent to first) think while house bots compute.
        if self.status != "ok" or self._stopped or self.session is None:
            return None
        pending = self._pending
        if pending is None or pending[0] != tick:
            return None
        self._pending = None
        try:
            state = self.session.update(pending[1])
            return self.session.actions(self.bot.on_tick(state))
        except Exception:
            self.errors += 1
            self.last_error = traceback.format_exc()
            return []

    def stop(self):
        self._stopped = True
        self._pending = None


class SubprocessBot(Participant):
    """Untrusted team code in a child process running bot_host.py.

    entry_path: the team's .py file (cwd = its folder, which is also on the
    child's sys.path for helper modules). log_path: the child's stderr
    (tracebacks and the team's prints, size-capped by bot_host), or None for
    devnull. memory_mb / max_processes: Windows Job Object limits (memory_mb
    caps each process and, plus JOB_MEMORY_SLACK_MB, the whole process
    tree; on POSIX it is an rlimit per process); 0 or None disables them.
    These limits are best-effort, not a sandbox (DESIGN.md section 15, in the
    organisers' design notes).

    Extras for the organiser: process_id, sandboxed (in a Job Object),
    responses / mean_response / max_response (seconds from send() to the
    answer arriving, for answers that counted), think_time() (how long
    the runner waited for this bot in all) and startup_time (seconds from
    launch to ready).

    With this process's own python (python=None), a Python too old to
    start bots (python_problem) raises RuntimeError here, before any bot
    starts.
    """

    def __init__(self, name, entry_path, kind="team", log_path=None, python=None,
                 memory_mb=DEFAULT_MEMORY_MB, max_processes=DEFAULT_MAX_PROCESSES):
        if not python:
            problem = python_problem()
            if problem is not None:
                raise RuntimeError(problem)
        super().__init__(name, kind)
        self.entry_path = os.path.abspath(entry_path)
        self.cwd = os.path.dirname(self.entry_path)
        self.log_path = log_path
        self.python = python or sys.executable
        self.memory_mb = memory_mb
        self.max_processes = max_processes
        self.proc = None
        self.job = None
        # SimpleQueue, not Queue: every tick each message passes the GIL
        # between this thread and a reader or writer thread, and Queue's
        # pure-Python locking held it for longer at every hand-off (a match
        # took about 12% longer). Both queues only need put, get (with a
        # timeout) and qsize.
        self._lines = queue.SimpleQueue()
        self._outbox = queue.SimpleQueue()
        self._reader = None
        self._writer = None
        self._start_sent = False
        self._ready = False
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._sent_tick = None
        self._sent_at = 0.0
        # Response times (send -> answer arrives) for answers that counted.
        self.responses = 0
        self.response_total = 0.0
        self.max_response = 0.0
        # Seconds from launching the child to its ready message (Python's
        # start, the bot's imports and on_start; for a child launched early,
        # also the wait for its start message). None until it is ready.
        self.startup_time = None
        self._launched_at = None

    @property
    def mean_response(self):
        """Average seconds from send() to the answer arriving, or None."""
        if not self.responses:
            return None
        return self.response_total / self.responses

    def think_time(self, tick_timeout):
        """Seconds the runner has waited for this bot so far: every answer
        that counted, plus tick_timeout for every tick it missed."""
        return self.response_total + self.timeouts * tick_timeout

    @property
    def process_id(self):
        """The child's OS process id (None before launch)."""
        if self.proc is None:
            return None
        return self.proc.pid

    @property
    def sandboxed(self):
        """True when the child is inside a Windows Job Object."""
        return self.job is not None

    def launch(self, info=None):
        """Start the child without waiting for it (idempotent). With info,
        also queue the start message. start_all() uses this to start every
        bot in parallel."""
        if self.proc is None and not self._stopped and self.status == "ok":
            self._spawn()
        if info is not None and self.proc is not None and not self._start_sent:
            self._start_sent = True
            self._put({"type": "start", "info": info})

    def _spawn(self):
        if not os.path.isfile(self.entry_path):
            self.fail("crashed", "import_error")
            return
        log = None
        stderr = subprocess.DEVNULL
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        try:
            if self.log_path:
                folder = os.path.dirname(os.path.abspath(self.log_path))
                os.makedirs(folder, exist_ok=True)
                log = open(self.log_path, "wb")
                stderr = log
            self._launched_at = time.perf_counter()
            self.proc = subprocess.Popen(
                [self.python] + LAUNCH_FLAGS + [HOST_SCRIPT, self.entry_path,
                                                str(int(self.memory_mb or 0))],
                cwd=self.cwd,
                env=child_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                close_fds=True,
                **kwargs,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            self.fail("crashed", "start_error")
            return
        finally:
            # The child has its own handle to the log now.
            if log is not None:
                log.close()
        self.job = _make_job(self.proc.pid, self.memory_mb, self.max_processes)
        self._reader = threading.Thread(target=_read_lines, args=(self.proc.stdout, self._lines),
                                        name=f"bot-read-{self.name}", daemon=True)
        self._writer = threading.Thread(target=_write_lines, args=(self.proc.stdin, self._outbox),
                                        name=f"bot-write-{self.name}", daemon=True)
        self._reader.start()
        self._writer.start()

    def _put(self, message):
        if self._outbox.qsize() >= MAX_QUEUED_SENDS:
            return False
        self._outbox.put(_encode(message))
        return True

    def _next(self, deadline):
        """Next line from the child, or None if nothing arrives by deadline."""
        remaining = deadline - time.monotonic()
        try:
            if remaining > 0:
                return self._lines.get(timeout=remaining)
            return self._lines.get_nowait()
        except queue.Empty:
            return None

    def start(self, info, deadline):
        """Launch (if needed), send start, wait for ready. False on failure,
        with status/detail set and the child stopped."""
        if self._ready:
            return True
        if self.status != "ok":
            return False
        self.launch(info)
        if self.proc is None or self.status != "ok":
            return False
        ok = False
        waiting = True
        while waiting:
            item = self._next(deadline)
            waiting = False
            if item is None:
                self.fail("timeout", "too_slow")
            elif item is _EOF:
                self.fail("crashed", "exited")
            elif item is _TOO_LONG or item is _FLOOD:
                self.fail("crashed", "protocol")
            else:
                message = _decode(item[1])
                kind = message.get("type") if isinstance(message, dict) else None
                if kind == "ready":
                    self._ready = True
                    ok = True
                    if self._launched_at is not None:
                        self.startup_time = max(0.0, item[0] - self._launched_at)
                elif kind == "fatal":
                    if message.get("stage") == "start":
                        self.fail("crashed", "start_error")
                    else:
                        self.fail("crashed", "import_error")
                else:
                    self.fail("crashed", "protocol")
        return ok

    def send(self, tick, state):
        """Queue a tick for the child. Never blocks."""
        if self.status != "ok" or self._stopped or not self._ready:
            return
        if self._put({"type": "tick", "tick": tick, "state": state}):
            self._sent_tick = tick
            self._sent_at = time.perf_counter()

    def collect(self, tick, deadline):
        """The child's actions for tick, or None if they don't arrive by
        deadline (counted in timeouts). Responses for older ticks are
        discarded."""
        if self.status != "ok" or self._stopped or not self._ready:
            return None
        result = None
        waiting = True
        while waiting:
            item = self._next(deadline)
            waiting = False
            if item is None:
                self.timeouts += 1
            elif item is _EOF:
                self.fail("crashed", "exited")
            elif item is _TOO_LONG or item is _FLOOD:
                self.fail("crashed", "protocol")
            else:
                arrived, line = item
                message = _decode(line)
                if not _valid_actions(message):
                    self.fail("crashed", "protocol")
                elif message["tick"] < tick:
                    waiting = True          # stale: a late answer to an old tick
                elif message["tick"] > tick:
                    self.fail("crashed", "protocol")
                else:
                    if message.get("error", False):
                        self.errors += 1
                    result = message["actions"]
                    if self._sent_tick == tick:
                        took = max(0.0, arrived - self._sent_at)
                        self.responses += 1
                        self.response_total += took
                        self.max_response = max(self.max_response, took)
        return result

    def stop(self):
        """Kill the child's whole process tree. Idempotent."""
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        proc = self.proc
        if proc is None:
            return
        self._outbox.put(None)
        _kill_tree(proc, self.job)
        if self._writer is not None:
            self._writer.join(timeout=1)
        if self._reader is not None:
            self._reader.join(timeout=1)
            # Closing a pipe another thread is still reading can hang on Windows.
            if not self._reader.is_alive():
                try:
                    proc.stdout.close()
                except (OSError, ValueError):
                    pass
        if self.job is not None:
            _close_job(self.job)
            self.job = None


def start_all(pairs, deadline):
    """Start many participants in parallel: every child is launched (and
    imports its bot) before waiting on any of them. pairs: [(participant,
    info)]. Returns a list of bools in the same order."""
    for participant, info in pairs:
        launch = getattr(participant, "launch", None)
        if launch is not None:
            launch(info)
    results = []
    for participant, info in pairs:
        results.append(participant.start(info, deadline))
    return results


def stop_all(participants):
    for participant in participants:
        participant.stop()
