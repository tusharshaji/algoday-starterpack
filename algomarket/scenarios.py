"""True-value paths and hint schedules (DESIGN.md section 7, in the
organisers' design notes, which are not in the starter kit).

generate(round_cfg, seed) is a pure function of its inputs. Every draw comes
from a numpy Generator seeded with [seed, stream, index]: one stream per
asset path, one per hint source, one for the tick-0 hints, so tuning one
source never changes the paths or the other sources. Stream ids used here:
1 = paths, 2 = hint sources, 4 = tick-0 hints (exchange.py uses 3).

Values are float cents. See rounds.py for the config keys.
"""
from dataclasses import dataclass
import math

import numpy as np

from .rounds import DEFAULT_JUMP_MARGIN

PATH_STREAM = 1
HINT_STREAM = 2
OPENING_STREAM = 4

# Safety floor for true values (cents). Never reached at sane parameters
# (it would take a ~20 sd move); it only keeps prices positive if a tuned
# config goes wild.
MIN_VALUE = 100.0


@dataclass
class Scenario:
    round_key: str
    seed: int
    ticks: int
    assets: list
    true_value: dict    # asset -> numpy float array of cents, length ticks
    hints_at: list      # hints_at[t] -> [(asset, value_cents, source)], released at t
    jump_ticks: dict    # asset -> [t] (private; empty lists unless the round jumps)

    def true_values_at(self, t):
        """{asset: V[asset][t]} as plain floats (cents)."""
        out = {}
        for asset in self.assets:
            out[asset] = float(self.true_value[asset][t])
        return out

    def final_values(self):
        return self.true_values_at(self.ticks - 1)


def check_seed(seed):
    """Seeds are non-negative ints (numpy ints ok, bools not)."""
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError(f"seed must be an int >= 0, got {seed!r}")
    return int(seed)


def _rng(seed, *stream):
    return np.random.default_rng([seed, *stream])


def generate(round_cfg, seed):
    seed = check_seed(seed)
    ticks = int(round_cfg["ticks"])
    assets = list(round_cfg["assets"])
    values, jumps = _paths(round_cfg, seed, ticks, assets)
    for asset in assets:
        values[asset] = np.maximum(values[asset], MIN_VALUE)
    hints_at = _hints(round_cfg, seed, ticks, assets, values, jumps)
    return Scenario(round_cfg.get("key"), seed, ticks, assets, values, hints_at, jumps)


# ------------------------------------------------------------------ paths

def _walk(rng, ticks, start, sigma, initial_sd, jumps=None):
    """Gaussian random walk in cents; steps[t] is the move from t-1 to t."""
    v0 = start + initial_sd * rng.standard_normal()
    steps = sigma * rng.standard_normal(ticks)
    steps[0] = 0.0
    if jumps is not None:
        steps = steps + jumps
    return v0 + np.cumsum(steps)


def _ou(rng, ticks, mean, half_life, sigma):
    """Exact discrete OU in cents, started from its stationary distribution."""
    phi = math.exp(-math.log(2.0) / half_life)
    stationary_sd = sigma / math.sqrt(1.0 - phi * phi)
    first = mean + stationary_sd * rng.standard_normal()
    shocks = sigma * rng.standard_normal(ticks)
    out = np.empty(ticks)
    out[0] = first
    prev = first
    for t in range(1, ticks):
        prev = mean + phi * (prev - mean) + shocks[t]
        out[t] = prev
    return out


def _jump_series(rng, ticks, proc):
    """(per-tick jump array in cents, sorted jump ticks)."""
    count_lo, count_hi = proc["jump_count"]
    size_lo, size_hi = proc["jump_size"]
    margin = max(1, int(proc.get("jump_margin", DEFAULT_JUMP_MARGIN)))
    count = int(rng.integers(int(count_lo), int(count_hi) + 1))
    candidates = np.arange(margin, max(margin, ticks - margin))
    count = min(count, len(candidates))
    chosen = np.sort(rng.choice(candidates, size=count, replace=False)) if count else np.zeros(0, int)
    sizes = rng.uniform(size_lo, size_hi, count) * 100.0
    signs = np.where(rng.random(count) < 0.5, -1.0, 1.0)
    series = np.zeros(ticks)
    series[chosen] = sizes * signs
    return series, [int(t) for t in chosen]


