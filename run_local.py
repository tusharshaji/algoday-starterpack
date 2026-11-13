"""Play bots against each other on your own computer and see how they do.

    python run_local.py                              all sample bots, random_walk, seed 1
    python run_local.py --bots my_bot.py bots/hint_follower.py
    python run_local.py --round jumps --seed 3
    python run_local.py --round all --seeds 3        every round, seeds 1-3, overall standings

    python run_local.py --vscode                     set up VS Code to play replays in a tab

Each bot runs in its own process with the same time limits as on the day
(100 ms per tick, 10 s of thinking per 1,000-tick match). Each match's
replay (one .algoday file: click it in VS Code, after --vscode, or drop it
on the competition site's Replays tab) and every bot's log (its print()
output and error messages) are written to --out.
"""
import os
import sys

# Python looks for modules in this file's folder first, so a team file here
# named like one of Python's own modules (random.py, queue.py) would replace
# that module for run_local too, and it would stop with an error deep inside
# algomarket. So look here last: Python's modules and installed packages
# win, and algomarket (no such module there) is still found here.
HERE = os.path.dirname(os.path.abspath(__file__))
if sys.path and (os.path.normcase(os.path.realpath(sys.path[0] or os.curdir))
                 == os.path.normcase(os.path.realpath(HERE))):
    sys.path.append(sys.path.pop(0))

import argparse  # noqa: E402
import time  # noqa: E402

# Bots print anything. Where the terminal can't show a character (on
# Windows: Git Bash, or output sent to a file or a pipe), it comes out as a
# backslash escape instead of stopping run_local.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="backslashreplace")
    except Exception:
        pass

# The match laptop runs Python 3.12. Older ones can't start the bots (they
# run with -P, new in 3.11), and 3.11 plays slightly different matches.
if sys.version_info < (3, 12):
    sys.exit("This kit needs Python 3.12 or newer, but this is Python %d.%d.%d (%s). Install Python 3.12 "
             "from https://www.python.org/downloads/ (README.md, step 2), then open a new terminal and "
             "try again." % (sys.version_info[0], sys.version_info[1], sys.version_info[2], sys.executable))
if sys.version_info[:2] > (3, 12):
    print("Note: this is Python %d.%d. The match laptop runs Python 3.12, so code that needs a newer "
          "Python fails the upload test." % (sys.version_info[0], sys.version_info[1]), file=sys.stderr)

from algomarket import match, rounds, scoring  # noqa: E402
from algomarket.replay import write_replay  # noqa: E402

SAMPLE_BOTS = ["do_nothing", "random_trader", "hint_follower", "simple_market_maker",
               "kalman_market_maker", "pairs_trader"]
MAIN_ROUNDS = ["random_walk", "mean_revert", "jumps", "pairs"]
LOG_TAIL = 12
# How a full error report starts in a bot's log (bot_host.py writes the
# first 20 on_tick tracebacks in full, then one line per error), or a
# report on code still running after its time (where a loop that never
# ends is stuck).
ERROR_STARTS = ("[algomarket] couldn't import the bot", "[algomarket] on_start raised",
                "[algomarket] on_tick raised") + match.STUCK_STARTS
CHAINED = ("During handling of the above exception", "The above exception was the direct cause")
FIRST_ERROR_LINES = 20
# Printed with a replay's path: the two ways to watch it ({}: what to click).
HOW_TO_WATCH = ("click {} in VS Code (set up once: python run_local.py --vscode), or drop it on the site's "
                "Replays tab.")

REASONS = {
    "bad_action": "not a valid action (use buy, sell, cancel or cancel_all)",
    "unknown_asset": "that asset isn't traded in this round",
    "bad_qty": "quantity must be a whole number from 1 to max_order_qty",
    "bad_price": "price must be a positive number",
    "price_band": "price outside the allowed band (see state.band(asset))",
    "position_limit": "would break the position limit (your open orders count too)",
    "too_many_orders": "too many orders resting on one asset (max_open_orders)",
    "too_many_actions": "more actions in one tick than max_actions_per_tick",
    "unknown_order": "cancel of an order id that isn't one of yours (or already gone)",
}

parser = argparse.ArgumentParser(
    prog="run_local.py",
    description="Play bots against each other and the house bots, then show the results.",
    epilog="Example: python run_local.py --round jumps --seed 2 --bots my_bot.py bots/hint_follower.py",
)
parser.add_argument("--round", default="random_walk",
                    help=f"round to play: {', '.join(rounds.ROUNDS)} or all (default random_walk)")
