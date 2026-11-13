"""Round configs (DESIGN.md section 7, in the organisers' design notes, which
are not in the starter kit).

Units: prices are integer cents; noise, sigma and jump sizes are dollars;
half-lives, periods and margins are ticks.

Public keys (fine to show teams): key, title, description, assets, ticks,
start_prices, hint_sources, limits, band_pct, lambda. `public_info()` returns
exactly those. Private keys (drive scenarios.py, never sent to bots):
process, hint_schedule. `house` holds overrides for house.build; an empty
dict means the house.py defaults.

Process types (`process["type"]`):
    random_walk   sigma (per-tick sd), initial_sd (sd of V[0] around the start price)
    mean_revert   Ornstein-Uhlenbeck around the start price (the public anchor):
                  half_life, sigma (per-tick shock sd); V[0] is a stationary draw
    jumps         random_walk plus jump_count [lo, hi] jumps of +-U(jump_size)
                  dollars, never within jump_margin ticks of either end
    pairs         leader = random_walk(sigma, initial_sd); follower =
                  beta * leader + (start_f - beta * start_l) + OU gap
                  (spread_half_life, spread_sigma), gap starts at a stationary draw

Hint schedule entries (one per source; within a tick hints come in this order):
    assets        assets covered (default: all)
    every         fires on ticks t > 0 with (t - offset) % every == 0
    offset        see every (default 0)
    prob          fires on each tick t > 0 with this probability
    on_jumps      fires on every jump tick of its asset
    noise         private noise sd override in dollars (default: the public one)
    outlier_prob  share of this source's hints pushed off by +-U(outlier_size) dollars
Tick 0 always releases exactly one hint per asset, from the first source in
the schedule that covers it (normal noise, never an outlier).
"""
import copy
import math

LIMIT_KEYS = ("position_limit", "max_order_qty", "max_open_orders", "max_actions_per_tick")
PUBLIC_KEYS = ("key", "title", "description", "assets", "ticks", "start_prices",
               "hint_sources", "limits", "band_pct", "lambda")
PROCESS_TYPES = ("random_walk", "mean_revert", "jumps", "pairs")
DEFAULT_JUMP_MARGIN = 20

_LIMITS = {
    "position_limit": 50,
    "max_order_qty": 10,
    "max_open_orders": 10,
    "max_actions_per_tick": 20,
}