def _paths(cfg, seed, ticks, assets):
    proc = cfg["process"]
    kind = proc["type"]
    start = cfg["start_prices"]
    values = {}
    jumps = {}
    for asset in assets:
        jumps[asset] = []
    if kind == "random_walk":
        for i, asset in enumerate(assets):
            rng = _rng(seed, PATH_STREAM, i)
            values[asset] = _walk(rng, ticks, float(start[asset]), proc["sigma"] * 100.0,
                                  proc.get("initial_sd", 0.0) * 100.0)
    elif kind == "mean_revert":
        for i, asset in enumerate(assets):
            rng = _rng(seed, PATH_STREAM, i)
            values[asset] = _ou(rng, ticks, float(start[asset]), proc["half_life"],
                                proc["sigma"] * 100.0)
    elif kind == "jumps":
        for i, asset in enumerate(assets):
            rng = _rng(seed, PATH_STREAM, i)
            # Diffusion first, then the jumps, all from this asset's stream.
            v0 = float(start[asset]) + proc.get("initial_sd", 0.0) * 100.0 * rng.standard_normal()
            steps = proc["sigma"] * 100.0 * rng.standard_normal(ticks)
            steps[0] = 0.0
            series, chosen = _jump_series(rng, ticks, proc)
            values[asset] = v0 + np.cumsum(steps + series)
            jumps[asset] = chosen
    elif kind == "pairs":
        leader = proc["leader"]
        follower = proc["follower"]
        rng = _rng(seed, PATH_STREAM, assets.index(leader))
        lead = _walk(rng, ticks, float(start[leader]), proc["sigma"] * 100.0,
                     proc.get("initial_sd", 0.0) * 100.0)
        rng = _rng(seed, PATH_STREAM, assets.index(follower))
        gap = _ou(rng, ticks, 0.0, proc["spread_half_life"], proc["spread_sigma"] * 100.0)
        beta = proc["beta"]
        anchor = float(start[follower]) - beta * float(start[leader])
        values[leader] = lead
        values[follower] = beta * lead + anchor + gap
    else:
        raise ValueError(f"unknown process type {kind!r}")
    return values, jumps


# ------------------------------------------------------------------ hints

def _noise_cents(cfg, name):
    spec = cfg["hint_schedule"][name]
    noise = spec.get("noise", cfg["hint_sources"][name]["noise"])
    if noise is None:
        raise ValueError(f"hint source {name!r} has no noise sd (public or private)")
    return float(noise) * 100.0


def _firing_ticks(spec, ticks, rng, jump_ticks):
    fire = np.zeros(ticks, dtype=bool)
    every = spec.get("every")
    if every:
        idx = np.arange(ticks)
        fire |= (idx - spec.get("offset", 0)) % every == 0
    prob = spec.get("prob")
    if prob:
        fire |= rng.random(ticks) < prob
    if spec.get("on_jumps") and jump_ticks:
        fire[np.asarray(jump_ticks, dtype=int)] = True
    fire[0] = False
    return np.flatnonzero(fire)


def _value(v):
    return round(float(v), 2)


def _hints(cfg, seed, ticks, assets, values, jumps):
    schedule = cfg["hint_schedule"]
    hints_at = []
    for _ in range(ticks):
        hints_at.append([])

    # Tick 0: one hint per asset, from the first source covering it.
    opening = _rng(seed, OPENING_STREAM)
    for asset in assets:
        source = None
        for name, spec in schedule.items():
            if source is None and asset in spec.get("assets", assets):
                source = name
        if source is None:
            raise ValueError(f"no hint source covers {asset}")
        z = opening.standard_normal()
        hints_at[0].append((asset, _value(values[asset][0] + _noise_cents(cfg, source) * z), source))

    for k, (name, spec) in enumerate(schedule.items()):
        rng = _rng(seed, HINT_STREAM, k)
        noise = _noise_cents(cfg, name)
        outlier_prob = spec.get("outlier_prob", 0.0)
        for asset in spec.get("assets", assets):
            fired = _firing_ticks(spec, ticks, rng, jumps[asset])
            n = len(fired)
            vals = values[asset][fired] + noise * rng.standard_normal(n)
            if outlier_prob:
                lo, hi = spec["outlier_size"]
                is_out = rng.random(n) < outlier_prob
                shift = rng.uniform(lo, hi, n) * 100.0 * np.where(rng.random(n) < 0.5, -1.0, 1.0)
                vals = vals + np.where(is_out, shift, 0.0)
            for t, v in zip(fired.tolist(), vals.tolist()):
                hints_at[t].append((asset, _value(v), name))
    return hints_at