parser.add_argument("--seed", type=int, default=1, help="first seed (default 1)")
parser.add_argument("--seeds", type=int, default=1, help="how many seeds to play (default 1)")
parser.add_argument("--bots", nargs="+", metavar="FILE",
                    help="bot files to play (default: all the sample bots in bots/)")
parser.add_argument("--out", default="out", help="folder for replays and logs (default out/)")
parser.add_argument("--timeout", type=float, default=0.1,
                    help="seconds each bot gets per tick (default 0.1, as on the day)")
parser.add_argument("--no-house", action="store_true", help="play without the house bots")
parser.add_argument("--vscode", action="store_true",
                    help="play nothing: install the kit's replay viewer into VS Code, so a match's "
                         ".algoday file in out/ plays in a tab when you click it")
args = parser.parse_args()

if args.vscode:
    from algomarket import vscode
    sys.exit(vscode.main(HERE))

if args.round == "all":
    round_keys = list(MAIN_ROUNDS)
elif args.round in rounds.ROUNDS:
    round_keys = [args.round]
else:
    parser.error(f"unknown round {args.round!r}; choose from {', '.join(rounds.ROUNDS)} or all")
if args.seed < 0 or args.seeds < 1:
    parser.error("--seed must be 0 or more and --seeds at least 1")
if not args.timeout > 0:
    parser.error("--timeout must be more than 0 seconds")


def find_bot(path):
    """The bot file as given, or relative to this folder; None if missing."""
    for candidate in (path, os.path.join(HERE, path)):
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


bot_files = args.bots or [os.path.join(HERE, "bots", name + ".py") for name in SAMPLE_BOTS]
teams = []
used = set()
for given in bot_files:
    path = find_bot(given)
    if path is None:
        places = os.getcwd() if os.path.abspath(os.getcwd()) == HERE else f"{os.getcwd()} and {HERE}"
        parser.error(f"can't find the bot file {given!r} (looked in {places})")
    if not path.endswith(".py"):
        parser.error(f"{given!r} isn't a .py file")
    base = os.path.splitext(os.path.basename(path))[0]
    name = base
    copy_number = 2
    while name in used:
        name = f"{base}-{copy_number}"
        copy_number += 1
    used.add(name)
    teams.append((name, path))

# A bot's own folder comes first when it imports, so a .py file there named
# like one of Python's modules (or numpy) hides that module from the bot,
# or is hidden by it if it was already loaded. Its error can be puzzling.
for folder in sorted({os.path.dirname(path) for _, path in teams}):
    try:
        found = sorted(os.listdir(folder))
    except OSError:
        found = []
    for file_name in found:
        stem, extension = os.path.splitext(file_name)
        if extension == ".py" and (stem in sys.stdlib_module_names or stem == "numpy"):
            print(f"Note: {os.path.join(folder, file_name)} has the name of the {stem} module, so it can "
                  f"hide that module from your bot (or be hidden by it). Rename it, for example to "
                  f"my_{stem}.py.", file=sys.stderr)


def ticks_text(count):
    return f"{count} tick" if count == 1 else f"{count} ticks"


def status_text(row):
    if row["status"] == "ok":
        return "ok" if row["kind"] == "team" else "house"
    return f"{row['status']} ({row['detail']})"


def print_results(rows):
    teams_first = sorted([r for r in rows if r["kind"] == "team"], key=lambda r: (r["rank"], r["pid"]))
    house = [r for r in rows if r["kind"] != "team"]
    width = max([len(r["name"]) for r in rows] + [4])
    status_width = max([len(status_text(r)) for r in rows] + [6])
    print(f"  {'rank':>4}  {'bot':<{width}}  {'status':<{status_width}} {'pnl $':>10} "
          f"{'max dd $':>10} {'score $':>10} {'trades':>7}")
    for row in teams_first + house:
        rank = str(row["rank"]) if row["rank"] is not None else "-"
        print(f"  {rank:>4}  {row['name']:<{width}}  {status_text(row):<{status_width}} "
              f"{row['pnl']:>10.2f} {row['max_drawdown']:>10.2f} {row['score']:>10.2f} "
              f"{row['trades']:>7}")
    print("  score = pnl - lambda x max drawdown; house bots are not ranked.")


def log_lines(path):
    """The non-empty lines of a bot log ([] if there is none)."""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return []
    return [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]