ROUNDS = {
    "random_walk": {
        "key": "random_walk",
        "title": "Random walk",
        "description": (
            "The true value of DEVS is a random walk starting near $100: every tick it "
            "takes a small random step, up or down equally likely. An analyst "
            "publishes an estimate every 5 ticks (error sd $0.40). Positions are "
            "cashed out at the true value after the last tick."),
        "assets": ["DEVS"],
        "ticks": 1000,
        "start_prices": {"DEVS": 10000},
        "process": {"type": "random_walk", "sigma": 0.13, "initial_sd": 1.0},
        "hint_sources": {
            "analyst": {"noise": 0.40, "description": "Estimate of DEVS every 5 ticks."},
        },
        "hint_schedule": {
            "analyst": {"every": 5},
        },
        "limits": dict(_LIMITS),
        "band_pct": 0.2,
        "lambda": 0.5,
        # A slower house: informed bots can beat it even when strong teams play.
        "house": {"market_maker": {"smoothing": 0.1, "delay": 3}},
    },
    "mean_revert": {
        "key": "mean_revert",
        "title": "Mean reversion",
        "description": (
            "TRV's true value is pulled back toward its $100.00 anchor: a gap "
            "from $100 shrinks by about half every 40 ticks, while random "
            "shocks (about $0.28 per tick) keep knocking it around. It is "
            "usually within about $1.50 of $100 and rarely more than $3 away. "
            "An analyst publishes an estimate every 5 ticks (error sd $0.80)."),
        "assets": ["TRV"],
        "ticks": 1000,
        "start_prices": {"TRV": 10000},
        "process": {"type": "mean_revert", "half_life": 40, "sigma": 0.28},
        "hint_sources": {
            "analyst": {"noise": 0.80, "description": "Estimate of TRV every 5 ticks."},
        },
        "hint_schedule": {
            "analyst": {"every": 5},
        },
        "limits": dict(_LIMITS),
        "band_pct": 0.2,
        "lambda": 0.5,
        "house": {},
    },
    "jumps": {
        "key": "jumps",
        "title": "Jumps",
        "description": (
            "SESA's true value drifts like a gentle random walk near $100, but "
            "several times per match it jumps by a few dollars, up or down. "
            "Insider: very precise (error sd $0.10) but rare. Rumour: frequent "
            "and noisy (error sd $0.80), and about 1 in 20 is off by several "
            "dollars. Newswire: reports the new value on the tick a jump "
            "happens (error sd $0.25). Jumps make big positions risky, so the "
            "position limit in this round is 20 units."),
        "assets": ["SESA"],
        "ticks": 1000,
        "start_prices": {"SESA": 10000},
        "process": {
            "type": "jumps", "sigma": 0.08, "initial_sd": 1.0,
            "jump_count": [7, 10], "jump_size": [2.0, 4.0], "jump_margin": 20,
        },
        "hint_sources": {
            "insider": {"noise": 0.10,
                        "description": "Very precise estimate, at random about once every 50 ticks."},
            "rumour": {"noise": 0.80,
                       "description": "Noisy estimate on about 2 ticks in 5; about 1 in 20 is way off."},
            "newswire": {"noise": 0.25,
                         "description": "Fires on the tick SESA jumps, with the new value."},
        },
        "hint_schedule": {
            "insider": {"prob": 0.02},
            "rumour": {"prob": 0.4, "outlier_prob": 0.05, "outlier_size": [4.0, 8.0]},
            "newswire": {"on_jumps": True},
        },
        "limits": dict(_LIMITS, position_limit=20),
        "band_pct": 0.2,
        "lambda": 0.5,
        # The house trusts the insider fully (smoothing 1.0) so its fair value
        # doesn't sit dollars away after a jump; the wider spread pays for it.
        "house": {"market_maker": {"smoothing": 1.0, "half_spread": 0.30, "skew": 0.01}},
    },
    "pairs": {
        "key": "pairs",
        "title": "Pairs",
        "description": (
            "Two linked assets. WDCC's true value is a random walk near $100. "
            "UOA = 0.5 x WDCC + a gap, where the gap wanders but is pulled "
            "back toward $0 (it halves in about 50 ticks and is usually within "
            "about $1 of $0), so UOA sits near $50. WDCC desk: estimate of "
            "WDCC every 4 ticks (error sd $0.30). UOA desk: estimate of UOA "
            "every 8 ticks (error sd $0.50)."),
        "assets": ["WDCC", "UOA"],
        "ticks": 1000,
        "start_prices": {"WDCC": 10000, "UOA": 5000},
        "process": {
            "type": "pairs", "leader": "WDCC", "follower": "UOA",
            "sigma": 0.12, "initial_sd": 1.0, "beta": 0.5,
            "spread_half_life": 50, "spread_sigma": 0.08,
        },
        "hint_sources": {
            "wdcc_desk": {"noise": 0.30, "description": "Estimate of WDCC every 4 ticks."},
            "uoa_desk": {"noise": 0.50, "description": "Estimate of UOA every 8 ticks."},
        },
        "hint_schedule": {
            "wdcc_desk": {"assets": ["WDCC"], "every": 4},
            "uoa_desk": {"assets": ["UOA"], "every": 8, "offset": 2},
        },
        "limits": dict(_LIMITS),
        "band_pct": 0.2,
        "lambda": 0.5,
        "house": {"market_maker": {"delay": 3}},
    },
}

# The upload test: the random-walk round, short.
_smoke = copy.deepcopy(ROUNDS["random_walk"])
_smoke["key"] = "smoke"
_smoke["title"] = "Smoke test"
_smoke["description"] = (
    "Upload check: the random-walk round (DEVS near $100, analyst estimate "
    "every 5 ticks, error sd $0.40) over 200 ticks. Your bot must start and "
    "answer every tick in time.")
_smoke["ticks"] = 200
ROUNDS["smoke"] = _smoke


def get_round(key):
    """A deep copy of one round config, safe to modify."""
    if key not in ROUNDS:
        raise KeyError(f"unknown round {key!r}, known: {sorted(ROUNDS)}")
    return copy.deepcopy(ROUNDS[key])


def deep_merge(base, overrides):
    """A new dict: overrides merged into base, recursing into nested dicts.
    Anything else in overrides (numbers, lists, None) replaces the value."""
    out = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def public_info(round_cfg):
    """The parts of a round a team may see (INFO uses these), deep-copied."""
    out = {"round": round_cfg["key"]}
    for key in PUBLIC_KEYS:
        if key != "key":
            out[key] = copy.deepcopy(round_cfg[key])
    return out


def _fail(key, problem):
    raise ValueError(f"round {key!r}: {problem}")


def _is_int(value):
    return type(value) is int


def _is_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _check_pair(key, name, value, low):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not _is_number(value[0]) or not _is_number(value[1])
            or value[0] < low or value[1] < value[0]):
        _fail(key, f"{name} must be [lo, hi] with {low} <= lo <= hi")


