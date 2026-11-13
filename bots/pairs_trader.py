"""For the pairs round (WDCC and UOA). On any other round it does nothing.

UOA's true value is tied to WDCC's: UOA = beta x WDCC + gap, and the gap
keeps getting pulled back toward $0. WDCC's hints are more precise and more
frequent than UOA's, so the best price for UOA comes from WDCC:

    fair UOA = beta x (our WDCC estimate) + (our gap estimate)

1. Keep a running estimate of WDCC from its hints.
2. Each UOA hint shows us the gap (UOA hint - beta x WDCC estimate).
   Keep a running estimate of it, and let it fade toward $0 between hints,
   because the true gap keeps getting pulled back there.
3. Quote both assets around those fair values, like simple_market_maker.

We don't know beta exactly. The ratio of the start prices is a decent guess
(the round description may say; a regression of UOA's hints on WDCC's
would also work).
"""
from algomarket import buy, cancel_all, sell

SMOOTHING = 0.3     # weight of each new hint in our running estimates
FADE = 0.986        # the gap keeps this share of itself each tick (halves in ~50 ticks)
HALF_SPREAD = 0.25  # dollars between our fair value and each quote
SIZE = 3            # units per quote
SKEW = 0.02         # dollars to move the quotes per unit of inventory

wdcc = None         # running estimate of WDCC's true value
gap = 0.0           # running estimate of the gap
beta = 0.5


def on_start(info):
    global wdcc, gap, beta
    wdcc = None
    gap = 0.0
    prices = info.get("start_prices", {})
    if prices.get("WDCC") and prices.get("UOA"):
        beta = prices["UOA"] / prices["WDCC"]


def on_tick(state):
    global wdcc, gap
    if "WDCC" not in state.assets or "UOA" not in state.assets:
        return []

    # 1 and 2: update the estimates (WDCC first, the gap needs it).
    gap = gap * FADE
    for hint in state.hints:
        if hint.asset == "WDCC" and hint.value is not None:
            wdcc = hint.value if wdcc is None else wdcc + SMOOTHING * (hint.value - wdcc)
    for hint in state.hints:
        if hint.asset == "UOA" and hint.value is not None and wdcc is not None:
            gap = gap + SMOOTHING * ((hint.value - beta * wdcc) - gap)
    if wdcc is None:
        return []

    # 3. Replace last tick's quotes on both assets.
    actions = []
    limit = state.limits["position_limit"]
    for asset, fair in (("WDCC", wdcc), ("UOA", beta * wdcc + gap)):
        position = state.position(asset)
        centre = fair - SKEW * position
        actions.append(cancel_all(asset))
        if position + SIZE <= limit:
            actions.append(buy(asset, round(centre - HALF_SPREAD, 2), SIZE))
        if position - SIZE >= -limit:
            actions.append(sell(asset, round(centre + HALF_SPREAD, 2), SIZE))
    return actions
