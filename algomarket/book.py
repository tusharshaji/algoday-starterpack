"""Reference order book. The C++ engine must behave exactly like this.

Prices and quantities are positive ints (prices in cents). Side 0 = buy,
1 = sell. Fills happen at the resting order's price. Priority: best price,
then earliest arrival. The full rules are DESIGN.md section 5, in the
organisers' design notes, which are not in the starter kit.
"""
import bisect

BUY = 0
SELL = 1

# take_cancels() reasons
SELF_TRADE = 1
IOC_REMAINDER = 2

MAX_ORDER_ID = 2**62
MAX_TRADER = 2**31 - 1
MAX_VALUE = 10**12


def _int_in(value, low, high, name):
    if type(value) is not int or value < low or value > high:
        raise ValueError(f"{name} must be an int in {low}..{high}, got {value!r}")


class OrderBook:
    def __init__(self):
        # order_id -> [trader, side, price, remaining]
        self._orders = {}
        # per side: price -> {order_id: None}, a dict used as a FIFO set
        self._levels = ({}, {})
        # per side: resting prices, ascending
        self._prices = ([], [])
        # trader -> set of resting order ids
        self._by_trader = {}
        self._fills = []
        self._cancels = []

    # ------------------------------------------------------------ commands

    def add(self, order_id, trader, side, price, qty, ioc=False):
        """Match what crosses, rest the remainder (unless IOC).

        Returns the quantity left resting in the book.
        """
        _int_in(order_id, 1, MAX_ORDER_ID, "order_id")
        _int_in(trader, 0, MAX_TRADER, "trader")
        _int_in(side, 0, 1, "side")
        _int_in(price, 1, MAX_VALUE, "price")
        _int_in(qty, 1, MAX_VALUE, "qty")
        if order_id in self._orders:
            raise ValueError(f"order_id {order_id} is already resting")
        # Before matching, so an ioc whose bool() raises can't half-apply an add.
        ioc = bool(ioc)

        remaining = qty
        maker_side = 1 - side
        while remaining > 0 and self._crosses(side, price):
            level_price = self._best(maker_side)
            level = self._levels[maker_side][level_price]
            maker_id = next(iter(level))
            maker = self._orders[maker_id]
            if maker[0] == trader:
                # Self-trade prevention: drop the resting order, keep going.
                self._cancels.append((maker_id, trader, maker[3], SELF_TRADE))
                self._remove(maker_id)
            else:
                traded = min(remaining, maker[3])
                maker[3] -= traded
                remaining -= traded
                self._fills.append(
                    (maker_id, order_id, maker[0], trader, side, level_price, traded))
                if maker[3] == 0:
                    self._remove(maker_id)

        if remaining == 0:
            return 0
        if ioc:
            self._cancels.append((order_id, trader, remaining, IOC_REMAINDER))
            return 0

        self._orders[order_id] = [trader, side, price, remaining]
        levels = self._levels[side]
        if price not in levels:
            levels[price] = {}
            bisect.insort(self._prices[side], price)
        levels[price][order_id] = None
        self._by_trader.setdefault(trader, set()).add(order_id)
        return remaining

    def cancel(self, order_id):
        """Cancel a resting order. Returns the qty cancelled (0 if not resting)."""
        order = self._orders.get(order_id)
        if order is None:
            return 0
        qty = order[3]
        self._remove(order_id)
        return qty

    def cancel_all(self, trader):
        """Cancel every resting order of a trader. Returns how many."""
        ids = list(self._by_trader.get(trader, ()))
        for order_id in ids:
            self._remove(order_id)
        return len(ids)

    # ------------------------------------------------------------- queries

    def best_bid(self):
        prices = self._prices[BUY]
        if prices:
            return prices[-1]
        return 0

    def best_ask(self):
        prices = self._prices[SELL]
        if prices:
            return prices[0]
        return 0

    def depth(self, side, levels):
        """Top `levels` price levels of one side, best first: [(price, qty)]."""
        _int_in(side, 0, 1, "side")
        if type(levels) is not int or levels < 0:
            raise ValueError(f"levels must be an int >= 0, got {levels!r}")
        prices = self._prices[side]
        if side == BUY:
            chosen = prices[::-1][:levels]
        else:
            chosen = prices[:levels]
        out = []
        for price in chosen:
            total = 0
            for order_id in self._levels[side][price]:
                total += self._orders[order_id][3]
            out.append((price, total))
        return out

    def open_orders(self, trader):
        """[(order_id, side, price, qty)] for a trader, sorted by order_id."""
        out = []
        for order_id in sorted(self._by_trader.get(trader, ())):
            order = self._orders[order_id]
            out.append((order_id, order[1], order[2], order[3]))
        return out

    def open_qty(self, trader, side):
        total = 0
        for order_id in self._by_trader.get(trader, ()):
            order = self._orders[order_id]
            if order[1] == side:
                total += order[3]
        return total

    def order(self, order_id):
        order = self._orders.get(order_id)
        if order is None:
            return None
        return (order[0], order[1], order[2], order[3])

    def order_count(self):
        return len(self._orders)

    def take_fills(self):
        """[(maker_id, taker_id, maker_trader, taker_trader, taker_side, price, qty)]"""
        fills = self._fills
        self._fills = []
        return fills

    def take_cancels(self):
        """[(order_id, trader, qty, reason)] for engine-initiated cancels."""
        cancels = self._cancels
        self._cancels = []
        return cancels

    # ------------------------------------------------------------ internals

    def _best(self, side):
        if side == BUY:
            return self._prices[BUY][-1]
        return self._prices[SELL][0]

    def _crosses(self, side, price):
        if side == BUY:
            asks = self._prices[SELL]
            return bool(asks) and asks[0] <= price
        bids = self._prices[BUY]
        return bool(bids) and bids[-1] >= price

    def _remove(self, order_id):
        trader, side, price, _ = self._orders.pop(order_id)
        level = self._levels[side][price]
        del level[order_id]
        if not level:
            del self._levels[side][price]
            prices = self._prices[side]
            del prices[bisect.bisect_left(prices, price)]
        ids = self._by_trader[trader]
        ids.discard(order_id)
        if not ids:
            del self._by_trader[trader]
