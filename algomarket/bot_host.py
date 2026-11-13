"""Child side of SubprocessBot: hosts one team bot (DESIGN.md section 9, in
the organisers' design notes, which are not in the starter kit).

Started by participants.SubprocessBot as

    python -P -B bot_host.py ENTRY_PATH MEMORY_MB

with cwd = the bot's folder, stderr = the bot's log file (or devnull) and an
allowlisted environment (PYTHONHASHSEED=0, participants.CHILD_ENV_KEYS).
The protocol is JSON lines on the stdin/stdout this process inherited.
Before any team code runs they move to private file descriptors: fd 0 then
reads from devnull and fd 1 writes to the log, so print(), os.write(1, ...)
and reading stdin can never touch the protocol.

Order of events: import the team file (fatal "import" on failure), wait for
"start", call on_start(info) (fatal "start" on failure), send "ready", then
answer every "tick" with "actions" until "end" or EOF.

Exceptions from on_tick, including SystemExit and KeyboardInterrupt, count
as errors (error: true, no actions) and the bot keeps running: team code
doesn't decide when the process ends, the runner does. os._exit() can't be
caught, so it ends the process and the runner reports "exited". SystemExit
during import or on_start is a fatal error like any other.

Team output (stdout + stderr) is capped at TEAM_LOG_LIMIT bytes and the
host's own tracebacks at HOST_LOG_LIMIT, so print spam can't fill the disk.

Team code still running after its limit (a tick after STUCK_TICK s, the
import or on_start after STUCK_START s) gets a "still running" report in
the log, from a watchdog thread: where the main thread is, as a traceback
of the team's frames. A loop that never ends leaves no exception, and the
runner kills the bot from outside, so this is the only place its line
shows. The report only reads the stack: the bot carries on (and the runner
treats a late answer as usual).
"""
import os
import sys

# Move the protocol off fds 0 and 1 before anything else can use them.
# os.dup returns non-inheritable fds, so processes the bot starts can't
# reach the protocol either.
PROTO_IN = os.dup(0)
PROTO_OUT = os.dup(1)
LOG_FD = os.dup(2)
_null = os.open(os.devnull, os.O_RDONLY)
os.dup2(_null, 0)
os.close(_null)
os.dup2(2, 1)

import faulthandler  # noqa: E402
import importlib.util  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

TEAM_LOG_LIMIT = 2 * 1024 * 1024
HOST_LOG_LIMIT = 1024 * 1024
MAX_LINE = 64 * 1024
FULL_TRACEBACKS = 20
# Still-running reports (module docstring). A match stops a bot after about
# 2 s of missed ticks in a row, the upload test's round checks after about
# 1 s (their thinking time), so a tick's report comes well before that; the
# runner allows 15 s to start. Checked every STUCK_POLL s; at most
# STUCK_REPORTS a match, each with at most STUCK_FRAMES frames.
STUCK_TICK = 0.5
STUCK_START = 5.0
STUCK_POLL = 0.1
STUCK_REPORTS = 5
STUCK_FRAMES = 30

_team_budget = [TEAM_LOG_LIMIT]
_host_budget = [HOST_LOG_LIMIT]
# Team code can't stop the reports by changing the time module.
_clock = time.monotonic
_nap = time.sleep
MAIN_THREAD = threading.get_ident()
_host_lock = threading.Lock()


def _write_all(fd, data):
    view = memoryview(data)
    while len(view):
        written = os.write(fd, view)
        view = view[written:]


def _emit(fd, data, budget):
    left = budget[0]
    if left <= 0:
        return
    if len(data) > left:
        data = data[:left] + b"\n[algomarket] log limit reached, further output dropped\n"
        budget[0] = 0
    else:
        budget[0] = left - len(data)
    try:
        _write_all(fd, data)
    except OSError:
        pass


def host_log(text):
    # The main thread and the watchdog (_watch_stuck) both report.
    with _host_lock:
        _emit(LOG_FD, text.encode("utf-8", "backslashreplace"), _host_budget)


class _TeamText(io.TextIOBase):
    """sys.stdout / sys.stderr for team code: UTF-8 into the log, capped."""

    def __init__(self, fd, name):
        super().__init__()
        self._fd = fd
        self.name = name
        self.mode = "w"
        self.buffer = _TeamBinary(fd)

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "backslashreplace"

    @property
    def line_buffering(self):
        return True

    def reconfigure(self, **kwargs):
        # Teams sometimes call sys.stdout.reconfigure(encoding="utf-8").
        pass

    def writable(self):
        return True

    def isatty(self):
        return False

    def fileno(self):
        return self._fd

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError(f"write() argument must be str, not {type(text).__name__}")
        _emit(self._fd, text.encode("utf-8", "backslashreplace"), _team_budget)
        return len(text)

    def flush(self):
        pass

    def close(self):
        # Closing stdout must not break later prints.
        pass


