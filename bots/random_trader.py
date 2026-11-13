"""Trades at random. Handy as an example of the API, terrible as a strategy:
every trade pays the spread and nothing tells it which way to go, so on
average it loses to do_nothing.
"""
import random

from algomarket import buy_now, sell_now

# A fixed seed means the bot does the same thing every run (easier to debug).
rng = random.Random(42)

CHANCE = 0.1      # trade on about 1 tick in 10 (shared out between the assets)
MAX_QTY = 3


def on_tick(state):
    actions = []
    for asset in state.assets:
        if rng.random() < CHANCE / len(state.assets):
            qty = rng.randint(1, MAX_QTY)
            side = rng.choice(["buy", "sell"])
            position = state.position(asset)
            limit = state.limits["position_limit"]
            # buy_now / sell_now trade straight away with the orders on offer,
            # paying at most $1 more (selling: $1 less) than the best price
            # in state.book(asset). Whatever can't fill that close is dropped.
            # Stay inside the position limit, or the exchange rejects the order.
            if side == "buy" and position + qty <= limit:
                actions.append(buy_now(asset, qty))
            if side == "sell" and position - qty >= -limit:
                actions.append(sell_now(asset, qty))
    return actions
