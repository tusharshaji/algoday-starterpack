"""Accounts, risk checks and tick processing (DESIGN.md sections 6 and 9, in
the organisers' design notes, which are not in the starter kit).

Prices, cash and actions are integer cents; hint values and equity are float
cents. One Exchange runs one match. The match loop drives it, per tick t:

    ex.begin_tick(t, scenario.hints_at[t])    # release hints, move bands
    state = ex.state_for(pid)                  # wire STATE dict, per active pid
    ex.process({pid: actions, ...})            # any JSON; None = no response
    ex.end_tick(scenario.true_values_at(t))    # mark equity at V[t]
    ex.check_invariants()                      # cheap, raises on a bug

and ex.settle() after the last tick. ex.stop(pid) at any point between
calls. Bot input never raises: anything malformed is rejected with a reason
the bot sees in its next state.

Order ids: participant pid's k-th accepted order (k = 0, 1, ...) gets id
k * N + pid + 1. Unique across participants and assets and increasing per
participant, so a bot's own ids say nothing about other bots' orders (one
shared counter would: the gaps would count everyone else's orders).

Phase-B order: a seeded shuffle per tick, a pure function of (seed, t),
then regrouped by each participant's slot: "first", "shuffle", "last"
(stable, so each group keeps the shuffled order). The match runner puts
the house noise traders last: their orders meet the quotes every other
bot has refreshed this tick, never a book its makers have just cancelled.
"""
import math

import numpy as np

from . import engine
from .book import MAX_ORDER_ID
from .engine import OrderBook

BUY = 0
SELL = 1
SIDES = ("buy", "sell")
ENGINE_CANCEL_REASONS = {1: "self_trade", 2: "ioc"}

BOOK_LEVELS = 5
MAX_PRICE = 10**12              # the engine's limit on price and qty
LIMIT_KEYS = ("position_limit", "max_order_qty", "max_open_orders", "max_actions_per_tick")
# Bounds the size of one state's reject list when a bot sends a huge list.
MAX_REPORTED_REJECTS = 1000
SHUFFLE_STREAM = 3              # numpy stream id for the phase-B shuffle
MAX_PRECOMPUTED_TICKS = 100000
# Phase-B slots: "first" pids go before the shuffled ones, "last" after; each
# group keeps the tick's seeded order. Only the match runner sets them (the
# house noise traders go last); team bots are always "shuffle".
SLOT_RANK = {"first": 0, "shuffle": 1, "last": 2}

# Reject reasons (section 6)
BAD_ACTION = "bad_action"
UNKNOWN_ASSET = "unknown_asset"
BAD_QTY = "bad_qty"
BAD_PRICE = "bad_price"
PRICE_BAND = "price_band"
POSITION_LIMIT = "position_limit"
TOO_MANY_ORDERS = "too_many_orders"
TOO_MANY_ACTIONS = "too_many_actions"
UNKNOWN_ORDER = "unknown_order"
REJECT_REASONS = (BAD_ACTION, UNKNOWN_ASSET, BAD_QTY, BAD_PRICE, PRICE_BAND,
                  POSITION_LIMIT, TOO_MANY_ORDERS, TOO_MANY_ACTIONS, UNKNOWN_ORDER)


def _as_int(value):
    """A plain int, or None. Booleans are not ints; numpy ints are."""
    if type(value) is int:
        return value
    if isinstance(value, np.integer):
        return int(value)
    return None


def band_for(ref, band_pct):
    """(lo, hi) in cents: [ceil(ref * (1 - pct)), floor(ref * (1 + pct))].

    Rounded to 6 dp before ceil/floor so float noise (8000.000000000001)
    can't move an edge by a cent. Clamped to the engine's 1..10**12; an
    empty band (hi < lo) rejects every order.
    """
    lo = math.ceil(round(ref * (1.0 - band_pct), 6))
    hi = math.floor(round(ref * (1.0 + band_pct), 6))
    if lo < 1:
        lo = 1
    if hi > MAX_PRICE:
        hi = MAX_PRICE
    return lo, hi


