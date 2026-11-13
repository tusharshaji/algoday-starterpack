"""Match runner: glue between rounds, scenarios, the exchange, participants,
house bots, scoring and the replay (DESIGN.md section 13, in the organisers'
design notes, which are not in the starter kit).

    result = run_match("random_walk", 1, [("alpha", "teams/alpha/bot.py")])
    result["results"]       # one row per participant, teams ranked
    result["replay"]        # replay v1 dict (record=True)
    run_series(["random_walk", "jumps"], [1, 2, 3], teams)   # standings
    run_smoke("uploads/alpha/strategy.py")                   # the upload test

Seeds: every random stream of a match (scenario, exchange shuffle, house
bots) comes from match_seed(seed, round key). The same (round, seed) always
gives the same market; the same seed in two rounds gives unrelated paths, so
the smoke test can't preview a real round.

Each tick: begin_tick, send to every live participant (child processes
first, so they start thinking), collect with one shared deadline (in-process
bots compute inside collect, children answer meanwhile), apply the
timeout/error/thinking-time policy (fail + exchange stop), process, mark,
invariants, record. Every participant is stopped in a finally, whatever
happens.

Phase B (new orders) runs in a seeded shuffle every tick. A trusted house
bot may take a fixed slot instead (its phase_b_slot attribute, see
_phase_b_slot): the house noise traders go last, so their orders meet the
quotes the other bots refreshed this tick. Team bots are always shuffled.

Thinking time: every tick waits for the slowest bot, so one bot answering
in just under the deadline would make every match (and the final) last
for ages. A child-process bot may therefore keep the runner waiting for at
most max_think seconds per REFERENCE_TICKS ticks in all (answer times plus
tick_timeout per missed tick); beyond that it is stopped (timeout,
over_budget) like a bot that misses too many ticks.
"""
import builtins      # run_match's `round` argument hides the builtin
import copy
import datetime
import hashlib
import importlib.util
import itertools
import math
import numbers
import os
import re
import tempfile
import time

import numpy as np

from . import house as house_bots
from . import rounds, scenarios, scoring
from .exchange import Exchange
from .participants import InProcessBot, Participant, SubprocessBot, start_all
from .replay import Recorder

# Section 13 result row, in this order; extras follow (see run_match).
RESULT_KEYS = ("pid", "name", "kind", "status", "detail", "pnl", "max_drawdown", "score",
               "rank", "trades", "volume", "final_positions", "errors", "timeouts")
EXTRA_KEYS = ("orders", "rejects", "stopped_at", "log_path", "mean_response", "max_response",
              "think_time", "halted")

SMOKE_ROUND = "smoke"
# A real match is about this long; the smoke test allows timeouts at the
# rate that would still survive max_timeouts in a real match, and the
# thinking time is scaled to the match length the same way.
REFERENCE_TICKS = 1000
# Seconds of thinking a child-process bot may use per REFERENCE_TICKS ticks
# (10 ms per tick on average; the sample bots use under 1 s). With 128
# final matches, one bot using all of it adds about 21 minutes.
DEFAULT_MAX_THINK = 10.0
DEFAULT_START_TIMEOUT = 15.0
# After a pass, the upload test plays a CHECK_TICKS-tick cut of every real
# round (warnings only). Seed 0 is never a scrimmage or final seed (those
# are >= 1), so the cuts show nothing of a real match.
CHECK_TICKS = 100
CHECK_SEED = 0
# Launch to ready (Python, the bot's imports and on_start) slower than this
# is an upload-test warning: every match waits for the slowest bot to start.
SLOW_START = 3.0
# bot_host.py's reports on team code still running after its limit (a tick
# after 0.5 s, the import or on_start after 5 s): where it is, as a traceback.
STUCK_STARTS = ("[algomarket] on_tick still running", "[algomarket] on_start still running",
                "[algomarket] still importing the bot")
# Error reports in a bot's log (bot_host.py): import and on_start failures
# and the first 20 on_tick errors in full, then one line per error; then
# the still-running reports.
REPORT_STARTS = ("[algomarket] couldn't import the bot", "[algomarket] on_start raised",
                 "[algomarket] on_tick raised", "[algomarket] couldn't encode the actions") + STUCK_STARTS
