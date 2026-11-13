"""Team-facing SDK. Everything here is in dollars. For teams: the cheat sheet
is docs/GUIDE.md section 13 and the rules are docs/RULES.md section 4. (The
organisers' design notes, DESIGN.md sections 9, 10 and 16, are the contract
behind this file; they are not in the starter kit.)

Your bot file defines on_tick(state) (required) and on_start(info)
(optional). on_tick returns a list of actions, or None for no actions:

    from algomarket import buy, sell, cancel_all

    def on_tick(state):
        actions = []
        for asset in state.assets:
            hint = state.last_hint(asset)
            if hint is None:
                continue
            actions += [cancel_all(asset),
                        buy(asset, hint.value - 0.10, 5),
                        sell(asset, hint.value + 0.10, 5)]
        return actions

Plain dicts in dollars work too: {"op": "buy", "asset": "DEVS", "price": 99.5,
"qty": 5}. The exchange works in integer cents; the SDK converts prices with
round(price * 100). Conversion never raises: anything it can't convert is
still sent, in a form the exchange rejects, so the reason shows up in
state.rejects on the next tick (rejects[i].index is the position in the list
you returned).

`info` (on_start and state.info) is the match info (round, description,
hint_sources, limits, start_prices, participants, ...), with start_prices
in dollars.
"""
import itertools
import math
from collections import namedtuple

Hint = namedtuple("Hint", "asset value source tick")
Trade = namedtuple("Trade", "asset price qty aggressor")
Fill = namedtuple("Fill", "order_id asset side price qty aggressor")
Cancelled = namedtuple("Cancelled", "order_id asset qty reason")
Reject = namedtuple("Reject", "index reason")
Order = namedtuple("Order", "order_id asset side price qty")

# At most this many actions go on the wire per tick. With the exchange's own
# max_actions_per_tick the SDK sends limit + 1 (so the exchange reports
# too_many_actions once) and drops the rest. Keeps every line far below 64 KB.
MAX_WIRE_ACTIONS = 256
MAX_ASSET_NAME = 64
BAD_ASSET = "<invalid>"
# An ioc flag that isn't a bool or a whole number is sent as this, which the
# exchange rejects (bad_action) instead of the order quietly resting.
BAD_FLAG = "<invalid>"
# buy_now / sell_now pay at most this many dollars past the best price on the
# other side of the book that the bot saw this tick (past the middle of the
# price band, about the latest hint, when that side was empty). Cancels go
# first, so without a cap a market order that arrives just after the market
# makers pulled their quotes could fill at any far-away quote left resting.
NOW_MAX_SLIPPAGE = 1.00
# Ints beyond this are garbage either way; keep them off the wire.
MAX_WIRE_INT = 2**63
# Prices beyond this many cents can't be valid (the book caps at 10**12).
MAX_PRICE_CENTS = 10**15

ORDER_OPS = ("buy", "sell")


# ---------------------------------------------------------------- actions


class Action:
    """One instruction for the exchange. Make these with buy(), sell(),
    buy_now(), sell_now(), cancel() and cancel_all()."""

    __slots__ = ("op", "asset", "price", "qty", "ioc", "order_id", "now", "slippage")

    def __init__(self, op, asset=None, price=None, qty=None, ioc=False,
                 order_id=None, now=False, slippage=NOW_MAX_SLIPPAGE):
        self.op = op
        self.asset = asset
        self.price = price
        self.qty = qty
        self.ioc = ioc
        self.order_id = order_id
        self.now = now
        # buy_now / sell_now only: dollars past the best price seen, None = no cap.
        self.slippage = slippage

    def _key(self):
        return (self.op, self.asset, self.price, self.qty, self.ioc,
                self.order_id, self.now, self.slippage)

    def __eq__(self, other):
        if not isinstance(other, Action):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __repr__(self):
        if self.op in ORDER_OPS:
            if self.now:
                if type(self.slippage) is float and self.slippage == NOW_MAX_SLIPPAGE:
                    return f"{self.op}_now({self.asset!r}, {self.qty!r})"
                return f"{self.op}_now({self.asset!r}, {self.qty!r}, max_slippage={self.slippage!r})"
            if self.ioc:
                return f"{self.op}({self.asset!r}, {self.price!r}, {self.qty!r}, ioc=True)"
            return f"{self.op}({self.asset!r}, {self.price!r}, {self.qty!r})"
        if self.op == "cancel":
            return f"cancel({self.order_id!r})"
        return f"cancel_all({self.asset!r})"