def _check_limits(limits):
    out = {}
    for key in LIMIT_KEYS:
        value = limits.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"limit {key} must be an int >= 0, got {value!r}")
        out[key] = value
    return out


class _Events:
    """What one tick produced; the next tick's states report it."""
    __slots__ = ("trades", "fills", "cancelled", "rejects")

    def __init__(self, n):
        self.trades = []
        self.fills = [[] for _ in range(n)]
        self.cancelled = [[] for _ in range(n)]
        self.rejects = [[] for _ in range(n)]


class Exchange:
    def __init__(self, round_cfg, participants, seed):
        """participants: [(pid, kind, limits_or_None[, slot])] with pids 0..N-1 in order.

        limits_or_None overrides some or all of the round's limits for that
        participant (house bots may get bigger ones). slot (default
        "shuffle", also for None) places it in phase B: "first", "shuffle"
        or "last" (see SLOT_RANK).
        """
        if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
            raise ValueError(f"seed must be an int >= 0, got {seed!r}")
        self.seed = int(seed)
        self.round_key = round_cfg.get("key")
        self.assets = list(round_cfg["assets"])
        self._index = {}
        for i, asset in enumerate(self.assets):
            self._index[asset] = i
        if not self.assets or len(self._index) != len(self.assets):
            raise ValueError("assets must be a non-empty list of unique names")
        self.band_pct = float(round_cfg.get("band_pct", 0.2))
        self.ticks = int(round_cfg["ticks"])
        round_limits = _check_limits(round_cfg["limits"])
        start = round_cfg["start_prices"]
        self._start = [float(start[asset]) for asset in self.assets]

        self.kinds = []
        self.limits = []
        self.slots = []                         # phase-B slot per pid
        for expected, item in enumerate(participants):
            pid = item[0]
            if pid != expected:
                raise ValueError(f"participant pids must be 0..N-1 in order, got {pid!r} at {expected}")
            override = item[2] if len(item) > 2 else None
            merged = dict(round_limits)
            if override:
                for key, value in override.items():
                    if key not in LIMIT_KEYS:
                        raise ValueError(f"unknown limit {key!r}")
                    merged[key] = value
            self.limits.append(_check_limits(merged))
            self.kinds.append(item[1])
            slot = item[3] if len(item) > 3 and item[3] is not None else "shuffle"
            if type(slot) is not str or slot not in SLOT_RANK:
                raise ValueError(f"phase-B slot must be one of {list(SLOT_RANK)}, got {slot!r}")
            self.slots.append(slot)
        self._slot_ranks = np.array([SLOT_RANK[slot] for slot in self.slots], dtype=np.int64)
        n = len(self.kinds)
        self.n = n
        n_assets = len(self.assets)

        self.books = []
        for _ in range(n_assets):
            self.books.append(OrderBook())
        self.engine = getattr(engine, "NAME", "unknown")
        self.cash = [0] * n
        self.pos = [[0] * n_assets for _ in range(n)]
        self.active = [True] * n
        self.equity = [0.0] * n                 # latest mark, float cents
        self.equity_curve = [[] for _ in range(n)]
        self.trade_count = [0] * n
        self.volume = [0] * n
        self.orders_placed = [0] * n
        self.reject_count = [0] * n
        self.reject_reasons = [{} for _ in range(n)]    # reason -> count

        self.tick = -1
        self.settled = False
        self._processed = -1
        self._marked = -1
        self._ref = list(self._start)           # latest hint per asset (start price before any)
        self._band = [band_for(ref, self.band_pct) for ref in self._ref]
        self._hints = []
        self._prev = _Events(n)                 # events of tick t-1 (in this tick's states)
        self._cur = _Events(n)                  # events of tick t (being collected)
        self._depth = None                      # cached top-of-book snapshot
        self._marks = None                      # latest true values used for equity
        self.tick_trades = []                   # this tick: (t, asset, price, qty, buyer, seller, aggressor)
        self.last_order = []                    # phase-B participant order used this tick

        # Phase-B shuffles for every tick, from one stream: a pure function
        # of (seed, t), whoever stops or doesn't answer. Ticks past the table
        # (only in absurdly long matches) get their own derived stream.
        # Every row is then regrouped by slot (_slotted).
        rng = np.random.default_rng([self.seed, SHUFFLE_STREAM])
        rows = min(max(self.ticks, 1), MAX_PRECOMPUTED_TICKS)
        self._perms = self._slotted(rng.permuted(np.tile(np.arange(n), (rows, 1)), axis=1))

    # ------------------------------------------------------------ queries

    def limits_for(self, pid):
        return dict(self.limits[pid])

    def band(self, asset):
        return self._band[self._index[asset]]

    def position(self, pid, asset):
        return self.pos[pid][self._index[asset]]

    def positions_of(self, pid):
        out = {}
        for i, asset in enumerate(self.assets):
            out[asset] = self.pos[pid][i]
        return out

    def stats(self, pid):
        return {
            "trades": self.trade_count[pid],
            "volume": self.volume[pid],
            "orders": self.orders_placed[pid],
            "rejects": self.reject_count[pid],
            "reject_reasons": dict(self.reject_reasons[pid]),
            "final_positions": self.positions_of(pid),
        }

    def book_snapshot(self):
        """Per asset (bids, asks), each [(price, qty)] top 5 best first, cents."""
        if self._depth is None:
            snap = []
            for book in self.books:
                bids = []
                for price, qty in book.depth(BUY, BOOK_LEVELS):
                    bids.append((int(price), int(qty)))
                asks = []
                for price, qty in book.depth(SELL, BOOK_LEVELS):
                    asks.append((int(price), int(qty)))
                snap.append((bids, asks))
            self._depth = snap
        return self._depth

    def tick_summary(self):
        """What the replay recorder needs after end_tick (cents)."""
        return {
            "books": self.book_snapshot(),
            "trades": list(self.tick_trades),
            "equity": list(self.equity),
            "positions": [list(row) for row in self.pos],
        }

    def open_orders(self, pid):
        """[(order_id, asset_index, side, price, qty)] sorted by order id."""
        rows = []
        for i, book in enumerate(self.books):
            for order_id, side, price, qty in book.open_orders(pid):
                rows.append((int(order_id), i, int(side), int(price), int(qty)))
        rows.sort()
        return rows

    def state_for(self, pid):
        """The wire STATE dict (section 9) for pid at the current tick."""
        snap = self.book_snapshot()
        books = {}
        band = {}
        positions = {}
        row = self.pos[pid]
        for i, asset in enumerate(self.assets):
            bids, asks = snap[i]
            books[asset] = {"bids": [[p, q] for p, q in bids], "asks": [[p, q] for p, q in asks]}
            lo, hi = self._band[i]
            band[asset] = [lo, hi]
            positions[asset] = row[i]
        prev = self._prev
        open_orders = []
        for order_id, i, side, price, qty in self.open_orders(pid):
            open_orders.append({"order_id": order_id, "asset": self.assets[i],
                                "side": SIDES[side], "price": price, "qty": qty})
        return {
            "tick": self.tick,
            "cash": self.cash[pid],
            "positions": positions,
            "books": books,
            "band": band,
            "hints": [dict(h) for h in self._hints],
            "trades": [dict(x) for x in prev.trades],
            "fills": [dict(x) for x in prev.fills[pid]],
            "cancelled": [dict(x) for x in prev.cancelled[pid]],
            "rejects": [{"index": index, "reason": reason} for index, reason in prev.rejects[pid]],
            "open_orders": open_orders,
        }

    # ----------------------------------------------------------- the tick

    def begin_tick(self, t, hints=()):
        """Start tick t: last tick's events move into the states, hints at t
        are released and the bands follow them. hints: [(asset, cents, source)]."""
        if self.settled:
            raise RuntimeError("the match is already settled")
        if t != self.tick + 1:
            raise ValueError(f"expected tick {self.tick + 1}, got {t!r}")
        self.tick = t
        self._prev = self._cur
        self._cur = _Events(self.n)
        self.tick_trades = []
        released = []
        for asset, value, source in hints:
            value = float(value)
            # A non-finite hint would break the JSON protocol: never released.
            if math.isfinite(value):
                released.append({"asset": asset, "value": value, "source": source})
                i = self._index.get(asset) if type(asset) is str else None
                if i is not None:
                    self._ref[i] = value
        self._hints = released
        bands = []
        for ref in self._ref:
            bands.append(band_for(ref, self.band_pct))
        self._band = bands

    def process(self, actions_by_pid):
        """Phase A (every cancel), then phase B (new orders, participants in
        this tick's shuffled order, regrouped by slot: "first" ones, the
        shuffled ones, then "last" ones). actions_by_pid: {pid: actions} or
        a list indexed by pid; anything that isn't a list counts as no
        actions."""
        if self.tick < 0 or self.settled:
            raise RuntimeError("process() needs begin_tick() first")
        if self._processed == self.tick:
            raise RuntimeError(f"tick {self.tick} was already processed")
        self._processed = self.tick
        n = self.n
        todo = [None] * n
        for pid in range(n):
            if self.active[pid]:
                actions = self._actions_of(actions_by_pid, pid)
                if isinstance(actions, list) and actions:
                    todo[pid] = self._phase_a(pid, actions)
        if self.tick < len(self._perms):
            order = self._perms[self.tick].tolist()
        else:
            perm = np.random.default_rng([self.seed, SHUFFLE_STREAM, self.tick]).permutation(n)
            order = self._slotted(perm.reshape(1, n))[0].tolist()
        self.last_order = order
        for pid in order:
            orders = todo[pid]
            if orders:
                for index, action, side in orders:
                    self._new_order(pid, index, action, side)
        for rejects in self._cur.rejects:
            if len(rejects) > 1:
                rejects.sort()
                del rejects[MAX_REPORTED_REJECTS:]
        self._depth = None

    def end_tick(self, true_values):
        """Mark every participant's equity at V[t]: cash + sum(pos * V).
        true_values: {asset: cents}. Returns the equities (float cents)."""
        if self.tick < 0 or self.settled:
            raise RuntimeError("end_tick() needs begin_tick() first")
        if self._marked == self.tick:
            raise RuntimeError(f"tick {self.tick} was already marked")
        self._marked = self.tick
        marks = []
        for asset in self.assets:
            marks.append(float(true_values[asset]))
        self._marks = marks
        n_assets = len(marks)
        for pid in range(self.n):
            row = self.pos[pid]
            value = float(self.cash[pid])
            for i in range(n_assets):
                if row[i]:
                    value += row[i] * marks[i]
            self.equity[pid] = value
            self.equity_curve[pid].append(value)
        return list(self.equity)

    def stop(self, pid):
        """Cancel all of pid's orders and ignore its actions from now on.
        It keeps its position, is still marked each tick and is settled."""
        if self.active[pid]:
            self.active[pid] = False
            for book in self.books:
                book.cancel_all(pid)
            self._depth = None

    def settle(self, true_values=None):
        """After the last tick: cancel every order, return each pid's final
        equity in float cents (marked at true_values, default the last marks)."""
        for book in self.books:
            for pid in range(self.n):
                book.cancel_all(pid)
        self._depth = None
        self.settled = True
        if true_values is not None:
            marks = [float(true_values[asset]) for asset in self.assets]
        elif self._marks is not None:
            marks = self._marks
        else:
            marks = list(self._start)
        final = []
        for pid in range(self.n):
            value = float(self.cash[pid])
            for i, mark in enumerate(marks):
                value += self.pos[pid][i] * mark
            final.append(value)
        return final

    def check_invariants(self):
        """Raise RuntimeError if money or units were created or destroyed,
        a position broke its limit, or a book is crossed."""
        if sum(self.cash) != 0:
            raise RuntimeError(f"tick {self.tick}: cash sums to {sum(self.cash)}, not 0")
        for i, asset in enumerate(self.assets):
            total = 0
            for pid in range(self.n):
                position = self.pos[pid][i]
                total += position
                if abs(position) > self.limits[pid]["position_limit"]:
                    raise RuntimeError(f"tick {self.tick}: pid {pid} holds {position} {asset}, "
                                       f"limit {self.limits[pid]['position_limit']}")
            if total != 0:
                raise RuntimeError(f"tick {self.tick}: {asset} positions sum to {total}, not 0")
            bid = self.books[i].best_bid()
            ask = self.books[i].best_ask()
            if bid and ask and bid >= ask:
                raise RuntimeError(f"tick {self.tick}: {asset} book crossed {bid} >= {ask}")

    # ---------------------------------------------------------- internals

    def _slotted(self, perms):
        """Rows of shuffled pids, stably regrouped first / shuffle / last.
        With every pid in "shuffle" the rows come back unchanged."""
        if perms.shape[1] == 0:
            return perms
        keys = self._slot_ranks[perms]
        return np.take_along_axis(perms, np.argsort(keys, axis=1, kind="stable"), axis=1)

    @staticmethod
    def _actions_of(actions_by_pid, pid):
        if isinstance(actions_by_pid, dict):
            return actions_by_pid.get(pid)
        if isinstance(actions_by_pid, (list, tuple)) and pid < len(actions_by_pid):
            return actions_by_pid[pid]
        return None

    def _reject(self, pid, index, reason):
        self._cur.rejects[pid].append((index, reason))
        self.reject_count[pid] += 1
        counts = self.reject_reasons[pid]
        counts[reason] = counts.get(reason, 0) + 1

    def _phase_a(self, pid, actions):
        """Run pid's cancels now; return its orders [(index, action, side)]
        for phase B. Malformed actions and the overflow are rejected here."""
        limit = self.limits[pid]["max_actions_per_tick"]
        count = len(actions)
        upto = count if count < limit else limit
        orders = []
        for index in range(upto):
            action = actions[index]
            op = action.get("op") if isinstance(action, dict) else None
            if type(op) is not str:
                self._reject(pid, index, BAD_ACTION)
            elif op == "buy":
                orders.append((index, action, BUY))
            elif op == "sell":
                orders.append((index, action, SELL))
            elif op == "cancel":
                self._cancel(pid, index, action)
            elif op == "cancel_all":
                self._cancel_all(pid, index, action)
            else:
                self._reject(pid, index, BAD_ACTION)
        if count > limit:
            self.reject_count[pid] += count - limit
            counts = self.reject_reasons[pid]
            counts[TOO_MANY_ACTIONS] = counts.get(TOO_MANY_ACTIONS, 0) + count - limit
            last = min(count, limit + MAX_REPORTED_REJECTS)
            rejects = self._cur.rejects[pid]
            for index in range(limit, last):
                rejects.append((index, TOO_MANY_ACTIONS))
        return orders

    def _cancel(self, pid, index, action):
        order_id = _as_int(action.get("order_id"))
        found = None
        if order_id is not None and 1 <= order_id <= MAX_ORDER_ID:
            for i, book in enumerate(self.books):
                info = book.order(order_id)
                if info is not None and info[0] == pid:
                    found = i
        if found is None:
            self._reject(pid, index, UNKNOWN_ORDER)
        else:
            self.books[found].cancel(order_id)
            self._depth = None

    def _cancel_all(self, pid, index, action):
        asset = action.get("asset")
        if asset is None:
            for book in self.books:
                book.cancel_all(pid)
            self._depth = None
        elif type(asset) is str and asset in self._index:
            self.books[self._index[asset]].cancel_all(pid)
            self._depth = None
        else:
            self._reject(pid, index, UNKNOWN_ASSET)

    def _new_order(self, pid, index, action, side):
        """Risk checks in the section 6 order, then into the book."""
        ioc = action.get("ioc")
        if ioc is None:
            ioc = False
        if ioc is not True and ioc is not False:
            self._reject(pid, index, BAD_ACTION)
            return
        asset = action.get("asset")
        i = self._index.get(asset) if type(asset) is str else None
        if i is None:
            self._reject(pid, index, UNKNOWN_ASSET)
            return
        limits = self.limits[pid]
        qty = _as_int(action.get("qty"))
        if qty is None or qty < 1 or qty > limits["max_order_qty"]:
            self._reject(pid, index, BAD_QTY)
            return
        price = _as_int(action.get("price"))
        if price is None or price < 1:
            self._reject(pid, index, BAD_PRICE)
            return
        lo, hi = self._band[i]
        if price < lo or price > hi:
            self._reject(pid, index, PRICE_BAND)
            return
        book = self.books[i]
        position = self.pos[pid][i]
        cap = limits["position_limit"]
        if side == BUY:
            over = position + book.open_qty(pid, BUY) + qty > cap
        else:
            over = position - book.open_qty(pid, SELL) - qty < -cap
        if over:
            self._reject(pid, index, POSITION_LIMIT)
            return
        if not ioc and len(book.open_orders(pid)) >= limits["max_open_orders"]:
            self._reject(pid, index, TOO_MANY_ORDERS)
            return
        # pid's own id sequence (module docstring): k = orders it placed so far.
        order_id = self.orders_placed[pid] * self.n + pid + 1
        try:
            book.add(order_id, pid, side, price, qty, ioc)
        except (ValueError, TypeError, OverflowError):
            # Unreachable after the checks above; never let it escape.
            self._reject(pid, index, BAD_ACTION)
            return
        self.orders_placed[pid] += 1
        self._depth = None
        self._apply(i, book.take_fills(), book.take_cancels())

    def _apply(self, i, fills, cancels):
        """Book events -> cash, positions, and the next states' reports."""
        asset = self.assets[i]
        cur = self._cur
        t = self.tick
        for maker_id, taker_id, maker, taker, taker_side, price, qty in fills:
            maker = int(maker)
            taker = int(taker)
            price = int(price)
            qty = int(qty)
            if taker_side == BUY:
                buyer, seller = taker, maker
            else:
                buyer, seller = maker, taker
            value = price * qty
            self.pos[buyer][i] += qty
            self.cash[buyer] -= value
            self.pos[seller][i] -= qty
            self.cash[seller] += value
            aggressor = SIDES[taker_side]
            cur.trades.append({"asset": asset, "price": price, "qty": qty, "aggressor": aggressor})
            cur.fills[taker].append({"order_id": int(taker_id), "asset": asset, "side": aggressor,
                                     "price": price, "qty": qty, "aggressor": True})
            cur.fills[maker].append({"order_id": int(maker_id), "asset": asset,
                                     "side": SIDES[1 - taker_side], "price": price, "qty": qty,
                                     "aggressor": False})
            self.tick_trades.append((t, asset, price, qty, buyer, seller, aggressor))
            self.trade_count[buyer] += 1
            self.trade_count[seller] += 1
            self.volume[buyer] += qty
            self.volume[seller] += qty
        for order_id, trader, qty, reason in cancels:
            cur.cancelled[int(trader)].append({
                "order_id": int(order_id), "asset": asset, "qty": int(qty),
                "reason": ENGINE_CANCEL_REASONS.get(int(reason), "other")})
