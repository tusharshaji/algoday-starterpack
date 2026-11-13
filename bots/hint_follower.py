"""Buys when the market is cheap compared with the latest hint and sells
when it's expensive.

Every position is cashed out at the true value at the end, and a hint is a
noisy estimate of that value. So buying well below the hint (or selling well
above it) is a good deal on average. "Well below" matters: hints are noisy,
so we only open a position when the gap is more than twice the hint's
typical error (the noise its source publishes), or $0.30 when the source
publishes none.

Once we own some, we sell it as soon as someone bids above the hint (and buy
back a short as soon as someone offers below it). That banks the gain and
keeps the risk small: holding a position while the true value wanders is
where big drawdowns come from.
"""
from algomarket import buy, sell

MARGIN_IN_NOISE = 2.0   # open a position only when the gap is 2x the hint's noise...
DEFAULT_MARGIN = 0.30   # ...or this many dollars if the noise isn't published
SIZE = 5                # units per trade


def margin_for(state, hint):
    # state.info["hint_sources"] says how noisy each source is (in dollars).
    source = state.info.get("hint_sources", {}).get(hint.source) or {}
    noise = source.get("noise")
    if noise is None:
        return DEFAULT_MARGIN
    return MARGIN_IN_NOISE * noise


def on_tick(state):
    actions = []
    for asset in state.assets:
        hint = state.last_hint(asset)
        if hint is None:
            continue                     # no hint yet: nothing to compare with
        book = state.book(asset)
        margin = margin_for(state, hint)
        position = state.position(asset)
        limit = state.limits["position_limit"]
        size = min(SIZE, state.limits["max_order_qty"])   # bigger orders are rejected

        # Someone is selling well below the hint: buy from them. If we're
        # short, any price below the hint is good enough to buy back.
        buy_below = hint.value - margin if position >= 0 else hint.value
        if book.best_ask is not None and book.best_ask < buy_below:
            qty = min(size, limit - position)
            if position < 0:
                qty = min(qty, -position)    # buying back: stop at flat
            if qty > 0:
                # ioc=True: fill what we can right now, don't leave an order behind.
                actions.append(buy(asset, book.best_ask, qty, ioc=True))

        # Someone is buying well above the hint: sell to them. If we're
        # long, any price above the hint is good enough to sell out.
        sell_above = hint.value + margin if position <= 0 else hint.value
        if book.best_bid is not None and book.best_bid > sell_above:
            qty = min(size, limit + position)
            if position > 0:
                qty = min(qty, position)     # selling out: stop at flat
            if qty > 0:
                actions.append(sell(asset, book.best_bid, qty, ioc=True))
    return actions