def buy(asset, price, qty, ioc=False):
    """Bid for qty units at price (dollars). Rests in the book until filled
    or cancelled, unless ioc=True (fill what you can now, drop the rest)."""
    return Action("buy", asset, price, qty, ioc)


def sell(asset, price, qty, ioc=False):
    """Offer qty units at price (dollars). See buy()."""
    return Action("sell", asset, price, qty, ioc)


def buy_now(asset, qty, max_slippage=NOW_MAX_SLIPPAGE):
    """Buy up to qty right away from the asks on offer: an immediate-or-cancel
    order that pays at most max_slippage dollars (default $1.00) more than
    the best ask you saw this tick (state.book(asset).best_ask), or more than
    the latest hint if nobody was offering. Whatever can't fill at that price
    is dropped. max_slippage=None removes the cap (any price up to the top of
    the price band: risky)."""
    return Action("buy", asset, None, qty, True, None, True, max_slippage)


def sell_now(asset, qty, max_slippage=NOW_MAX_SLIPPAGE):
    """Sell up to qty right away to the bids on offer, for at least the best
    bid you saw minus max_slippage dollars (default $1.00), or the latest hint
    minus that if nobody was bidding. See buy_now()."""
    return Action("sell", asset, None, qty, True, None, True, max_slippage)


def cancel(order_id):
    """Cancel one of your resting orders (an order id, or an Order from
    state.open_orders)."""
    return Action("cancel", order_id=order_id)


def cancel_all(asset=None):
    """Cancel all your resting orders on one asset, or on every asset."""
    return Action("cancel_all", asset)


# ------------------------------------------------------------- conversion


def _is_bool(value):
    # Python bool and numpy bool. Booleans are never numbers here.
    return type(value).__name__ in ("bool", "bool_")


def _cents(price):
    """Dollars -> int cents, or None if it isn't a sensible finite number."""
    if price is None or _is_bool(price) or isinstance(price, (str, bytes, bytearray)):
        return None
    if type(price) is int:
        cents = price * 100
    else:
        try:
            value = float(price)
        except Exception:
            return None
        if not math.isfinite(value):
            return None
        cents = round(value * 100)
    if abs(cents) > MAX_PRICE_CENTS:
        return None
    return cents


def _int(value):
    """An int (5, 5.0, numpy ints), or None if it isn't a whole number."""
    if value is None or _is_bool(value) or isinstance(value, (str, bytes, bytearray)):
        return None
    if type(value) is int:
        number = value
    else:
        try:
            number = value.__index__()
        except Exception:
            try:
                as_float = float(value)
            except Exception:
                return None
            if not math.isfinite(as_float) or not as_float.is_integer():
                return None
            number = int(as_float)
    if type(number) is not int or abs(number) > MAX_WIRE_INT:
        return None
    return number


def _asset(asset):
    if isinstance(asset, str) and len(asset) <= MAX_ASSET_NAME:
        return asset
    return None


def _cancel_all_asset(asset):
    # None means every asset, so garbage must not turn into None here.
    if asset is None:
        return None
    if isinstance(asset, str) and len(asset) <= MAX_ASSET_NAME:
        return asset
    return BAD_ASSET


def _flag(value):
    """ioc: None -> False; a bool (numpy too) or a whole number -> a bool;
    anything else -> BAD_FLAG, so the exchange rejects the order (bad_action)
    rather than letting a mistyped ioc rest in the book."""
    if value is None:
        return False
    if _is_bool(value):
        return bool(value)
    number = _int(value)
    if number is None:
        return BAD_FLAG
    return number != 0


