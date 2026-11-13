"""An advanced market maker built on a Kalman filter (one per asset).

The filter keeps two numbers: an estimate of the true value and how unsure
it is (a variance). Each tick:

1. Predict: the true value may have drifted, so uncertainty grows.
2. Update: every new hint pulls the estimate toward it. A precise source
   (small published noise) pulls hard, a noisy one only a little. That's the
   Kalman gain: uncertainty / (uncertainty + hint noise^2).
3. Quote around the estimate, wider when we're unsure, leaning against our
   inventory.

Two guards for rounds with jumps and bad hints: a noisy hint that's wildly
off from a confident estimate is ignored (probably an outlier), but a
precise hint that's wildly off means the price really jumped, so we reopen
our uncertainty and follow it quickly.
"""
import math

from algomarket import buy, cancel_all, sell

DRIFT = 0.15             # dollars the true value moves per tick (a guess: tune it per round)
UNKNOWN_NOISE = 1.0      # dollars, for sources that don't publish their noise
START_UNCERTAINTY = 1.0  # dollars, how unsure the start price is
OUTLIER_SIGMAS = 4.0     # "wildly off" = this many standard deviations
BASE_HALF_SPREAD = 0.15  # dollars
UNSURE_SPREAD = 0.5      # extra half-spread per dollar of our own standard deviation
SIZE = 4
SKEW = 0.02              # dollars to move quotes per unit of inventory

# asset -> [estimate, variance]. Module globals live for the whole match.
filters = {}
noise_by_source = {}


def on_start(info):
    filters.clear()
    noise_by_source.clear()
    for source, details in info.get("hint_sources", {}).items():
        noise_by_source[source] = details.get("noise") or UNKNOWN_NOISE
    for asset, price in info.get("start_prices", {}).items():
        if price is not None:
            filters[asset] = [price, START_UNCERTAINTY ** 2]


def absorb(asset, value, noise):
    if asset not in filters:
        filters[asset] = [value, noise ** 2]       # first hint: start there
        return
    estimate, variance = filters[asset]
    hint_variance = noise ** 2
    surprise = value - estimate
    if abs(surprise) > OUTLIER_SIGMAS * math.sqrt(variance + hint_variance):
        if hint_variance > variance:
            return                                 # noisy and wildly off: ignore it
        variance += surprise ** 2                  # precise and wildly off: a jump
    gain = variance / (variance + hint_variance)
    filters[asset] = [estimate + gain * surprise, (1 - gain) * variance]


def on_tick(state):
    # 1. Predict: everything we know got a bit less certain.
    for f in filters.values():
        f[1] += DRIFT ** 2

    # 2. Update with this tick's hints.
    for hint in state.hints:
        if hint.value is not None:
            absorb(hint.asset, hint.value, noise_by_source.get(hint.source, UNKNOWN_NOISE))

    # 3. Quote.
    actions = []
    for asset in state.assets:
        if asset not in filters:
            continue
        estimate, variance = filters[asset]
        half_spread = BASE_HALF_SPREAD + UNSURE_SPREAD * math.sqrt(variance)
        position = state.position(asset)
        limit = state.limits["position_limit"]
        centre = estimate - SKEW * position

        actions.append(cancel_all(asset))
        if position + SIZE <= limit:
            actions.append(buy(asset, round(centre - half_spread, 2), SIZE))
        if position - SIZE >= -limit:
            actions.append(sell(asset, round(centre + half_spread, 2), SIZE))
    return actions
