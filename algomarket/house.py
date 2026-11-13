"""House bots: a market maker and noise traders (DESIGN.md section 11, in the
organisers' design notes, which are not in the starter kit).

    build(house_cfg, info, seed) -> [(name, bot, limits_or_None), ...]

Each bot has on_tick(state) like a team bot and gets the same SDK State;
the runner wraps it in participants.InProcessBot(name, bot, kind="house").
limits is a complete limits dict for that bot (the round's limits with the
house overrides applied), or None for the round's own limits. A bot's
phase_b_slot attribute is its place in phase B (new orders): the market
maker stays in the seeded shuffle with the teams, the noise traders go
last (after everyone, still shuffled among themselves).

house_cfg is a plain dict of overrides merged over DEFAULTS, one level deep
per bot type, e.g. {"noise_traders": {"count": 4, "prob": 0.5}}. None or {}
gives the defaults; {"market_maker": None} (or "count": 0) removes a type.
Unknown keys raise ValueError, so config typos fail loudly. Money is in
dollars.

market_maker
  count         how many market makers (normally 1)
  half_spread   distance from fair value to the first bid/ask level
  levels        price levels quoted on each side
  level_step    extra distance per further level
  size          qty per level
  smoothing     weight of a new hint from the most precise source in the
                fair-value average (0..1; lower = smoother and slower).
                Noisier sources get less: smoothing * (best_noise / noise)^2.
                Sources with unpublished noise count as precise.
  delay         ticks between a hint's release and the market maker using it
  skew          quotes move this much against each unit of inventory, with
                no cap: past half_spread / skew units, one first-level quote
                is on the far side of its own fair value (calibrated so)
  requote_move  requote when fair value (with skew) moves this much
  loss_cap      stop quoting for good once its own marked P&L < -loss_cap
  limits        overrides for the round's limits (a dict), or None

noise_traders
  count         how many noise traders
  prob          chance of trading on any tick
  min_qty, max_qty   order size range (inclusive)
  flatten_at    once |position| >= flatten_at * position_limit it only
                trades back toward flat
  max_slippage  None: IOC at the band edge (any price). A number:
                IOC limit at the recent-hint median +/- this many dollars
                (still inside the band), so a thin book can't hand someone
                a band-edge fill.
  limits        overrides for the round's limits, or None

Deterministic: every random draw comes from a numpy Generator seeded from
(seed, bot index), and noise traders draw the same numbers every tick
whatever the market does.
"""
import copy
import math
from collections import deque

import numpy as np

from .sdk import buy, cancel_all, sell

HOUSE_SALT = 0x484F555345  # keeps house streams apart from other seeded streams
# Noise traders draw this many ticks' random numbers at once (NoiseTrader._next_draws).
DRAW_BATCH = 100

DEFAULTS = {
    "market_maker": {
        "count": 1,
        "half_spread": 0.20,
        "levels": 3,
        "level_step": 0.10,
        "size": 5,
        "smoothing": 0.2,
        "delay": 2,
        "skew": 0.01,
        "requote_move": 0.05,
        "loss_cap": 5000.0,
        "limits": {
            "position_limit": 500,
            "max_order_qty": 100,
            "max_open_orders": 40,
            "max_actions_per_tick": 60,
        },
    },
    "noise_traders": {
        "count": 3,
        "prob": 0.3,
        "min_qty": 1,
        "max_qty": 5,
        "flatten_at": 0.8,
        "max_slippage": 2.0,
        "limits": None,
    },
}