def first_error(lines):
    """(start, end) of the first full error report in a log's lines: its
    header and traceback, up to the exception line. None if there is none."""
    start = None
    for index, line in enumerate(lines):
        if start is None and line.startswith(ERROR_STARTS):
            start = index
    if start is None:
        return None
    end = start + 1
    done = False
    while not done and end < len(lines) and end - start < FIRST_ERROR_LINES:
        line = lines[end]
        if line.startswith("[algomarket]"):
            done = True
        else:
            end += 1
            # An unindented line other than these headers is the exception
            # line, the end of the report (unless another one is chained on).
            chained = end < len(lines) and lines[end].startswith(CHAINED)
            if (not line[:1].isspace() and not line.startswith("Traceback (")
                    and not line.startswith(CHAINED) and not chained):
                done = True
    return start, end


def log_excerpt(path):
    """(first error, tail): the lines of a bot log the Notes show. The first
    full error report gets its own lines when the tail doesn't reach back
    to it: the bot printed a lot after it, or raised so often that the end
    of the log is one-line reports."""
    lines = log_lines(path)
    tail_from = max(0, len(lines) - LOG_TAIL)
    head = []
    span = first_error(lines)
    if span is not None and span[0] < tail_from:
        head = lines[span[0]:span[1]]
        tail_from = max(tail_from, span[1])
    return head, lines[tail_from:]


def explain(rows, timeout, budget=None):
    """Plain-words notes on team bots that crashed, raised, were slow or
    had orders rejected. budget: the match's thinking time per bot."""
    notes = []
    for row in rows:
        if row["kind"] != "team":
            continue
        name = row["name"]
        log = os.path.normpath(row["log_path"]) if row["log_path"] else None
        show_log = False
        if row["status"] != "ok":
            stopped = "" if not row["stopped_at"] else f" at tick {row['stopped_at']}"
            notes.append(f"!! {name} was stopped{stopped}: "
                         f"{match.DETAIL_TEXT.get(row['detail'], row['detail'])}.")
            show_log = True
        if row["errors"]:
            notes.append(f"!  {name}: on_tick raised an exception on {ticks_text(row['errors'])} "
                         f"(those ticks did nothing).")
            show_log = True
        if row["timeouts"]:
            notes.append(f"!  {name}: missed the {timeout * 1000:.0f} ms deadline on "
                         f"{ticks_text(row['timeouts'])} (those ticks did nothing).")
        used = row.get("think_time")
        if row["status"] == "ok" and budget and used is not None and used > 0.5 * budget:
            notes.append(f"!  {name}: used {used:.1f} s of its {budget:g} s of thinking time for "
                         f"this match (a bot that uses it all is stopped).")
        rejects = sorted(row["rejects"].items(), key=lambda item: -item[1])
        if rejects:
            total = sum(count for _, count in rejects)
            # "!" for what the upload test warns about: broken orders (each
            # reason listed), or orders mostly outside the price band. The
            # rest is market friction.
            band = match.band_warning(row) is not None
            warned = band
            shown = []
            for index, (reason, count) in enumerate(rejects):
                if reason in match.MALFORMED:
                    warned = True
                if index < 3 or reason in match.MALFORMED:
                    shown.append(f"{reason} x{count} ({REASONS.get(reason, reason)})")
            notes.append(f"{'!  ' if warned else '-  '}{name}: {total} orders rejected: " + "; ".join(shown))
            if band:
                notes.append(f"   {row['rejects']['price_band']} of its orders were outside the price band and "
                             f"{row['orders']} went into the book: {match.BAND_HINT}.")
        if show_log:
            head, tail = log_excerpt(log)
            if head:
                notes.append(f"   the first error in its log ({log}):")
                for line in head:
                    notes.append(f"     | {line}")
            if tail:
                notes.append("   last lines of its log:" if head else f"   last lines of its log ({log}):")
                for line in tail:
                    notes.append(f"     | {line}")
            if not head and not tail and log:
                notes.append(f"   its log is empty: {log}")
    if notes:
        print()
        print("Notes:")
        for line in notes:
            print("  " + line)