def validate(round_cfg):
    """Raise ValueError if a round config is malformed. Returns the config."""
    key = round_cfg.get("key")
    required = PUBLIC_KEYS + ("process", "hint_schedule", "house")
    for name in required:
        if name not in round_cfg:
            _fail(key, f"missing {name!r}")
    assets = round_cfg["assets"]
    if (not isinstance(assets, list) or not assets
            or len(set(assets)) != len(assets)
            or not all(type(a) is str and a for a in assets)):
        _fail(key, "assets must be a non-empty list of unique names")
    ticks = round_cfg["ticks"]
    if not _is_int(ticks) or ticks < 1:
        _fail(key, "ticks must be an int >= 1")
    for asset in assets:
        price = round_cfg["start_prices"].get(asset)
        if not _is_int(price) or price < 1:
            _fail(key, f"start price of {asset} must be an int number of cents >= 1")
    limits = round_cfg["limits"]
    for name in LIMIT_KEYS:
        if not _is_int(limits.get(name)) or limits[name] < 0:
            _fail(key, f"limits.{name} must be an int >= 0")
    band = round_cfg["band_pct"]
    if not _is_number(band) or not 0 < band < 1:
        _fail(key, "band_pct must be in (0, 1)")
    if not _is_number(round_cfg["lambda"]) or round_cfg["lambda"] < 0:
        _fail(key, "lambda must be >= 0")
    if not isinstance(round_cfg["house"], dict):
        _fail(key, "house must be a dict of overrides")

    sources = round_cfg["hint_sources"]
    schedule = round_cfg["hint_schedule"]
    if not isinstance(sources, dict) or not isinstance(schedule, dict) or not schedule:
        _fail(key, "hint_sources and hint_schedule must be non-empty dicts")
    if set(sources) != set(schedule):
        _fail(key, "hint_sources and hint_schedule must name the same sources")
    covered = set()
    for name, spec in schedule.items():
        public = sources[name]
        if set(public) != {"noise", "description"} or type(public["description"]) is not str:
            _fail(key, f"hint source {name!r} must have exactly noise and description")
        noise = spec.get("noise", public["noise"])
        if not _is_number(noise) or noise < 0:
            _fail(key, f"hint source {name!r} needs a noise sd >= 0 (public or private)")
        src_assets = spec.get("assets", assets)
        if not src_assets or not all(a in assets for a in src_assets):
            _fail(key, f"hint source {name!r} covers unknown assets")
        covered.update(src_assets)
        fires = False
        if "every" in spec:
            if not _is_int(spec["every"]) or spec["every"] < 1:
                _fail(key, f"hint source {name!r}: every must be an int >= 1")
            if not _is_int(spec.get("offset", 0)):
                _fail(key, f"hint source {name!r}: offset must be an int")
            fires = True
        if "prob" in spec:
            if not _is_number(spec["prob"]) or not 0 <= spec["prob"] <= 1:
                _fail(key, f"hint source {name!r}: prob must be in [0, 1]")
            fires = True
        if spec.get("on_jumps"):
            if round_cfg["process"].get("type") != "jumps":
                _fail(key, f"hint source {name!r}: on_jumps needs a jumps process")
            fires = True
        if not fires:
            _fail(key, f"hint source {name!r} never fires (needs every, prob or on_jumps)")
        if spec.get("outlier_prob", 0):
            if not _is_number(spec["outlier_prob"]) or not 0 <= spec["outlier_prob"] <= 1:
                _fail(key, f"hint source {name!r}: outlier_prob must be in [0, 1]")
            _check_pair(key, f"{name}.outlier_size", spec.get("outlier_size"), 0)
    if covered != set(assets):
        _fail(key, "every asset needs at least one hint source (tick 0 hint)")

    proc = round_cfg["process"]
    kind = proc.get("type")
    if kind not in PROCESS_TYPES:
        _fail(key, f"unknown process type {kind!r}")
    if kind == "mean_revert":
        names = ("half_life", "sigma")
    elif kind == "pairs":
        names = ("sigma", "beta", "spread_half_life", "spread_sigma")
        if (proc.get("leader") not in assets or proc.get("follower") not in assets
                or proc["leader"] == proc["follower"] or len(assets) != 2):
            _fail(key, "pairs needs two assets: a leader and a follower")
    else:
        names = ("sigma",)
    for name in names:
        if not _is_number(proc.get(name)) or proc[name] < 0:
            _fail(key, f"process.{name} must be a number >= 0")
    for name in ("half_life", "spread_half_life"):
        if name in names and proc[name] <= 0:
            _fail(key, f"process.{name} must be > 0")
    if not _is_number(proc.get("initial_sd", 0)) or proc.get("initial_sd", 0) < 0:
        _fail(key, "process.initial_sd must be >= 0")
    if kind == "jumps":
        _check_pair(key, "process.jump_count", proc.get("jump_count"), 0)
        _check_pair(key, "process.jump_size", proc.get("jump_size"), 0)
        if not all(_is_int(v) for v in proc["jump_count"]):
            _fail(key, "process.jump_count must be ints")
        margin = proc.get("jump_margin", DEFAULT_JUMP_MARGIN)
        if not _is_int(margin) or margin < 1:
            _fail(key, "process.jump_margin must be an int >= 1")
    return round_cfg
