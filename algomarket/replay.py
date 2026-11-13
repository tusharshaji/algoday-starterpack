"""Match recorder and the replay file, version 1 (DESIGN.md section 14, in the
organisers' design notes, which are not in the starter kit).

The Recorder takes one row per tick while the match runs (cents in, from
Exchange.tick_summary()) and builds the replay dict (dollars, 2 dp). Files
are JSON, gzipped when the path ends in .gz (mtime 0, so the same replay
always gives the same bytes). run_local.py's .algoday files are the gzipped
form under another name (write_replay(..., gzipped=True)). Replay trades are
[t, asset, price, qty, buyer_pid, seller_pid, aggressor "buy" | "sell"].
Participants are {pid, name, kind, status, stopped_at}: stopped_at is the
tick the bot was stopped at (0 = it failed to start), or null when it ran
to the end; the viewer shows a bot's status from that tick. Replays
written before stopped_at existed still validate without it.

    rec = Recorder(round_cfg, seed, participants)
    ... each tick, after ex.end_tick():
    rec.record_tick(t, true_values, hints, ex.tick_summary())
    replay = rec.build(results)
    write_replay(replay, "match.json.gz")
"""
import datetime
import gzip
import json
import math
import os

from . import engine

VERSION = 1
META_KEYS = ("round", "title", "seed", "ticks", "assets", "lambda", "engine", "created_at")
PARTICIPANT_KEYS = ("pid", "name", "kind", "status")
# Written by Recorder.build; optional when reading (older replays and the
# viewer's fake ones may leave it out).
PARTICIPANT_OPTIONAL = ("stopped_at",)
RESULT_KEYS = ("pid", "name", "kind", "status", "pnl", "max_drawdown", "score", "rank",
               "trades", "volume")
TOP_KEYS = ("version", "meta", "participants", "true_value", "best_bid", "best_ask", "books",
            "hints", "trades", "equity", "positions", "results")


def dollars(cents):
    """Cents -> dollars rounded to 2 dp (never -0.0)."""
    return round(float(cents) / 100.0, 2) + 0.0


def _field(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _levels(levels):
    return [[dollars(price), int(qty)] for price, qty in levels]


class Recorder:
    def __init__(self, round_cfg, seed, participants, engine_name=None, created_at=None):
        """participants: dicts or objects with pid, name, kind (and status).

        created_at defaults to now (UTC, ISO 8601); pass a fixed value when
        two runs must give identical replays.
        """
        self.assets = list(round_cfg["assets"])
        if created_at is None:
            created_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if engine_name is None:
            engine_name = getattr(engine, "NAME", "unknown")
        self.meta = {
            "round": round_cfg.get("key"),
            "title": round_cfg.get("title"),
            "seed": int(seed),
            "ticks": 0,
            "assets": list(self.assets),
            "lambda": float(round_cfg["lambda"]),
            "engine": engine_name,
            "created_at": created_at,
        }
        self._participants = list(participants)
        self.pids = []
        for p in self._participants:
            self.pids.append(int(_field(p, "pid")))
        self.ticks = 0
        self.true_value = {}
        self.best_bid = {}
        self.best_ask = {}
        self.books = {}
        for asset in self.assets:
            self.true_value[asset] = []
            self.best_bid[asset] = []
            self.best_ask[asset] = []
            self.books[asset] = []
        self.hints = []
        self.trades = []
        self.equity = {}
        self.positions = {}
        for pid in self.pids:
            key = str(pid)
            self.equity[key] = []
            self.positions[key] = {}
            for asset in self.assets:
                self.positions[key][asset] = []

    def record_tick(self, t, true_values, hints, summary):
        """One tick after processing. true_values {asset: cents}, hints
        [(asset, cents, source)] released at t, summary from tick_summary()."""
        if t != self.ticks:
            raise ValueError(f"expected tick {self.ticks}, got {t!r}")
        for i, asset in enumerate(self.assets):
            self.true_value[asset].append(dollars(true_values[asset]))
            bids, asks = summary["books"][i]
            self.best_bid[asset].append(dollars(bids[0][0]) if bids else None)
            self.best_ask[asset].append(dollars(asks[0][0]) if asks else None)
            self.books[asset].append([_levels(bids), _levels(asks)])
        for asset, value, source in hints:
            # Same rule as the exchange: a non-finite hint is never released.
            if math.isfinite(float(value)):
                self.hints.append([t, asset, dollars(value), source])
        for _, asset, price, qty, buyer, seller, aggressor in summary["trades"]:
            self.trades.append([t, asset, dollars(price), int(qty), int(buyer), int(seller), aggressor])
        equity = summary["equity"]
        positions = summary["positions"]
        for pid in self.pids:
            key = str(pid)
            self.equity[key].append(dollars(equity[pid]))
            row = positions[pid]
            for i, asset in enumerate(self.assets):
                self.positions[key][asset].append(int(row[i]))
        self.ticks += 1

    def build(self, results=(), statuses=None):
        """The replay dict. results: per-participant result rows (dollars;
        a row's stopped_at becomes the participant's), statuses: optional
        {pid: status} overriding everything else."""
        by_pid = {}
        for row in results:
            by_pid[int(row["pid"])] = row
        participants = []
        for p in self._participants:
            pid = int(_field(p, "pid"))
            status = None
            if statuses is not None:
                status = statuses.get(pid)
            if status is None and pid in by_pid:
                status = by_pid[pid].get("status")
            if status is None:
                status = _field(p, "status")
            stopped = by_pid[pid].get("stopped_at") if pid in by_pid else None
            participants.append({"pid": pid, "name": str(_field(p, "name")),
                                 "kind": str(_field(p, "kind")), "status": status or "ok",
                                 "stopped_at": None if stopped is None else int(stopped)})
        result_rows = []
        for p in participants:
            row = by_pid.get(p["pid"])
            if row is not None:
                out = {}
                for key in RESULT_KEYS:
                    out[key] = row.get(key)
                out["pid"] = p["pid"]
                out["status"] = p["status"]
                result_rows.append(out)
        meta = dict(self.meta)
        meta["ticks"] = self.ticks
        return {
            "version": VERSION,
            "meta": meta,
            "participants": participants,
            "true_value": self.true_value,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "books": self.books,
            "hints": self.hints,
            "trades": self.trades,
            "equity": self.equity,
            "positions": self.positions,
            "results": result_rows,
        }


def write_replay(replay, path, gzipped=None):
    """Write JSON, gzipped when the path ends in .gz. gzipped=True or False
    decides it whatever the name (an .algoday file is gzipped). Returns the
    path."""
    path = os.fspath(path)
    if gzipped is None:
        gzipped = path.endswith(".gz")
    data = json.dumps(replay, separators=(",", ":"), allow_nan=False).encode("utf-8")
    with open(path, "wb") as handle:
        if gzipped:
            with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as packed:
                packed.write(data)
        else:
            handle.write(data)
    return path


def load_replay(path):
    """Read a replay written by write_replay (gzip detected from the bytes)."""
    with open(os.fspath(path), "rb") as handle:
        data = handle.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))