def _best_seen(books, asset, op):
    """Best price (cents) on the side a buy_now / sell_now trades against, in
    the book the bot saw this tick, or None if that side was empty."""
    sides = books.get(asset) if isinstance(asset, str) else None
    if not isinstance(sides, dict):
        return None
    levels = sides.get("asks" if op == "buy" else "bids")
    if not isinstance(levels, (list, tuple)) or not levels:
        return None
    best = levels[0]
    if isinstance(best, (list, tuple)) and best and type(best[0]) is int:
        return best[0]
    return None


def _now_price(band, books, asset, op, slippage):
    """The IOC limit (cents) for buy_now / sell_now: at most `slippage` dollars
    past the best opposite price seen (past the band's middle, about the latest
    hint, when that side was empty), kept inside the band. slippage None: the
    band edge. None (the exchange rejects it) if there is no band or the
    slippage isn't a number >= 0."""
    edges = band.get(asset) if isinstance(asset, str) else None
    if not isinstance(edges, (list, tuple)) or len(edges) != 2:
        return None
    lo, hi = edges
    if type(lo) is not int or type(hi) is not int:
        return None
    if slippage is None:
        if op == "buy":
            return hi
        return lo
    cents = _cents(slippage)
    if cents is None or cents < 0:
        return None
    best = _best_seen(books, asset, op)
    if op == "buy":
        if best is None:
            best = (lo + hi) // 2
        return max(lo, min(hi, best + cents))
    if best is None:
        best = (lo + hi + 1) // 2
    return min(hi, max(lo, best - cents))


def _order_id(order_id):
    if isinstance(order_id, (Order, Fill, Cancelled)):
        order_id = order_id.order_id
    return _int(order_id)


def _order(op, asset, price_cents, qty, ioc):
    return {"op": op, "asset": _asset(asset), "price": price_cents,
            "qty": _int(qty), "ioc": _flag(ioc)}


def _action_to_wire(action, band, books):
    op = action.op
    if op in ORDER_OPS:
        if action.now:
            price = _now_price(band, books, action.asset, op, action.slippage)
            return _order(op, action.asset, price, action.qty, True)
        return _order(op, action.asset, _cents(action.price), action.qty, action.ioc)
    if op == "cancel":
        return {"op": "cancel", "order_id": _order_id(action.order_id)}
    if op == "cancel_all":
        return {"op": "cancel_all", "asset": _cancel_all_asset(action.asset)}
    return {"op": None}


def _dict_to_wire(item):
    op = item.get("op")
    if isinstance(op, str):
        op = op.strip().lower()
    if op in ORDER_OPS:
        return _order(op, item.get("asset"), _cents(item.get("price")),
                      item.get("qty"), item.get("ioc", False))
    if op == "cancel":
        return {"op": "cancel", "order_id": _order_id(item.get("order_id"))}
    if op == "cancel_all":
        return {"op": "cancel_all", "asset": _cancel_all_asset(item.get("asset"))}
    return {"op": None}


def to_wire(item, band=None, books=None):
    """One returned action (helper object or dollars dict) -> wire dict in
    cents. band and books are this tick's (wire STATE, cents); buy_now and
    sell_now need them for their price. Never raises: garbage becomes
    {"op": None} (bad_action) or an order with None or BAD_FLAG fields
    (bad_qty / bad_price / unknown_asset / bad_action)."""
    try:
        if isinstance(item, Action):
            return _action_to_wire(item, band or {}, books or {})
        if isinstance(item, dict):
            return _dict_to_wire(item)
    except Exception:
        pass
    return {"op": None}


# Returned values that are never read as a list of actions: text, and sets
# (no order: the same bot could send its orders in a different order each run).
_NOT_A_LIST = (str, bytes, bytearray, set, frozenset)