def save_replay(result, out_dir, stem):
    """Write the match's replay, <stem>.algoday (gzipped JSON): the one file
    a local run keeps of a match, next to its logs. The kit's VS Code viewer
    and the competition site's Replays tab play it. Returns its path, or
    None if it couldn't be written."""
    path = os.path.join(out_dir, stem + ".algoday")
    try:
        os.makedirs(out_dir, exist_ok=True)
        # Put in place in one step, so a tab that is showing it reloads a
        # whole file.
        write_replay(result["replay"], path + ".partial", gzipped=True)
        os.replace(path + ".partial", path)
    except OSError as exc:
        # On Windows: another program has the old one open. It stays as it was.
        print(f"  ({stem}.algoday, the replay, couldn't be written: {exc}. If an older one is there, it is "
              f"still the earlier match: close whatever has it open and play again.)")
        try:
            os.remove(path + ".partial")
        except OSError:
            pass
        return None
    return path


def progress_printer(label):
    if not sys.stderr.isatty():
        return None

    def show(done, total):
        end = "\n" if done == total else ""
        sys.stderr.write(f"\r  {label}: {done}/{total} ticks{end}")
        sys.stderr.flush()
    return show


def play(key, seed):
    stem = f"{key}_seed{seed}"
    return match.run_match(key, seed, teams, tick_timeout=args.timeout, house=not args.no_house,
                           log_dir=os.path.join(args.out, "logs", stem),
                           progress=progress_printer(f"{key} seed {seed}")), stem


try:
    seeds = list(range(args.seed, args.seed + args.seeds))
    print(f"{len(teams)} bots: {', '.join(name for name, _ in teams)}"
          f"{'' if args.no_house else ' (+ house bots)'}")
    if len(round_keys) == 1 and len(seeds) == 1:
        cfg = rounds.get_round(round_keys[0])
        print(f"Round {cfg['title']} ({cfg['key']}), seed {seeds[0]}, {cfg['ticks']} ticks")
        print()
        result, stem = play(round_keys[0], seeds[0])
        print_results(result["results"])
        # The replay first: whatever happens while printing the Notes, it's saved.
        replay_path = save_replay(result, args.out, stem)
        explain(result["results"], args.timeout, result["meta"]["think_budget"])
        print()
        print(f"Played in {result['meta']['wall_seconds']:.1f} s (engine: {result['meta']['engine']}).")
        print(f"Bot logs (their print() output and errors): "
              f"{os.path.normpath(os.path.join(args.out, 'logs', stem))}")
        if replay_path:
            print(f"Replay: {os.path.normpath(replay_path)}")
            print("  To watch it: " + HOW_TO_WATCH.format("it"))
    else:
        matches = []
        saved = 0
        print(f"Rounds {', '.join(round_keys)} x seeds {seeds[0]}-{seeds[-1]}")
        print()
        for key in round_keys:
            for seed in seeds:
                result, stem = play(key, seed)
                matches.append(result)
                ranked = [r for r in result["results"] if r["rank"] == 1]
                winner = ", ".join(f"{r['name']} ({r['score']:.2f})" for r in ranked) or "nobody"
                replay_path = save_replay(result, args.out, stem)
                # It is saved: let the replay go. With some forty of them
                # held here, Python's own clean-up paused this program for
                # longer than a tick, and every bot was charged a missed tick.
                result["replay"] = None
                if replay_path:
                    saved += 1
                print(f"  {key:<12} seed {seed:<4} winner {winner}   [{result['meta']['wall_seconds']:.1f} s]"
                      f"{'  ' + os.path.normpath(replay_path) if replay_path else ''}")
                explain(result["results"], args.timeout, result["meta"]["think_budget"])
        standings = scoring.series_standings(
            [{"round": m["meta"]["round"], "results": m["results"]} for m in matches])
        width = max([len(row["name"]) for row in standings] + [4])
        print()
        print("Overall standings (points per round: n_teams - rank + 1; ties broken by total score)")
        header = f"  {'rank':>4}  {'bot':<{width}} {'points':>7} {'total $':>10}"
        for key in round_keys:
            header += f" {key[:12]:>12}"
        print(header)
        for row in standings:
            rank = str(row["rank"]) if row["rank"] is not None else "-"
            points = str(row["points"]) if row["points"] is not None else "-"
            line = f"  {rank:>4}  {row['name']:<{width}} {points:>7} {row['total_score']:>10.2f}"
            for key in round_keys:
                entry = row["rounds"].get(key)
                line += f" {entry['mean_score']:>12.2f}" if entry else f" {'-':>12}"
            print(line)
        print("  per-round columns are the mean score over the seeds; house bots are not ranked.")
        if saved:
            print()
            print("To watch a match: " + HOW_TO_WATCH.format("its .algoday file"))
except KeyboardInterrupt:
    print()
    print("Stopped (every bot process was shut down).")
    sys.exit(130)
