"""A simple market maker: keeps a bid just below and an ask just above its
estimate of the true value, and earns the gap when other traders hit them.

Its estimate is the average of the last few hints. It leans its quotes
against its inventory (when it owns a lot it quotes lower, so it sells more
and buys less), which stops the position running away.
"""
from algomarket import buy, cancel_all, sell

HISTORY = 4         # average this many recent hints
HALF_SPREAD = 0.25  # dollars between our estimate and each quote
SIZE = 3            # units per quote
SKEW = 0.02         # dollars to move the quotes per unit of inventory


def on_tick(state):
    actions = []
    for asset in state.assets:
        hints = state.hint_history(asset)[-HISTORY:]
        if not hints:
            continue
        fair = sum(h.value for h in hints) / len(hints)

        position = state.position(asset)
        limit = state.limits["position_limit"]
        centre = fair - SKEW * position
        bid = round(centre - HALF_SPREAD, 2)
        ask = round(centre + HALF_SPREAD, 2)

        # Replace last tick's quotes. Cancels are processed before new
        # orders, so this never trades with our own old quotes.
        actions.append(cancel_all(asset))
        if position + SIZE <= limit:
            actions.append(buy(asset, bid, SIZE))
        if position - SIZE >= -limit:
            actions.append(sell(asset, ask, SIZE))
    return actions