# ------------------------------------------------------------- validation

def _num(value):
    return type(value) in (int, float) and math.isfinite(value)


def _bad(problem):
    raise ValueError(f"replay: {problem}")


def validate_replay(replay):
    """Raise ValueError unless replay matches the version 1 schema."""
    if not isinstance(replay, dict) or set(replay) != set(TOP_KEYS):
        _bad(f"top-level keys must be exactly {TOP_KEYS}")
    if replay["version"] != VERSION:
        _bad(f"version must be {VERSION}")
    meta = replay["meta"]
    if set(meta) != set(META_KEYS):
        _bad(f"meta keys must be exactly {META_KEYS}")
    ticks = meta["ticks"]
    assets = meta["assets"]
    if type(ticks) is not int or ticks < 0 or not isinstance(assets, list):
        _bad("meta.ticks must be an int and meta.assets a list")
    pids = []
    allowed = (set(PARTICIPANT_KEYS), set(PARTICIPANT_KEYS) | set(PARTICIPANT_OPTIONAL))
    for p in replay["participants"]:
        if not isinstance(p, dict) or set(p) not in allowed or type(p["pid"]) is not int:
            _bad(f"participant keys must be exactly {PARTICIPANT_KEYS}, plus {PARTICIPANT_OPTIONAL} "
                 "if present")
        stopped = p.get("stopped_at")
        if stopped is not None and (type(stopped) is not int or not 0 <= stopped < max(ticks, 1)):
            _bad("a participant's stopped_at must be null or a tick of the match")
        pids.append(str(p["pid"]))
    for name in ("true_value", "best_bid", "best_ask", "books"):
        if set(replay[name]) != set(assets):
            _bad(f"{name} must have one entry per asset")
        for asset in assets:
            if len(replay[name][asset]) != ticks:
                _bad(f"{name}.{asset} must have one entry per tick")
    for asset in assets:
        for value in replay["true_value"][asset]:
            if not _num(value):
                _bad("true values must be numbers")
        for name in ("best_bid", "best_ask"):
            for value in replay[name][asset]:
                if value is not None and not _num(value):
                    _bad(f"{name} entries must be numbers or null")
        for entry in replay["books"][asset]:
            if len(entry) != 2:
                _bad("books entries must be [bids, asks]")
            for side in entry:
                if len(side) > 5:
                    _bad("books keep the top 5 levels")
                for level in side:
                    if len(level) != 2 or not _num(level[0]) or type(level[1]) is not int:
                        _bad("book levels must be [price, qty]")
    for hint in replay["hints"]:
        if len(hint) != 4 or type(hint[0]) is not int or not _num(hint[2]):
            _bad("hints must be [t, asset, value, source]")
    for trade in replay["trades"]:
        if (len(trade) != 7 or type(trade[0]) is not int or not _num(trade[2])
                or type(trade[3]) is not int or trade[6] not in ("buy", "sell")):
            _bad("trades must be [t, asset, price, qty, buyer, seller, aggressor]")
    if set(replay["equity"]) != set(pids) or set(replay["positions"]) != set(pids):
        _bad("equity and positions must have one entry per participant")
    for key in pids:
        if len(replay["equity"][key]) != ticks:
            _bad("equity must have one entry per tick")
        if set(replay["positions"][key]) != set(assets):
            _bad("positions must have one entry per asset")
        for asset in assets:
            if len(replay["positions"][key][asset]) != ticks:
                _bad("positions must have one entry per tick")
    for row in replay["results"]:
        if set(row) != set(RESULT_KEYS):
            _bad(f"result keys must be exactly {RESULT_KEYS}")
    return replay