def merge_config(house_cfg):
    """DEFAULTS with house_cfg's overrides applied (a new dict)."""
    cfg = copy.deepcopy(DEFAULTS)
    if not house_cfg:
        return cfg
    if not isinstance(house_cfg, dict):
        raise ValueError(f"house config must be a dict, got {type(house_cfg).__name__}")
    for kind, overrides in house_cfg.items():
        if kind not in DEFAULTS:
            raise ValueError(f"unknown house bot type {kind!r} (expected one of {sorted(DEFAULTS)})")
        if overrides is None:
            cfg[kind]["count"] = 0
        elif isinstance(overrides, dict):
            for key, value in overrides.items():
                if key not in DEFAULTS[kind]:
                    raise ValueError(f"unknown {kind} setting {key!r} (expected one of {sorted(DEFAULTS[kind])})")
                if key == "limits" and isinstance(value, dict) and isinstance(cfg[kind]["limits"], dict):
                    cfg[kind]["limits"].update(value)
                else:
                    cfg[kind][key] = copy.deepcopy(value)
        else:
            raise ValueError(f"house config for {kind!r} must be a dict or None")
    _check(cfg)
    return cfg


def _check(cfg):
    mm = cfg["market_maker"]
    nt = cfg["noise_traders"]
    problems = []

    def need(ok, message):
        if not ok:
            problems.append(message)

    def whole(value, low):
        return type(value) is int and value >= low

    for kind, section in (("market_maker", mm), ("noise_traders", nt)):
        need(whole(section["count"], 0), f"{kind}.count must be an int >= 0")
        need(section["limits"] is None or isinstance(section["limits"], dict),
             f"{kind}.limits must be a dict or None")
    need(_number(mm["half_spread"]) and mm["half_spread"] >= 0.01, "market_maker.half_spread must be >= 0.01")
    need(whole(mm["levels"], 1), "market_maker.levels must be an int >= 1")
    need(_number(mm["level_step"]) and mm["level_step"] >= 0, "market_maker.level_step must be >= 0")
    need(whole(mm["size"], 1), "market_maker.size must be an int >= 1")
    need(_number(mm["smoothing"]) and 0 < mm["smoothing"] <= 1, "market_maker.smoothing must be in (0, 1]")
    need(whole(mm["delay"], 0), "market_maker.delay must be an int >= 0")
    need(_number(mm["skew"]) and mm["skew"] >= 0, "market_maker.skew must be >= 0")
    need(_number(mm["requote_move"]) and mm["requote_move"] >= 0, "market_maker.requote_move must be >= 0")
    need(_number(mm["loss_cap"]) and mm["loss_cap"] > 0, "market_maker.loss_cap must be > 0")
    need(_number(nt["prob"]) and 0 <= nt["prob"] <= 1, "noise_traders.prob must be in [0, 1]")
    need(whole(nt["min_qty"], 1) and whole(nt["max_qty"], 1) and nt["min_qty"] <= nt["max_qty"],
         "noise_traders needs ints 1 <= min_qty <= max_qty")
    need(_number(nt["flatten_at"]) and 0 < nt["flatten_at"] <= 1, "noise_traders.flatten_at must be in (0, 1]")
    need(nt["max_slippage"] is None or (_number(nt["max_slippage"]) and nt["max_slippage"] > 0),
         "noise_traders.max_slippage must be > 0 or None")
    if problems:
        raise ValueError("bad house config: " + "; ".join(problems))


def _rng(seed, index):
    return np.random.default_rng(np.random.SeedSequence([int(seed) % 2**63, HOUSE_SALT, index]))


def _limits(round_limits, overrides):
    if overrides is None:
        return None
    merged = dict(round_limits)
    merged.update(overrides)
    return merged