class _TeamBinary(io.RawIOBase):
    def __init__(self, fd):
        super().__init__()
        self._fd = fd

    def writable(self):
        return True

    def fileno(self):
        return self._fd

    def write(self, data):
        data = bytes(data)
        _emit(self._fd, data, _team_budget)
        return len(data)

    def close(self):
        pass


sys.stdin = open(os.devnull, "r", encoding="utf-8")
sys.stdout = _TeamText(1, "<stdout>")
sys.stderr = _TeamText(2, "<stderr>")

try:
    faulthandler.enable(file=LOG_FD, all_threads=True)
except Exception:
    pass

# Ctrl+C belongs to the runner, and team code can't fake it either.
try:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
except Exception:
    pass


def _limit_memory(megabytes):
    # POSIX only (Windows gets a Job Object from the parent). Address space
    # is bigger than real memory use, so allow twice the cap.
    if os.name != "posix" or megabytes <= 0:
        return
    try:
        import resource
        limit = megabytes * 2 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:
        pass


def _watch_parent():
    """Exit if the runner dies, even while team code is stuck in a loop."""
    parent = os.getppid()
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle = kernel32.OpenProcess(0x00100000, 0, parent)  # SYNCHRONIZE
        if not handle:
            return

        def wait():
            kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(1)
    else:
        def wait():
            while os.getppid() == parent:
                time.sleep(0.5)
            os._exit(1)
    threading.Thread(target=wait, name="algomarket-watchdog", daemon=True).start()


# What team code is running now: (stage, tick, started, limit) or None.
_BUSY = [None]
_stuck_left = [STUCK_REPORTS]


def _busy(stage, tick, limit):
    _BUSY[0] = (stage, tick, _clock(), limit)


def _idle():
    _BUSY[0] = None


def _watch_stuck():
    """Watchdog thread: a still-running report for team code that has run
    past its limit, once per tick (or import, or on_start)."""
    reported = None
    while _stuck_left[0] > 0:
        _nap(STUCK_POLL)
        busy = _BUSY[0]
        if busy is not None and busy is not reported and _clock() - busy[2] > busy[3]:
            reported = busy
            _report_stuck(busy)


def _host_codes():
    codes = set()
    for name in ("_load_bot", "_start", "_tick"):
        function = globals().get(name)
        if function is not None:
            codes.add(function.__code__)
    return codes


def _stuck_text(stage, tick, limit):
    """(header, last line) of a still-running report."""
    after = f"{limit:g} s"
    if stage == "tick":
        return (f"[algomarket] on_tick still running at tick {tick} after {after}; where it is now:",
                f"on_tick is still running after {after}: is it stuck in a loop that never ends?")
    if stage == "start":
        return (f"[algomarket] on_start still running after {after}; where it is now:",
                f"on_start is still running after {after}: is it stuck in a loop that never ends?")
    return (f"[algomarket] still importing the bot after {after}; where it is now:",
            f"the import is still running after {after}: is it stuck in a loop that never ends?")


def _report_stuck(busy):
    """Log where the main thread is: its frames inside the host function
    that called team code (not the host's own, nor frozen importlib's),
    innermost last, like a traceback. Nothing if it has moved on."""
    try:
        frame = sys._current_frames().get(MAIN_THREAD)
        if frame is None:
            return
        hosts = _host_codes()
        frames = []
        inside = False
        for item in traceback.walk_stack(frame):
            if not inside:
                if item[0].f_code in hosts:
                    inside = True
                elif not item[0].f_code.co_filename.startswith("<"):
                    frames.append(item)
        if not inside or _BUSY[0] is not busy:
            return
        _stuck_left[0] -= 1
        lines = []
        if len(frames) > STUCK_FRAMES:
            lines.append(f"  ... ({len(frames) - STUCK_FRAMES} frames further out)\n")
        frames = frames[:STUCK_FRAMES]
        frames.reverse()
        lines.extend(traceback.StackSummary.extract(iter(frames)).format())
        header, last = _stuck_text(busy[0], busy[1], busy[3])
        host_log(header + "\nTraceback (most recent call last):\n" + "".join(lines) + last + "\n")
    except BaseException:
        pass


def _parse_memory(args):
    try:
        return int(args[2])
    except (IndexError, ValueError):
        return 0