CHAINED = ("During handling of the above exception", "The above exception was the direct cause")
# error_summary() reads at most this much of a log's start (bot_host caps
# team prints at 2 MB and its own reports at 1 MB; fd writes aren't capped).
LOG_SCAN_BYTES = 4 * 1024 * 1024
MAX_ERROR_TEXT = 200
# The bot controls its error text, and one exception line can be about a
# megabyte (bot_host's limit): _clean_error's regexes only ever see this
# much of its start (the result is capped at MAX_ERROR_TEXT anyway).
CLEAN_SCAN_TEXT = 8 * MAX_ERROR_TEXT
ALGOMARKET_DIR = os.path.dirname(os.path.abspath(__file__))
# Rejects that mean the bot built a broken order (a bug), not market friction.
MALFORMED = ("bad_action", "unknown_asset", "bad_qty", "bad_price", "unknown_order",
             "too_many_actions")
# A price_band reject now and then is friction, but a bot whose orders are
# mostly outside the band (prices in cents, or hard-coded for another
# asset) never trades: band_warning() when its price_band rejects are at
# least as many as its orders that went into the book.
BAND_HINT = "prices are in dollars (99.50, not 9950) and must be inside state.band(asset)"

DETAIL_TEXT = {
    "import_error": "the file failed to import (a syntax error, a missing module, "
                    "or an exception at import time)",
    "start_error": "on_start(info) raised an exception",
    "exited": "the bot process exited in the middle of the match",
    "protocol": "the bot process sent something that isn't a valid answer",
    "too_slow": "too slow: it missed the per-tick deadline too often, or took too long to start",
    "over_budget": (f"too slow overall: it used up its thinking time for the match "
                    f"({DEFAULT_MAX_THINK:g} s per {REFERENCE_TICKS:,} ticks, about "
                    f"{DEFAULT_MAX_THINK * 1000 / REFERENCE_TICKS:g} ms per tick on average)"),
    "too_many_errors": "on_tick raised exceptions on too many ticks",
}

_bot_counter = itertools.count(1)
# "[algomarket] tick 23: KeyError: 'x' (strategy.py line 9, in on_tick)": its
# start, then the place at its very end, looked for in the last PLACE_SCAN
# characters only. The bot controls the text between (and can print a line
# that looks like one), and one regex over all of it could backtrack for
# minutes.
_ONE_LINE = re.compile(r"\[algomarket\] tick -?\d+: ")
_PLACE = re.compile(r" \((?P<file>[^()]*) line (?P<line>\d+), in [^()]*\)$")
PLACE_SCAN = 1000
_FRAME = re.compile(r'\s*File "(?P<file>[^"]*)", line (?P<line>\d+)')
# Absolute paths left in an error message once the bot's own folder is cut
# out: a drive (C:\..., C:/...), a UNC share (\\server\...) or /a/b... A
# share only starts at the first backslash of a run: starting anywhere in
# a long run of backslashes would take time quadratic in its length.
_PATH_PART = r"[^\s'\"<>|*?()\[\]{},;:"
_ABSOLUTE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+" + _PATH_PART + "]*"
                       + r"|(?<![\\])[\\]{2,}[^\\/\s'\"]+[\\/]+" + _PATH_PART + "]*"
                       + r"|(?<![\w.~\\/-])/" + _PATH_PART + "/]+(?:/" + _PATH_PART + "/]*)+")


# ------------------------------------------------------------------ helpers

def match_seed(seed, round_key):
    """The seed all of a match's random streams come from: (seed, round key)."""
    seed = scenarios.check_seed(seed)
    digest = hashlib.sha256(f"algomarket:{round_key}".encode("utf-8")).digest()
    key = int.from_bytes(digest[:8], "little")
    return int(np.random.SeedSequence([seed, key]).generate_state(1, np.uint64)[0])


def think_budget(ticks, max_think=DEFAULT_MAX_THINK):
    """Seconds of thinking a child-process bot may use in a match of `ticks`
    ticks: max_think per REFERENCE_TICKS ticks. None or 0: no limit."""
    if max_think is None or max_think == 0:
        return None
    if not (isinstance(max_think, numbers.Real) and math.isfinite(max_think) and max_think > 0):
        raise ValueError(f"max_think must be a positive number of seconds or None, got {max_think!r}")
    return float(max_think) * ticks / REFERENCE_TICKS