def normalise(returned):
    """What on_tick returned -> a list of items. None -> [], one action ->
    [it], a list or tuple -> its items, any other iterable (a generator, a
    numpy array, ...) -> its first MAX_WIRE_ACTIONS + 1 items. Anything else
    (a string, a set, a number, an iterable that raises) -> [{"op": None}],
    so the bot sees one bad_action reject instead of silently not trading."""
    try:
        if returned is None:
            return []
        if isinstance(returned, (Action, dict)):
            return [returned]
        if type(returned) is list:
            return returned
        if type(returned) is tuple:
            return list(returned)
        if not isinstance(returned, _NOT_A_LIST):
            return list(itertools.islice(iter(returned), MAX_WIRE_ACTIONS + 1))
    except Exception:
        pass
    return [{"op": None}]


# ------------------------------------------------------------------ state


def _dollars(cents):
    if cents is None or _is_bool(cents):
        return None
    try:
        return cents / 100
    except Exception:
        return None


def team_info(info):
    """Match info as team code sees it: start_prices converted to dollars."""
    if not isinstance(info, dict):
        info = {}
    out = dict(info)
    prices = {}
    for asset, cents in (info.get("start_prices") or {}).items():
        prices[asset] = _dollars(cents)
    out["start_prices"] = prices
    return out


class Book:
    """Top of the order book for one asset. bids/asks are lists of
    (price, qty), best first, prices in dollars."""

    __slots__ = ("asset", "bids", "asks", "_bid_cents", "_ask_cents")

    def __init__(self, asset, bids=(), asks=()):
        self.asset = asset
        self.bids = []
        self.asks = []
        for level in bids:
            self.bids.append((level[0] / 100, level[1]))
        for level in asks:
            self.asks.append((level[0] / 100, level[1]))
        self._bid_cents = bids[0][0] if bids else None
        self._ask_cents = asks[0][0] if asks else None

    @property
    def best_bid(self):
        """Highest bid price, or None if nobody is bidding."""
        if self._bid_cents is None:
            return None
        return self._bid_cents / 100

    @property
    def best_ask(self):
        """Lowest ask price, or None if nobody is offering."""
        if self._ask_cents is None:
            return None
        return self._ask_cents / 100

    @property
    def mid(self):
        """Halfway between best bid and best ask (None if a side is empty)."""
        if self._bid_cents is None or self._ask_cents is None:
            return None
        return (self._bid_cents + self._ask_cents) / 200

    @property
    def spread(self):
        """best_ask - best_bid (None if a side is empty)."""
        if self._bid_cents is None or self._ask_cents is None:
            return None
        return (self._ask_cents - self._bid_cents) / 100

    def __repr__(self):
        return f"Book({self.asset!r}, best_bid={self.best_bid!r}, best_ask={self.best_ask!r})"


def _levels(side):
    out = []
    for level in side or ():
        out.append((level[0], level[1]))
    return out