def build(house_cfg, info, seed):
    """House bots for one match: [(name, bot, limits_or_None)]."""
    cfg = merge_config(house_cfg)
    assets = list(info.get("assets") or [])
    round_limits = dict(info.get("limits") or {})
    start_prices = info.get("start_prices") or {}
    noise = {}
    for source, details in (info.get("hint_sources") or {}).items():
        noise[source] = (details or {}).get("noise")

    bots = []
    index = 0
    mm = cfg["market_maker"]
    for i in range(mm["count"]):
        limits = _limits(round_limits, mm["limits"])
        name = "house-mm" if mm["count"] == 1 else f"house-mm-{i + 1}"
        bot = MarketMaker(assets, start_prices, noise, limits or round_limits, mm)
        bots.append((name, bot, limits))
        index += 1
    nt = cfg["noise_traders"]
    for i in range(nt["count"]):
        limits = _limits(round_limits, nt["limits"])
        bot = NoiseTrader(_rng(seed, index), assets, start_prices, limits or round_limits, nt)
        bots.append((f"house-noise-{i + 1}", bot, limits))
        index += 1
    return bots


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _median(values):
    """float(np.median(values)) of a few finite floats, without numpy's call
    overhead: the middle value, or the mean of the middle two."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def source_weights(noise):
    """Hint source -> weight in (0, 1]: (best published noise / its noise)^2.
    Unknown or unpublished noise counts as 1."""
    published = []
    for value in noise.values():
        if _number(value) and value > 0:
            published.append(value)
    weights = {}
    for source, value in noise.items():
        if published and _number(value) and value > 0:
            weights[source] = (min(published) / value) ** 2
        else:
            weights[source] = 1.0
    return weights


class MarketMaker:
    """Quotes both sides around a slow, smoothed fair value.

    It uses each hint `delay` ticks late and averages heavily, so a bot that
    reacts to hints straight away can trade against its stale quotes.
    """

    # In the seeded shuffle with the teams: "first" was measured to cost
    # the house far more (jumps and mean_revert).
    phase_b_slot = "shuffle"

    def __init__(self, assets, start_prices, noise, limits, cfg):
        self.assets = list(assets)
        self.cfg = dict(cfg)
        self.limits = dict(limits)
        self.weights = source_weights(noise)
        self.fair = {}
        for asset in self.assets:
            cents = start_prices.get(asset)
            self.fair[asset] = cents / 100 if _number(cents) else None
        self.pending = []        # (usable_from_tick, asset, value, source)
        self.quoted = {}         # asset -> centre of the live quotes
        self.stopped = False

    def on_tick(self, state):
        if self.stopped:
            return []
        self._absorb_hints(state)
        if self.marked_pnl(state) < -self.cfg["loss_cap"]:
            self.stopped = True
            return [cancel_all()]
        filled = set()
        for fill in state.fills:
            filled.add(fill.asset)
        live = set()
        for order in state.open_orders:
            live.add(order.asset)
        actions = []
        for asset in self.assets:
            fair = self.fair.get(asset)
            if fair is None:
                continue
            position = state.position(asset)
            centre = fair - self.cfg["skew"] * position
            last = self.quoted.get(asset)
            stale = last is None or abs(centre - last) >= self.cfg["requote_move"]
            if stale or asset in filled or asset not in live:
                actions.append(cancel_all(asset))
                actions.extend(self._quotes(state, asset, centre, position))
                self.quoted[asset] = centre
        return actions

    def _absorb_hints(self, state):
        for hint in state.hints:
            if _number(hint.value):
                self.pending.append((state.tick + self.cfg["delay"], hint.asset, hint.value, hint.source))
        waiting = []
        for item in self.pending:
            usable_from, asset, value, source = item
            if usable_from > state.tick:
                waiting.append(item)
            elif asset in self.fair:
                fair = self.fair[asset]
                if fair is None:
                    self.fair[asset] = value
                else:
                    weight = self.cfg["smoothing"] * self.weights.get(source, 1.0)
                    self.fair[asset] = fair + weight * (value - fair)
        self.pending = waiting

    def marked_pnl(self, state):
        """Cash plus positions valued at its own fair values (dollars)."""
        total = state.cash
        for asset in self.assets:
            fair = self.fair.get(asset)
            if fair is not None:
                total += state.position(asset) * fair
        return total

    def _quotes(self, state, asset, centre, position):
        limit = self.limits.get("position_limit", 0)
        size = min(self.cfg["size"], self.limits.get("max_order_qty", self.cfg["size"]))
        band = state.band(asset)
        room_buy = limit - position
        room_sell = limit + position
        actions = []
        for level in range(self.cfg["levels"]):
            offset = self.cfg["half_spread"] + level * self.cfg["level_step"]
            bid = math.floor((centre - offset) * 100 + 1e-6) / 100
            ask = math.ceil((centre + offset) * 100 - 1e-6) / 100
            bid_ok = bid >= 0.01 and (band is None or band[0] <= bid <= band[1])
            ask_ok = band is None or band[0] <= ask <= band[1]
            qty = min(size, room_buy)
            if bid_ok and qty > 0:
                actions.append(buy(asset, bid, qty))
                room_buy -= qty
            qty = min(size, room_sell)
            if ask_ok and qty > 0:
                actions.append(sell(asset, ask, qty))
                room_sell -= qty
        return actions


class NoiseTrader:
    """Trades at random: uninformed flow that pays the spread."""

    # After every other bot in phase B (match._phase_b_slot): its IOCs meet
    # this tick's fresh quotes, never a book whose makers just cancelled, so
    # a quote nobody updates can't live off the noise flow.
    phase_b_slot = "last"

    def __init__(self, rng, assets, start_prices, limits, cfg):
        self.rng = rng
        self.assets = list(assets)
        self.cfg = dict(cfg)
        self.limits = dict(limits)
        self.recent = {}
        for asset in self.assets:
            self.recent[asset] = deque(maxlen=5)
            cents = start_prices.get(asset)
            if _number(cents):
                self.recent[asset].append(cents / 100)
        # The next ticks' draws, last tick first (_next_draws).
        self._draws = []

    def on_tick(self, state):
        for hint in state.hints:
            if hint.asset in self.recent and _number(hint.value):
                self.recent[hint.asset].append(hint.value)
        # Same four draws every tick, so the flow doesn't depend on the market.
        trade_draw, side_draw, which, qty = self._next_draws()
        if trade_draw >= self.cfg["prob"] or not self.assets:
            return []
        asset = self.assets[which]
        position = state.position(asset)
        limit = self.limits.get("position_limit", 0)
        if position >= self.cfg["flatten_at"] * limit:
            side = "sell"
        elif position <= -self.cfg["flatten_at"] * limit:
            side = "buy"
        elif side_draw < 0.5:
            side = "buy"
        else:
            side = "sell"
        if side == "buy":
            room = limit - position
        else:
            room = limit + position
        qty = min(qty, room, self.limits.get("max_order_qty", qty))
        if qty <= 0:
            return []
        price = self._limit_price(state, asset, side)
        if price is None:
            # IOC at the band edge, spelled out: the SDK's buy_now/sell_now
            # now cap the price near the best quote, which isn't this option.
            band = state.band(asset)
            if band is None:
                return []
            price = band[1] if side == "buy" else band[0]
        if side == "buy":
            return [buy(asset, price, qty, ioc=True)]
        return [sell(asset, price, qty, ioc=True)]

    def _next_draws(self):
        """This tick's (trade_draw, side_draw, asset index, qty). They never
        depend on the market, so they are drawn DRAW_BATCH ticks at a time:
        the same calls in the same order give the same numbers, and one
        tick at a time numpy's call overhead was most of a noise trader's
        time."""
        if not self._draws:
            batch = []
            for _ in range(DRAW_BATCH):
                trade_draw, side_draw = self.rng.random(2)
                which = int(self.rng.integers(max(1, len(self.assets))))
                qty = int(self.rng.integers(self.cfg["min_qty"], self.cfg["max_qty"] + 1))
                batch.append((trade_draw, side_draw, which, qty))
            batch.reverse()
            self._draws = batch
        return self._draws.pop()

    def _limit_price(self, state, asset, side):
        slippage = self.cfg["max_slippage"]
        recent = self.recent.get(asset)
        if slippage is None or not recent:
            return None
        reference = _median(recent)
        band = state.band(asset)
        if side == "buy":
            price = math.floor((reference + slippage) * 100) / 100
            if band is not None:
                price = min(price, band[1])
        else:
            price = math.ceil((reference - slippage) * 100) / 100
            if band is not None:
                price = max(price, band[0])
        if price < 0.01:
            return None
        return price
