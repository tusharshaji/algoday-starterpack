"""Your team's bot. This is the file you edit and upload.

Every tick (about 1,000 per match) the match calls on_tick(state) and you
answer with a list of orders. This example is a small market maker: it keeps
an offer to buy just below its guess of the true value and an offer to sell
just above it, and earns the gap when other traders take them. It works in
every round, but it is only a start: change it! (If several teams upload it
unchanged, they can all score below 0 in Jumps: docs/GUIDE.md, section 11,
says why.)

    Try it:      python run_local.py --bots strategy.py
    Watch it:    click the replay (.algoday) file it prints, in VS Code
                 (README.md, step 5; no VS Code: the site's Replays tab)
    Learn more:  docs/GUIDE.md (the full guide to writing a bot)
                 docs/RULES.md (limits, scoring, what's allowed)
                 bots/ (sample bots to borrow ideas from)

What you can read (prices and cash in dollars):
    state.tick, state.ticks_left          where we are in the match
    state.assets                          what this round trades, e.g. ["DEVS"]
    state.last_hint(asset).value          the latest estimate of the true value
    state.hint_history(asset)             every hint so far, oldest first
    state.book(asset).best_bid            highest price someone will pay now
    state.book(asset).best_ask            lowest price someone will sell at now
    state.position(asset), state.cash     what you hold (negative = short)
    state.limits["position_limit"]        most units you may hold, long or short
    state.fills, state.rejects            your trades and refused orders, last tick
last_hint, best_bid and best_ask are None when there is nothing yet: check
before you use them.

What you can do (return a list of these):
    buy(asset, price, qty)       offer to buy; stays in the book until filled or cancelled
    sell(asset, price, qty)      offer to sell
    buy_now(asset, qty)          buy right away, paying at most $1 above best_ask
    sell_now(asset, qty)         sell right away, at most $1 below best_bid
    cancel(order_id), cancel_all(asset)

Variables at the top of this file keep their values from tick to tick. To
change one inside on_tick (count += 1), first write `global count` at the
top of on_tick; without it Python raises UnboundLocalError.

At the end, everything you hold is cashed in at the true value.
Score = profit - lambda x max drawdown (your biggest fall from a high point),
so steady profit beats wild swings.
"""
from algomarket import buy, cancel_all, sell

HISTORY = 4         # average this many recent hints (one hint on its own is noisy)
HALF_SPREAD = 0.30  # dollars between our guess and each of our quotes
SKEW = 0.15         # dollars to move our quotes per unit we hold (keeps what we hold small)
SIZE = 2            # units per quote


def on_start(info):
    # Optional: runs once before the first tick. print() goes to your bot's
    # log file (run_local.py shows where it is), not to the screen.
    print("Round:", info.get("title"))
    print(info.get("description"))


def on_tick(state):
    actions = []
    for asset in state.assets:
        # 1. Guess the true value: the average of the last few hints.
        hints = state.hint_history(asset)[-HISTORY:]
        if not hints:
            continue                        # no hints yet: nothing to go on
        fair = sum(h.value for h in hints) / len(hints)

        # 2. Lean against what we hold: when we own a lot, quote lower so we
        #    sell more and buy less (and the other way round when short).
        position = state.position(asset)
        centre = fair - SKEW * position

        # 3. Swap last tick's quotes for new ones. Cancels happen before new
        #    orders, so we never trade with our own old quotes.
        actions.append(cancel_all(asset))
        limit = state.limits["position_limit"]
        if position + SIZE <= limit:        # orders past the limit get rejected
            actions.append(buy(asset, round(centre - HALF_SPREAD, 2), SIZE))
        if position - SIZE >= -limit:
            actions.append(sell(asset, round(centre + HALF_SPREAD, 2), SIZE))
    return actions