def send(message):
    data = (json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    _write_all(PROTO_OUT, data)


def _quit(code):
    os._exit(code)


try:
    _watch_parent()
except Exception:
    pass
try:
    threading.Thread(target=_watch_stuck, name="algomarket-stuck", daemon=True).start()
except Exception:
    pass
_limit_memory(_parse_memory(sys.argv))

ENTRY = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ""
BOT_DIR = os.path.dirname(ENTRY)
ALGOMARKET_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_PARENT = os.path.dirname(ALGOMARKET_DIR)

# Our SDK is imported first, so a team's own copy of algomarket can't shadow it.
sys.path.insert(0, PACKAGE_PARENT)
from algomarket import sdk  # noqa: E402

sys.path.insert(0, BOT_DIR)
sys.argv = [ENTRY]


def _load_bot():
    name = os.path.splitext(os.path.basename(ENTRY))[0]
    if not name.isidentifier() or name in sys.modules:
        name = "_algomarket_team_bot"
    spec = importlib.util.spec_from_file_location(name, ENTRY)
    if spec is None or spec.loader is None:
        raise ImportError(f"can't load {ENTRY!r} as a Python file")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fatal(stage, text):
    host_log(text)
    try:
        send({"type": "fatal", "stage": stage})
    except Exception:
        pass
    _quit(1)


BOT = None
ON_TICK = None
try:
    _busy("import", None, STUCK_START)
    BOT = _load_bot()
    ON_TICK = getattr(BOT, "on_tick", None)
    if not callable(ON_TICK):
        raise AttributeError(f"{os.path.basename(ENTRY)} has no on_tick(state) function")
except BaseException:
    _fatal("import", "[algomarket] couldn't import the bot:\n" + traceback.format_exc())
_idle()

SESSION = None
ERRORS = [0]


def _inside(path, folder):
    path = os.path.normcase(path)
    folder = os.path.normcase(folder).rstrip(os.sep)
    return path == folder or path.startswith(folder + os.sep)


def _team_line(tb):
    """' (strategy.py line 9, in on_tick)': the innermost frame of the
    traceback in the team's own files (next to the entry file, not
    algomarket/ or installed packages), or '' if there is none."""
    where = ""
    for frame, lineno in traceback.walk_tb(tb):
        name = frame.f_code.co_filename
        if name and not name.startswith("<"):
            path = os.path.abspath(name)
            parts = os.path.normcase(path).split(os.sep)
            if (_inside(path, BOT_DIR) and not _inside(path, ALGOMARKET_DIR)
                    and "site-packages" not in parts and "dist-packages" not in parts):
                where = f" ({os.path.basename(path)} line {lineno}, in {frame.f_code.co_name})"
    return where


def _report_error(tick):
    ERRORS[0] += 1
    try:
        kind, value, tb = sys.exc_info()
        note = ""
        if kind is not None and not issubclass(kind, Exception):
            note = f" ({kind.__name__} in on_tick counts as an error; the bot keeps running)"
        if ERRORS[0] <= FULL_TRACEBACKS:
            text = f"[algomarket] on_tick raised at tick {tick}{note}:\n{traceback.format_exc()}"
        else:
            # Short from here on, but still saying where: the full
            # tracebacks may be far above the end of the log.
            text = f"[algomarket] tick {tick}: {kind.__name__}: {value}{_team_line(tb)}\n"
    except BaseException:
        text = f"[algomarket] on_tick raised at tick {tick}\n"
    host_log(text)


def _start(info):
    global SESSION
    try:
        SESSION = sdk.Session(info)
        on_start = getattr(BOT, "on_start", None)
        if callable(on_start):
            _busy("start", None, STUCK_START)
            on_start(SESSION.info)
    except BaseException:
        _fatal("start", "[algomarket] on_start raised:\n" + traceback.format_exc())
    _idle()
    send({"type": "ready"})


def _tick(message):
    tick = message.get("tick")
    error = False
    _busy("tick", tick, STUCK_TICK)
    try:
        state = SESSION.update(message.get("state"))
        actions = SESSION.actions(ON_TICK(state))
    except BaseException:
        error = True
        actions = []
        _report_error(tick)
    _idle()
    try:
        reply = {"type": "actions", "tick": tick, "actions": actions, "error": error}
        data = (json.dumps(reply, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(data) > MAX_LINE:
            raise ValueError(f"reply is {len(data)} bytes")
    except BaseException:
        host_log(f"[algomarket] couldn't encode the actions for tick {tick}:\n{traceback.format_exc()}")
        reply = {"type": "actions", "tick": tick, "actions": [], "error": True}
        data = (json.dumps(reply, separators=(",", ":")) + "\n").encode("utf-8")
    _write_all(PROTO_OUT, data)


INPUT = os.fdopen(PROTO_IN, "rb")
running = True
while running:
    try:
        line = INPUT.readline()
    except (OSError, ValueError):
        line = b""
    if not line:
        running = False
        continue
    try:
        message = json.loads(line)
    except ValueError:
        message = None
    kind = message.get("type") if isinstance(message, dict) else None
    try:
        if kind == "start":
            _start(message.get("info") or {})
        elif kind == "tick":
            _tick(message)
        elif kind == "end":
            running = False
    except OSError:
        # The runner went away (broken pipe): nothing left to talk to.
        running = False

_quit(0)
