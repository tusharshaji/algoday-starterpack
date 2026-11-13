"""The simplest legal bot: it never trades.

It ends every match with a score of exactly 0. That makes it the baseline:
a bot that scores below 0 did worse than not trading at all. (Even a bot
that makes money can score below 0: the score takes off a penalty for its
biggest fall from a high point.)
"""


def on_tick(state):
    # Return a list of actions. An empty list (or None) means "do nothing".
    return []