class State:
    """What on_tick sees each tick. Prices and cash are in dollars.

    tick, ticks, ticks_left (ticks after this one; 0 on the last tick),
    assets, info, limits, cash, positions (dict), hints (released this
    tick), trades (everyone's, last tick), fills / cancelled / rejects
    (yours, last tick), open_orders (yours, resting now).
    """

    def __init__(self, session, wire, hints):
        info = session.info
        self.info = info
        self.tick = wire.get("tick", 0)
        self.ticks = info.get("ticks", 0)
        if type(self.tick) is int and type(self.ticks) is int:
            self.ticks_left = max(0, self.ticks - self.tick - 1)
        else:
            self.ticks_left = 0
        self.assets = list(info.get("assets") or [])
        self.limits = dict(info.get("limits") or {})
        self.cash = _dollars(wire.get("cash", 0)) or 0.0
        self.positions = {}
        for asset in self.assets:
            self.positions[asset] = 0
        for asset, qty in (wire.get("positions") or {}).items():
            self.positions[asset] = qty
        self.hints = hints
        self.trades = []
        for t in wire.get("trades") or ():
            self.trades.append(Trade(t.get("asset"), _dollars(t.get("price")),
                                     t.get("qty"), t.get("aggressor")))
        self.fills = []
        for f in wire.get("fills") or ():
            self.fills.append(Fill(f.get("order_id"), f.get("asset"), f.get("side"),
                                   _dollars(f.get("price")), f.get("qty"),
                                   f.get("aggressor")))
        self.cancelled = []
        for c in wire.get("cancelled") or ():
            self.cancelled.append(Cancelled(c.get("order_id"), c.get("asset"),
                                            c.get("qty"), c.get("reason")))
        self.rejects = []
        for r in wire.get("rejects") or ():
            self.rejects.append(Reject(r.get("index"), r.get("reason")))
        self.open_orders = []
        for o in wire.get("open_orders") or ():
            self.open_orders.append(Order(o.get("order_id"), o.get("asset"), o.get("side"),
                                          _dollars(o.get("price")), o.get("qty")))
        self._books_wire = wire.get("books") or {}
        self._books = {}
        self._band = wire.get("band") or {}
        self._history = session.history

    def position(self, asset):
        """Units you hold (negative = short). 0 for unknown assets."""
        return self.positions.get(asset, 0)

    def book(self, asset):
        """Top 5 levels of the order book for asset (empty for unknown assets)."""
        book = self._books.get(asset)
        if book is None:
            sides = self._books_wire.get(asset) or {}
            book = Book(asset, _levels(sides.get("bids")), _levels(sides.get("asks")))
            self._books[asset] = book
        return book

    def band(self, asset):
        """(lowest, highest) price you may order at this tick, or None."""
        edges = self._band.get(asset)
        if not edges:
            return None
        return (edges[0] / 100, edges[1] / 100)

    def hint_history(self, asset, source=None):
        """Every hint for asset so far (oldest first), optionally one source only."""
        hints = self._history.get(asset, ())
        if source is None:
            return list(hints)
        out = []
        for hint in hints:
            if hint.source == source:
                out.append(hint)
        return out

    def last_hint(self, asset, source=None):
        """The most recent hint for asset (optionally from one source), or None."""
        hints = self._history.get(asset, ())
        i = len(hints) - 1
        while i >= 0 and source is not None and hints[i].source != source:
            i -= 1
        if i < 0:
            return None
        return hints[i]

    def __repr__(self):
        return (f"State(tick={self.tick!r}, cash={self.cash!r}, positions={self.positions!r}, "
                f"hints={len(self.hints)}, trades={len(self.trades)}, fills={len(self.fills)}, "
                f"open_orders={len(self.open_orders)})")


class Session:
    """One bot's SDK state for a whole match: hint history, and the latest
    price band and books (needed to turn buy_now/sell_now into prices)."""

    def __init__(self, info):
        self.info = team_info(info)
        self.history = {}
        self.last_tick = None
        self.band = {}
        self.books = {}
        limit = (self.info.get("limits") or {}).get("max_actions_per_tick")
        if type(limit) is int and limit >= 0:
            self.max_actions = min(limit + 1, MAX_WIRE_ACTIONS)
        else:
            self.max_actions = MAX_WIRE_ACTIONS

    def update(self, wire):
        """Wire STATE (cents) -> State (dollars). Records this tick's hints."""
        if not isinstance(wire, dict):
            wire = {}
        tick = wire.get("tick")
        hints = []
        for h in wire.get("hints") or ():
            hints.append(Hint(h.get("asset"), _dollars(h.get("value")), h.get("source"), tick))
        # The same tick twice (a retry) must not duplicate the history.
        fresh = self.last_tick is None or (type(tick) is int and tick > self.last_tick)
        if fresh:
            for hint in hints:
                self.history.setdefault(hint.asset, []).append(hint)
            if type(tick) is int:
                self.last_tick = tick
        band = wire.get("band")
        self.band = band if isinstance(band, dict) else {}
        books = wire.get("books")
        self.books = books if isinstance(books, dict) else {}
        return State(self, wire, hints)

    def actions(self, returned):
        """What on_tick returned -> wire actions (cents), same order and
        indices, at most max_actions of them. Never raises."""
        items = normalise(returned)
        wire = []
        try:
            for item in items[:self.max_actions]:
                wire.append(to_wire(item, self.band, self.books))
        except Exception:
            pass
        return wire