def resolve_round(round_or_cfg):
    """A validated deep copy of a round: a key from rounds.ROUNDS or a config dict."""
    if isinstance(round_or_cfg, str):
        cfg = rounds.get_round(round_or_cfg)
    elif isinstance(round_or_cfg, dict):
        cfg = copy.deepcopy(round_or_cfg)
    else:
        raise TypeError(f"round must be a round key or a config dict, got {round_or_cfg!r}")
    if type(cfg.get("key")) is not str or not cfg["key"]:
        raise ValueError("a round config needs a 'key' (its name)")
    return rounds.validate(cfg)


def scenario_for(round_or_cfg, seed):
    """The scenario run_match plays for (round, seed)."""
    cfg = resolve_round(round_or_cfg)
    return scenarios.generate(cfg, match_seed(seed, cfg["key"]))


def load_bot(path):
    """A bot file loaded as a brand-new module (its own globals), for trusted
    in-process runs such as calibration. Real matches never do this: team
    code only runs in child processes."""
    path = os.path.abspath(os.fspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(f"_algomarket_bot_{next(_bot_counter)}_{_safe(stem)}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"can't load a bot from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))[:60] or "bot"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _team(entry, index, log_dir):
    """A team entry -> (participant, log path or None)."""
    if isinstance(entry, Participant):
        if entry.pid is not None:
            raise ValueError(f"participant {entry.name!r} already played a match; make a new one")
        return entry, getattr(entry, "log_path", None)
    if isinstance(entry, (tuple, list)) and len(entry) == 2 and isinstance(entry[0], str):
        name, target = entry
        if isinstance(target, (str, os.PathLike)):
            log_path = None
            if log_dir is not None:
                log_path = os.path.join(os.fspath(log_dir), f"{index:02d}_{_safe(name)}.log")
            return SubprocessBot(name, os.fspath(target), kind="team", log_path=log_path), log_path
        if callable(getattr(target, "on_tick", None)):
            return InProcessBot(name, target, kind="team"), None
    raise ValueError(f"teams[{index}] must be (name, path), (name, bot with on_tick) "
                     f"or a Participant, got {entry!r}")


def _house_cfg(cfg, house):
    if house is False or house is None:
        return None
    base = copy.deepcopy(cfg.get("house") or {})
    if isinstance(house, dict):
        return rounds.deep_merge(base, house)
    if house is True:
        return base
    raise ValueError(f"house must be True, False or a dict of overrides, got {house!r}")


def _halted(participant):
    """True if a house bot stopped itself (the market maker's loss cap)."""
    if participant.kind != "house":
        return None
    flag = getattr(getattr(participant, "bot", None), "stopped", None)
    return flag if isinstance(flag, bool) else None


def _phase_b_slot(participant):
    """Where the participant's new orders go in phase B: "first", "shuffle"
    or "last" (exchange.SLOT_RANK). Only a trusted in-process house bot
    picks its own (house.NoiseTrader: "last"); a team bot is always in the
    shuffle, whatever its code defines."""
    if participant.kind == "house" and isinstance(participant, InProcessBot):
        return getattr(participant.bot, "phase_b_slot", "shuffle")
    return "shuffle"


def _stop_everyone(participants):
    for participant in participants:
        try:
            participant.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- matches

def run_match(round, seed, teams, *, tick_timeout=0.1, start_timeout=DEFAULT_START_TIMEOUT,
              max_timeouts=20, max_errors=100, max_think=DEFAULT_MAX_THINK, house=True, record=True,
              log_dir=None, progress=None, created_at=None, check_invariants=True):
    """Play one match. Returns {"meta", "results", "replay"}.

    round: a round key or a round config dict (e.g. with overrides).
    teams: entries of (name, entry_path) -> child process,
           (name, object with on_tick) -> trusted in-process bot, or a
           fresh Participant. Pids: teams in order, then house bots.
    max_think: seconds a child-process bot may keep the runner waiting per
           REFERENCE_TICKS ticks (see think_budget); None = no limit.
    house: True = the round's house config, a dict = overrides merged over
           it, False = no house bots.
    progress(ticks_done, ticks) is called about 20 times per match.

    Result rows: the section 13 keys plus orders (orders that went into
    the book, rejected ones not counted), rejects ({reason: count}),
    stopped_at (tick a participant was stopped, 0 for startup failures),
    log_path, mean_response / max_response / think_time (seconds, child
    processes only) and halted (house market maker hit its loss cap).
    meta["think_budget"]: this match's thinking time per bot (or None).
    """
    clock = time.monotonic()
    cfg = resolve_round(round)
    key = cfg["key"]
    budget = think_budget(cfg["ticks"], max_think)
    seed = scenarios.check_seed(seed)
    mseed = match_seed(seed, key)
    if created_at is None:
        created_at = _now()
    public = rounds.public_info(cfg)

    everyone = []
    log_paths = []
    limits = []
    for index, entry in enumerate(teams):
        participant, log_path = _team(entry, index, log_dir)
        everyone.append(participant)
        log_paths.append(log_path)
        limits.append(None)
    house_cfg = _house_cfg(cfg, house)
    if house_cfg is not None:
        for name, bot, bot_limits in house_bots.build(house_cfg, public, mseed):
            everyone.append(InProcessBot(name, bot, kind="house"))
            log_paths.append(None)
            limits.append(bot_limits)
    names = [p.name for p in everyone]
    if len(set(names)) != len(names):
        raise ValueError(f"participant names must be unique, got {names}")
    for pid, participant in enumerate(everyone):
        participant.pid = pid

    sc = scenarios.generate(cfg, mseed)
    ex = Exchange(cfg, [(p.pid, p.kind, limits[p.pid], _phase_b_slot(p)) for p in everyone], mseed)
    recorder = None
    if record:
        recorder = Recorder(cfg, seed, everyone, engine_name=ex.engine, created_at=created_at)
    people = [{"pid": p.pid, "name": p.name, "kind": p.kind} for p in everyone]
    children = [p for p in everyone if isinstance(p, SubprocessBot)]
    local = [p for p in everyone if not isinstance(p, SubprocessBot)]
    stopped_at = [None] * len(everyone)
    ticks = sc.ticks
    every = max(1, ticks // 20)

    try:
        pairs = []
        for p in everyone:
            info = copy.deepcopy(public)
            info.update({"you": p.pid, "name": p.name, "limits": ex.limits_for(p.pid),
                         "participants": copy.deepcopy(people)})
            pairs.append((p, info))
        start_all(pairs, time.monotonic() + start_timeout)
        for p in everyone:
            if p.status != "ok":
                ex.stop(p.pid)
                stopped_at[p.pid] = 0

        for t in range(ticks):
            hints = sc.hints_at[t]
            ex.begin_tick(t, hints)
            live_children = [p for p in children if p.status == "ok"]
            live_local = [p for p in local if p.status == "ok"]
            for p in live_children + live_local:
                p.send(t, ex.state_for(p.pid))
            deadline = time.monotonic() + tick_timeout
            actions = {}
            for p in live_local + live_children:
                actions[p.pid] = p.collect(t, deadline)
            for p in live_local + live_children:
                if p.status == "ok":
                    if p.timeouts > max_timeouts:
                        p.fail("timeout", "too_slow")
                    elif p.errors > max_errors:
                        p.fail("disqualified", "too_many_errors")
                    elif (budget is not None and isinstance(p, SubprocessBot)
                          and p.think_time(tick_timeout) > budget):
                        p.fail("timeout", "over_budget")
                if p.status != "ok":
                    ex.stop(p.pid)
                    actions.pop(p.pid, None)
                    stopped_at[p.pid] = t
            ex.process(actions)
            values = sc.true_values_at(t)
            ex.end_tick(values)
            if check_invariants:
                ex.check_invariants()
            if recorder is not None:
                recorder.record_tick(t, values, hints, ex.tick_summary())
            if progress is not None and ((t + 1) % every == 0 or t + 1 == ticks):
                progress(t + 1, ticks)
        ex.settle()
    finally:
        _stop_everyone(everyone)

    rows = []
    for p in everyone:
        stats = ex.stats(p.pid)
        summary = scoring.summarize(scoring.to_dollars(ex.equity_curve[p.pid]), cfg["lambda"])
        child = isinstance(p, SubprocessBot)
        rows.append({
            "pid": p.pid, "name": p.name, "kind": p.kind, "status": p.status, "detail": p.detail,
            "pnl": summary["pnl"], "max_drawdown": summary["max_drawdown"],
            "score": summary["score"], "rank": None,
            "trades": stats["trades"], "volume": stats["volume"],
            "final_positions": stats["final_positions"],
            "errors": p.errors, "timeouts": p.timeouts,
            "orders": stats["orders"], "rejects": stats["reject_reasons"],
            "stopped_at": stopped_at[p.pid],
            "log_path": log_paths[p.pid],
            "mean_response": getattr(p, "mean_response", None),
            "max_response": p.max_response if child else None,
            "think_time": p.think_time(tick_timeout) if child else None,
            "halted": _halted(p),
        })
    rows = scoring.assign_ranks(rows)
    meta = {"round": key, "title": cfg.get("title"), "seed": seed, "match_seed": mseed,
            "ticks": ticks, "assets": list(cfg["assets"]), "lambda": cfg["lambda"],
            "engine": ex.engine, "created_at": created_at, "tick_timeout": tick_timeout,
            "think_budget": budget, "wall_seconds": builtins.round(time.monotonic() - clock, 3)}
    replay = recorder.build(rows) if recorder is not None else None
    return {"meta": meta, "results": rows, "replay": replay}


def run_series(round_list, seeds, teams, **kw):
    """Every round x every seed, fresh bots each match. Returns
    {"standings": scoring.series_standings rows, "matches": run_match results}.

    teams: a list of (name, path) / (name, bot) entries (paths get a fresh
    process per match; in-process bot objects are reused as they are), or a
    function (round_key, seed) -> entries for fresh objects every match.
    """
    if not callable(teams):
        for entry in teams:
            if isinstance(entry, Participant):
                raise ValueError("run_series starts fresh bots for every match: pass (name, path) "
                                 "entries or a function (round_key, seed) -> entries")
    matches = []
    for item in round_list:
        cfg = resolve_round(item)
        for seed in seeds:
            entries = teams(cfg["key"], seed) if callable(teams) else teams
            matches.append(run_match(cfg, seed, entries, **kw))
    standings = scoring.series_standings(
        [{"round": m["meta"]["round"], "results": m["results"]} for m in matches])
    return {"standings": standings, "matches": matches}


# ------------------------------------------------------------- smoke test

def smoke_timeout_allowance(ticks, max_timeouts=20):
    """Timeouts the smoke test tolerates: the real-match rate, scaled down."""
    return int(math.floor(max_timeouts * ticks / REFERENCE_TICKS))


def run_smoke(entry_path, name="team", seed=0, **kw):
    """The upload test: one team against the house on the smoke round.

    Passes when the bot started and stayed ok, on_tick never raised, and it
    missed the deadline on at most smoke_timeout_allowance ticks (4 of 200
    at the defaults: the rate that would still survive a real match). Its
    thinking time is limited as in a real match, scaled to 200 ticks (2 s
    at the defaults), so a bot too slow for a real match fails here. Late
    answers, slow averages (> half the deadline), using over half the
    thinking time, a slow start (over SLOW_START s from launch to ready),
    malformed orders and orders mostly outside the price band
    (band_warning) are warnings, not failures.

    After a pass it also plays a CHECK_TICKS-tick cut of every real round
    (round_checks: seed CHECK_SEED, the same limits, no replay, logs in a
    log_dir subfolder per round), because a bot written for one round's
    assets passes the smoke round (DEVS) and then raises, or does nothing,
    all day in the others. A cut where on_tick raised, the bot was stopped,
    orders were rejected as malformed or were mostly outside the price
    band, or no order went into the book (though some did in the smoke
    match and in another cut) adds a warning, never a failure. Returns
    {"passed", "verdict", "problems", "warnings", "result", "meta",
    "replay"}, result, meta and replay from the smoke match; replay is
    None unless record=True is passed.
    """
    kw.setdefault("record", False)
    entry = (name, entry_path)
    if isinstance(name, str) and isinstance(entry_path, (str, os.PathLike)):
        # The same child-process bot run_match would make, kept here for
        # its start-up time.
        entry = _team(entry, 0, kw.get("log_dir"))[0]
    result = run_match(SMOKE_ROUND, seed, [entry], **kw)
    row = result["results"][0]
    meta = result["meta"]
    ticks = meta["ticks"]
    limit_ms = round(meta["tick_timeout"] * 1000)
    allowed = smoke_timeout_allowance(ticks, kw.get("max_timeouts", 20))
    budget = meta["think_budget"]
    used = row["think_time"]
    problems = []
    warnings = []
    if row["status"] != "ok":
        text = (f"{row['status']} ({row['detail']}): "
                f"{DETAIL_TEXT.get(row['detail'], 'the bot was stopped')}")
        if row["detail"] == "over_budget" and budget is not None:
            text += f"; this {ticks}-tick test allows {budget:g} s"
        problems.append(text)
    elif budget is not None and used is not None and used > 0.5 * budget:
        warnings.append(f"slow overall: used {used:.1f} s of the {budget:g} s of thinking time "
                        f"this {ticks}-tick test allows (a bot that uses it all is stopped)")
    if row["errors"]:
        problems.append(f"on_tick raised an exception on {row['errors']} of {ticks} ticks")
    if row["timeouts"] > allowed:
        problems.append(f"missed the {limit_ms} ms deadline on {row['timeouts']} of {ticks} ticks "
                        f"(at most {allowed} allowed)")
    elif row["timeouts"]:
        warnings.append(f"missed the {limit_ms} ms deadline on {row['timeouts']} of {ticks} ticks")
    mean = row["mean_response"]
    if mean is not None and mean > 0.5 * meta["tick_timeout"]:
        warnings.append(f"slow: answers took {mean * 1000:.0f} ms on average (limit {limit_ms} ms)")
    malformed = []
    for reason in MALFORMED:
        if row["rejects"].get(reason):
            malformed.append(f"{reason} x{row['rejects'][reason]}")
    if malformed:
        warnings.append("orders rejected as malformed: " + ", ".join(malformed))
    band = band_warning(row)
    if band is not None:
        warnings.append(band)
    startup = getattr(entry, "startup_time", None)
    if startup is not None and startup > SLOW_START:
        warnings.append(f"slow start: took {startup:.1f} s to get ready (the limit is "
                        f"{kw.get('start_timeout', DEFAULT_START_TIMEOUT):g} s); every match waits for "
                        f"the slowest bot, so keep heavy work out of import and on_start")
    passed = not problems
    if passed:
        warnings.extend(round_checks(entry_path, name, smoke=result, **kw))
    return {"passed": passed, "verdict": "PASS" if passed else "FAIL: " + problems[0],
            "problems": problems, "warnings": warnings, "result": row, "meta": meta,
            "replay": result["replay"]}


def round_checks(entry_path, name="team", smoke=None, **kw):
    """Warnings from a CHECK_TICKS-tick cut of every real round (seed
    CHECK_SEED): the bot alone against the house, with run_match's other
    settings from kw, never recorded. Each cut logs to log_dir/<round key>/
    (participants name logs by index, so one shared folder would overwrite
    the smoke test's log); without a log_dir, to a temporary folder, so
    the warnings can still quote the first error. Every cut's child
    process is launched first: they import the bot while the first cut
    plays. smoke: run_match's result for the smoke match (run_smoke passes
    it), for the warnings that compare a cut with it (_cut_warnings)."""
    log_dir = kw.get("log_dir")
    settings = dict(kw)
    settings.update(record=False, progress=None, log_dir=None)
    scratch = None
    cuts = []
    warnings = []
    try:
        if log_dir is None:
            scratch = tempfile.TemporaryDirectory(prefix="algomarket_checks_", ignore_cleanup_errors=True)
            log_dir = scratch.name
        for key in rounds.ROUNDS:
            if key != SMOKE_ROUND:
                cfg = rounds.get_round(key)
                cfg["ticks"] = CHECK_TICKS
                folder = os.path.join(os.fspath(log_dir), key)
                cuts.append((cfg, _team((name, entry_path), 0, folder)[0]))
        for _, participant in cuts:
            launch = getattr(participant, "launch", None)
            if launch is not None:
                launch()
        played = []
        for cfg, participant in cuts:
            played.append((cfg, run_match(cfg, CHECK_SEED, [participant], **settings), participant))
        placed = False
        for _, result, _ in played:
            if result["results"][0]["orders"]:
                placed = True
        for cfg, result, participant in played:
            warnings.extend(_cut_warnings(cfg, result, getattr(participant, "cwd", None), smoke, placed))
    finally:
        _stop_everyone([participant for _, participant in cuts])
        if scratch is not None:
            scratch.cleanup()
    return warnings


def _assets_text(assets):
    """"DEVS", "WDCC and UOA", "A, B and C"."""
    assets = list(assets)
    if len(assets) > 1:
        return ", ".join(assets[:-1]) + " and " + assets[-1]
    return assets[0] if assets else "nothing"


def band_warning(row, where=None):
    """The upload-test warning for a result row whose price_band rejects
    are at least as many as its orders that went into the book (row
    "orders"), or None. where: e.g. "in a short Pairs test (it trades WDCC
    and UOA)"."""
    band = (row.get("rejects") or {}).get("price_band") or 0
    placed = row.get("orders") or 0
    if band <= 0 or band < placed:
        return None
    place = f" {where}" if where else ""
    return (f"orders rejected as outside the price band{place}: price_band x{band}, while {placed} "
            f"went into the book; {BAND_HINT}")


def _cut_warnings(cfg, result, bot_dir, smoke=None, placed=False):
    """Upload-test warnings for one cut: on_tick raised, or the bot was
    stopped (with the first error in its log, if there is one); orders
    rejected as malformed, for reasons the smoke match (smoke: its
    run_match result) didn't have; orders mostly outside the price band
    (band_warning), unless the smoke match had that warning; or, though
    the smoke match and another cut (placed) put orders into the book, no
    order went in here (and none of its orders was malformed or outside
    the band)."""
    row = result["results"][0]
    ticks = result["meta"]["ticks"]
    budget = result["meta"]["think_budget"]
    assets = list(cfg["assets"])
    where = f"in a short {cfg.get('title') or cfg['key']} test (it trades {_assets_text(assets)})"
    out = []
    if row["errors"]:
        text = f"on_tick raised on {row['errors']} of {ticks} ticks {where}"
        first = error_summary(row["log_path"], bot_dir, stuck=False)
        if first:
            text += f": {first}"
        out.append(text)
    if row["status"] != "ok":
        text = (f"stopped at tick {row['stopped_at']} {where}: {row['status']} ({row['detail']}): "
                f"{DETAIL_TEXT.get(row['detail'], 'the bot was stopped')}")
        if row["detail"] == "over_budget" and budget is not None:
            text += f"; this {ticks}-tick test allows {budget:g} s"
        if not row["errors"]:
            first = error_summary(row["log_path"], bot_dir)
            if first:
                text += f": {first}"
        out.append(text)
    smoke_row = smoke["results"][0] if smoke else None
    known = (smoke_row or {}).get("rejects") or {}
    rejects = row.get("rejects") or {}
    malformed = []
    for reason in MALFORMED:
        if rejects.get(reason) and not known.get(reason):
            malformed.append(f"{reason} x{rejects[reason]}")
    if malformed:
        out.append(f"orders rejected as malformed {where}: " + ", ".join(malformed))
    band = band_warning(row, where)
    if band is not None and (smoke_row is None or band_warning(smoke_row) is None):
        out.append(band)
    if (not malformed and band is None and smoke_row is not None and placed and row["status"] == "ok"
            and not row["errors"] and row.get("orders") == 0 and smoke_row.get("orders")):
        smoke_assets = list(smoke["meta"]["assets"])
        if set(assets) <= set(smoke_assets):
            hint = f"does it skip this round? (state.info[\"round\"] is \"{cfg['key']}\" here)"
        else:
            hint = "is an asset name hard-coded? (loop over state.assets)"
        out.append(f"no orders {where}, though it placed some in the {smoke['meta']['ticks']}-tick test "
                   f"(it trades {_assets_text(smoke_assets)}): {hint}")
    return out


# ------------------------------------------------------------ bot logs

def error_summary(log_path, bot_dir=None, stuck=True):
    """The first error report in a bot's log as one line, e.g.
    "KeyError: 'DEVS' (strategy.py line 12)": the exception, then the
    innermost frame in the team's own files (bot_dir: the bot's folder;
    algomarket/ and installed packages don't count). Safe to show the
    team: no folder paths (the bot's folder is cut out of the message and
    any other absolute path becomes <path>), printable, at most
    MAX_ERROR_TEXT characters plus the place. None if there is no report.
    stuck=False skips bot_host's still-running reports (STUCK_STARTS)."""
    starts = REPORT_STARTS
    if not stuck:
        starts = tuple([prefix for prefix in REPORT_STARTS if prefix not in STUCK_STARTS])
    lines = _log_head(log_path)
    start = None
    for index, line in enumerate(lines):
        if start is None and (line.startswith(starts) or _ONE_LINE.match(line)):
            start = index
    if start is None:
        return None
    if lines[start].startswith(starts):
        exception, where = _parse_report(lines[start + 1:_report_end(lines, start)], bot_dir)
    else:
        exception, where = _parse_one_line(lines[start])
    text = _clean_error(exception or "", bot_dir)
    if not text:
        return None
    if where is not None:
        text += f" ({_clean_error(where[0], bot_dir)} line {where[1]})"
    return text


def _log_head(log_path):
    """The lines of the first LOG_SCAN_BYTES of a log ([] if unreadable)."""
    if not log_path:
        return []
    try:
        with open(log_path, "rb") as handle:
            data = handle.read(LOG_SCAN_BYTES)
    except OSError:
        return []
    return data.decode("utf-8", "replace").splitlines()


def _parse_one_line(line):
    """(exception text, (file name, line) or None) of a one-line report."""
    text = line[_ONE_LINE.match(line).end():]
    tail = text[-PLACE_SCAN:]
    place = _PLACE.search(tail)
    if place is None:
        return text, None
    return text[:len(text) - len(tail) + place.start()], (place.group("file"), place.group("line"))


def _report_end(lines, start):
    """Index just past the error report whose header is lines[start]: its
    exception line (chained exceptions included), or the next [algomarket]
    line. As run_local.py's first_error()."""
    end = start + 1
    done = False
    while not done and end < len(lines):
        line = lines[end]
        if line.startswith("[algomarket]"):
            done = True
        else:
            end += 1
            if (line.strip() and not line[:1].isspace() and not line.startswith("Traceback (")
                    and not line.startswith(CHAINED)):
                # An exception line ends the report, unless another
                # exception is chained on (after a blank line).
                ahead = end
                while ahead < len(lines) and not lines[ahead].strip():
                    ahead += 1
                done = not (ahead < len(lines) and lines[ahead].startswith(CHAINED))
    return end


def _parse_report(lines, bot_dir):
    """(exception line, (file name, line) or None) of a full report's
    traceback lines. With chained exceptions the last one counts; the place
    is the innermost team frame of the last traceback that has one."""
    exception = None
    where = None
    in_traceback = False
    for line in lines:
        if line.startswith("Traceback ("):
            in_traceback = True
            exception = None
        elif in_traceback and exception is None and line[:1].isspace():
            frame = _FRAME.match(line)
            if frame is not None and _team_file(frame.group("file"), bot_dir):
                where = (os.path.basename(frame.group("file")), frame.group("line"))
        elif in_traceback and exception is None and line.strip() and not line.startswith(CHAINED):
            exception = line.strip()
    return exception, where


def _inside(path, folder):
    path = os.path.normcase(path)
    folder = os.path.normcase(folder).rstrip("\\/")
    return path == folder or path.startswith(folder + os.sep)


def _team_file(path, bot_dir):
    """True for a file in the team's own folder, not in algomarket/ or an
    installed package (as bot_host.py's _team_line)."""
    if not bot_dir or not path or path.startswith("<"):
        return False
    full = os.path.abspath(path)
    parts = os.path.normcase(full).split(os.sep)
    return (_inside(full, os.path.abspath(bot_dir)) and not _inside(full, ALGOMARKET_DIR)
            and "site-packages" not in parts and "dist-packages" not in parts)


def _clean_error(text, bot_dir):
    """Error text fit to show a team: the bot's folder cut out (so its own
    files keep just their names), other absolute paths -> <path>, control
    characters -> spaces, at most MAX_ERROR_TEXT characters. Only the first
    CLEAN_SCAN_TEXT characters are read: a longer text also loses its last,
    cut word (it may be the start of a path) and ends in " ..."."""
    text = str(text)
    if len(text) > CLEAN_SCAN_TEXT:
        head = text[:CLEAN_SCAN_TEXT]
        words = head.rsplit(None, 1)
        if len(words) == 2:
            head = words[0]
        text = head + " ..."
    if bot_dir:
        pieces = [piece for piece in re.split(r"[\\/]+", os.path.abspath(bot_dir)) if piece]
        if pieces:
            sep = r"[\\/]+"
            lead = sep if os.path.abspath(bot_dir)[:1] in ("/", "\\") else ""
            folder = re.compile(lead + sep.join([re.escape(piece) for piece in pieces])
                                + r"(?:(?P<sep>[\\/]+)|(?![^\\/'\"\s,;:)\]}>]))", re.IGNORECASE)
            text = folder.sub(lambda hit: "" if hit.group("sep") else ".", text)
    text = _ABSOLUTE.sub("<path>", text)
    text = "".join([ch if ch.isprintable() else " " for ch in text]).strip()
    if len(text) > MAX_ERROR_TEXT:
        text = text[:MAX_ERROR_TEXT - 3].rstrip() + "..."
    return text
