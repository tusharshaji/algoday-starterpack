# AlgoDay Market: the rules

This is the rulebook for the AlgoDay trading floor. New to all this? Start
with the hands-on [GUIDE.md](GUIDE.md), then come back here when you need a
detail.

## 1. The game in one minute

- Your team writes a **bot**: a Python file with a function `on_tick(state)`.
- Every team's bot trades in **one shared market**, together with a few
  **house bots** run by the organisers.
- Each asset has a hidden **true value**. No bot can see it during the match.
- Every bot gets the same **hints**: estimates of the true value with a
  random error.
- Bots trade by sending buy and sell **orders** to an **order book**.
- A match lasts **1,000 ticks**. In each tick, every bot looks at the market
  and then acts.
- After the last tick, everything you hold is **cashed out at the true
  value**.
- Your **score** is your profit minus half of your biggest drop along the way.

In short: buy below the true value, sell above it, and don't take big risks.

## 2. Words used here

| Word | Meaning |
|---|---|
| asset | A made-up thing you can trade, like DEVS. The tickers are only names: nothing real is bought or sold. Prices are in dollars, to the cent. |
| true value | What one unit is really worth. Hidden during the match; you can see it in the replay afterwards. |
| hint | A published estimate of the true value: the true value plus a random error. |
| error sd | How big a hint's error usually is ("sd" is short for standard deviation). With an error sd of $0.40, about 2 hints in 3 are within $0.40 of the true value, and about 19 in 20 are within $0.80. |
| order | An offer to buy (a **bid**) or to sell (an **ask**) some units at a price. |
| best bid, best ask | The highest bid and the lowest ask in the book right now. |
| spread | best ask minus best bid. |
| position | How many units you hold. Negative means **short**: you sold units you didn't have. A short position is cashed out too: you pay the true value for each unit. |
| tick | One step of the match. Ticks are numbered 0 to 999. |
| seed | A number that fixes everything random in a match. The same round with the same seed always has the same true values and the same hints. |

## 3. The rounds

There are four rounds. **Your one bot plays all of them**, so it should check
which round it is in: `state.info["round"]` (or look at `state.assets`).

The same in every round:

- 1,000 ticks per match.
- The start price is $100 per asset (UOA: $50). The true value starts
  *near* the start price, not exactly on it, so use the hints.
- You start with $0 cash and no position. Your cash may go below $0. There
  are no fees and no interest.
- At tick 0, every asset gets one hint, so you always have a first estimate.
- Hint errors are random and centred on zero: a hint is as likely to be too
  high as too low. They follow a normal (bell-curve) distribution and are
  independent from one hint to the next. The one exception is the rumours in
  Jumps (below).

| Round (key) | Asset | Position limit | Hints (error sd) |
|---|---|---|---|
| Random walk (`random_walk`) | DEVS | 50 | analyst: every 5 ticks ($0.40) |
| Mean reversion (`mean_revert`) | TRV | 50 | analyst: every 5 ticks ($0.80) |
| Jumps (`jumps`) | SESA | **20** | insider ($0.10), rumour ($0.80), newswire ($0.25) |
| Pairs (`pairs`) | WDCC and UOA | 50 each | wdcc_desk: WDCC every 4 ticks ($0.30); uoa_desk: UOA every 8 ticks ($0.50) |

### Random walk: DEVS

The true value of DEVS is a random walk starting near $100: every tick it takes a
small random step, up or down, equally likely. An analyst publishes an
estimate every 5 ticks (error sd $0.40).

### Mean reversion: TRV

TRV's true value is pulled back toward its anchor of $100.00. A gap from
$100 shrinks by about half every 40 ticks, while random shocks (about $0.28
per tick) keep knocking it around. It is usually within about $1.50 of $100
and rarely more than $3 away. An analyst publishes an estimate every 5 ticks
(error sd $0.80).

### Jumps: SESA

SESA's true value drifts like a gentle random walk near $100, but several
times per match it jumps by a few dollars, up or down. Three hint sources:

- **insider**: very precise (error sd $0.10) but rare: at random, about once
  every 50 ticks.
- **rumour**: frequent (on about 2 ticks in 5) and noisy (error sd $0.80).
  About 1 rumour in 20 is way off, by several dollars.
- **newswire**: fires on the tick a jump happens, with the new value (error
  sd $0.25).

Jumps make big positions risky, so the position limit in this round is 20
units.

### Pairs: WDCC and UOA

Two linked assets. WDCC's true value is a random walk near $100. UOA is
0.5 x WDCC plus a gap. The gap wanders but is pulled back toward $0: it
halves in about 50 ticks and is usually within about $1 of $0. So UOA sits
near $50.

- **wdcc_desk**: an estimate of WDCC every 4 ticks (error sd $0.30).
- **uoa_desk**: an estimate of UOA every 8 ticks (error sd $0.50).

### The upload test (`smoke`)

Not a real round: it is the check every upload goes through (section 8). It
is the Random walk round (DEVS), cut to 200 ticks. After a pass, the test
also plays 100 ticks of each of the four rounds above, as a check.

### The house bots

Every match also has bots run by the organisers. They appear in results and
replays but are never ranked.

- **house-mm**, a market maker. It offers to buy a little below and to sell
  a little above its own estimate of the value. When it holds a lot of one
  asset, it moves both of its prices to get rid of it (by up to about $2),
  so it can end up selling below, or buying above, its own estimate. It is
  deliberately a bit slow: it uses each hint a couple of ticks late.
- **house-noise-1, -2 and -3**, noise traders. On about 3 ticks in 10, each
  one buys or sells a few units at random, taking the best price on offer.
  They always place their orders after every other bot (section 5).

Trading is a zero-sum game: valued at the true value, all the profits and
losses in a match add up to exactly $0. The noise traders lose money on
purpose, and the slow house market maker can be beaten. That is where the
teams' profits come from.

## 4. Your bot

### The file

- Your bot is a file called `strategy.py` with a top-level
  `def on_tick(state):`. It runs once per tick.
- Optional: `def on_start(info):`, run once before tick 0 with the match
  info (the same as `state.info`).
- Uploading a single `.py` file? Any name is fine: it is saved as
  `strategy.py`.
- You may add helper `.py` files and import them (`import helpers` for
  `helpers.py`). Then one file must be called `strategy.py`, and file names
  may only use letters, numbers and `_`. At most 50 files and 2 MB in total.
- You may use the Python standard library and numpy. Nothing else is
  installed on the match laptop, which runs Python 3.12.

### Every match is a fresh start

For each match your bot is started in a new process of its own, which lasts
for that match. Variables at the top level of your file keep their values
from tick to tick (to change one inside `on_tick`, declare it `global`
there: [GUIDE.md](GUIDE.md), section 13). Nothing carries over to the next
match.

### Time and memory

| | Limit |
|---|---|
| Starting up (importing your file, plus `on_start`) | 15 seconds (the upload test warns above 3 seconds) |
| Each `on_tick` | 100 ms (0.1 seconds) |
| Thinking time for the match (all your `on_tick` answers together) | 10 seconds per 1,000 ticks: about 10 ms per tick on average (the upload test allows 2 seconds for its 200 ticks, and 1 second for each 100-tick round check) |
| Memory | 1 GB (all of your bot's processes together) |
| Your log (everything you `print`) | 2 MB per match; anything after that is dropped |

The sample bots take well under 1 ms per tick (under 1 second per match).
Section 9 says what happens if your bot is too slow.

### What your bot sees

`on_tick` gets a `state` (all money in dollars):

| Field | What it is |
|---|---|
| `state.tick`, `state.ticks`, `state.ticks_left` | this tick (0 to 999), the number of ticks (1,000), and how many come after this one |
| `state.assets` | the assets in this round, for example `["DEVS"]` |
| `state.cash`, `state.position(asset)` | your cash, and how many units you hold |
| `state.book(asset)` | the top 5 price levels on each side: `.bids`, `.asks`, `.best_bid`, `.best_ask`, `.mid`, `.spread` |
| `state.hints` | the hints published this tick |
| `state.last_hint(asset, source=None)`, `state.hint_history(asset, source=None)` | the latest hint (or `None`), and every hint so far, oldest first. With a source, only that source's hints: `state.last_hint("SESA", "insider")` |
| `state.trades` | every trade from the last tick: price, size and which side started it (no names) |
| `state.fills` | your own trades from the last tick |
| `state.open_orders` | your orders resting in the book |
| `state.rejects`, `state.cancelled` | your rejected actions from the last tick, and your orders the exchange cancelled |
| `state.band(asset)`, `state.limits` | the prices you may use right now, and your limits |
| `state.info` | the match info: round, description, hint sources and their error sd, limits, who is playing |

Your bot never sees the true value, the seed, who placed which order, or
anyone else's position.

### What your bot does

`on_tick` returns a list of actions. An empty list (or `None`) means "do
nothing this tick". Something that isn't a list of actions (a string or a
number, say) is rejected as `bad_action`.

| Action | Meaning |
|---|---|
| `buy(asset, price, qty)` | a bid for `qty` units at `price` or less. It rests in the book until it fills or you cancel it. |
| `sell(asset, price, qty)` | an offer of `qty` units at `price` or more |
| `buy(asset, price, qty, ioc=True)`, `sell(..., ioc=True)` | "immediate or cancel": trade what you can right now, and drop the rest. `ioc` must be `True` or `False`. |
| `buy_now(asset, qty)`, `sell_now(asset, qty)` | trade right now with the orders on offer. `buy_now` pays at most $1 more than the best ask in the book you saw (`state.book(asset).best_ask`); `sell_now` sells for at most $1 less than the best bid. If that side of the book was empty, the limit is $1 from the latest hint. Whatever can't trade within the limit is dropped. `buy_now(asset, qty, max_slippage=0.5)` sets your own limit, in dollars. |
| `cancel(order_id)` | cancel one of your resting orders |
| `cancel_all(asset)`, `cancel_all()` | cancel all your resting orders on one asset, or on every asset |

Import them with `from algomarket import buy, sell, buy_now, sell_now,
cancel, cancel_all`. Prices are rounded to the cent. Plain dictionaries work
too: `{"op": "buy", "asset": "DEVS", "price": 99.5, "qty": 5}`.

Why does `buy_now` have a limit? The book can change between the moment
your bot looks at it and the moment your order goes in: every bot's cancels
are done first, and the bots that go before you may trade (section 5). The
limit stops a "buy now" from paying far more than the prices you saw.

## 5. How a tick works

1. The hints for tick `t` are published.
2. Every bot gets its `state` at the same moment: the book as it was at the
   end of tick `t-1`, its own fills and rejects from tick `t-1`, and the
   hints for tick `t`.
3. Every bot has 100 ms to answer with its actions.
4. **Cancels first.** Every cancel from every bot is done before any new
   order.
5. **Then new orders.** Bots take turns in a random order, shuffled again
   every tick, except the house noise traders: they always go after every
   other bot (in a random order among themselves). Your own orders go in
   the order you listed them.
6. Each bot's equity (section 7) is measured at the true value for tick `t`.

Because cancels go first, a bot that reacts to news can always pull its old
orders before anyone trades with them in that tick. A bot that doesn't react
gets "picked off". And because the noise traders go last, their orders meet
the quotes the other bots have just refreshed: an old quote far from the
value rarely trades with them.

### Matching

An incoming buy trades with the asks priced at or below its price, cheapest
first. An incoming sell trades with the bids priced at or above its price,
highest first. At the same price, the older order goes first. **A trade
happens at the price of the order that was already resting.** Whatever is
left of a normal order then rests in the book. Whatever is left of an
immediate-or-cancel order is dropped.

Example. The DEVS book:

```text
ask  100.40 x 5
ask  100.30 x 5    <- best ask
bid   99.90 x 5    <- best bid
bid   99.80 x 5
```

You send `buy("DEVS", 100.35, 8)`. You buy 5 at $100.30 (the 100.40s cost
more than your price). The other 3 units rest in the book as a bid at
$100.35, the new best bid. With `ioc=True` those 3 would be dropped instead.
With `buy_now("DEVS", 8)` you would buy 5 at $100.30 and 3 at $100.40 (it
would pay up to $101.30: $1 above the best ask).

You can't trade with yourself. If your new order would match one of your own
resting orders, that resting order is cancelled instead (it shows up in
`state.cancelled` with the reason `"self_trade"`).

You hear about your trades one tick later, in `state.fills`.

### The end of the match

After tick 999, all orders are cancelled and every position is cashed out at
the true value of tick 999.

Example: you bought 10 DEVS at $99.50 and sold 4 at $100.20. You hold 6, and
your cash is -$995.00 + $400.80 = -$594.20. The true value ends at $100.10,
so you finish with -$594.20 + 6 x $100.10 = **$6.40**.

## 6. Limits and rejects

| Limit | Value | Notes |
|---|---|---|
| Position | -50 to +50 units per asset (Jumps: -20 to +20) | Your resting orders count. A buy is rejected if your position + your resting buys + its quantity would be over 50. A sell is rejected if your position - your resting sells - its quantity would be below -50. |
| Order size | 1 to 10 units | whole numbers only |
| Resting orders | 10 per asset | immediate-or-cancel orders don't count |
| Actions per tick | 20 | buys, sells and cancels all count |
| Price band | within 20% of the latest hint | If the latest hint is $100.00, you may use prices from $80.00 to $120.00. `state.band(asset)` gives the exact range. |

An action that breaks a rule is **rejected**: it is skipped, and the rest of
your list still goes ahead. Nothing else happens: there is no fine. On the
next tick, `state.rejects` lists each rejected action: its position in the
list you returned (`index`, counting from 0) and the `reason`.

| Reason | Means |
|---|---|
| `position_limit` | the order could take you past your position limit (your resting orders count) |
| `price_band` | the price is outside the band |
| `too_many_orders` | you already have 10 orders resting on that asset |
| `too_many_actions` | more than 20 actions this tick: everything after the 20th is rejected |
| `bad_qty` | the quantity isn't a whole number from 1 to 10 |
| `bad_price` | the price is missing, not a number, or not above $0 |
| `unknown_asset` | that asset isn't traded in this round |
| `unknown_order` | a cancel of an order that isn't resting (often because it just filled) |
| `bad_action` | not an action the exchange understands: also when `on_tick` returned something that isn't a list of actions (index 0), or `ioc` isn't `True` or `False` |

## 7. Scoring

At every tick the exchange values what you have at the true value:

```text
equity = cash + position x true value      (added up over the assets)
```

- **PnL** (profit and loss) is your equity at the end. Everyone starts at $0.
- **Max drawdown** is the biggest drop of your equity below its highest
  point so far. The starting $0 counts as a high point.
- **Score = PnL - 0.5 x max drawdown.**

Worked example. Say your equity climbs to $80 by tick 300, falls to $30 at
tick 450, climbs to $120 by tick 800 and ends at $100 (and never goes lower
than that in between). The biggest drop is from $80 down to $30: $50. (The
drop from $120 to $100 is only $20.) So:

- PnL = $100
- max drawdown = $50
- score = 100 - 0.5 x 50 = **$75**

A bot with the same $100 PnL whose equity never dropped more than $10 would
score $95. A bot whose equity first fell to -$40 has a max drawdown of at
least $40, because it fell $40 below the starting $0. Smooth gains beat wild
swings.

### Ranking

- **In a match**, teams are ranked by score, rounded to the cent. Equal
  scores share a place.
- **Over many matches** (a scrimmage, or the final), each round is scored on
  its own: your score for a round is your **average** score over that
  round's matches. Teams are ranked in each round, and each round gives
  **points = number of teams - place + 1**. With 10 teams, 1st place gets 10
  points and 10th place gets 1. The most points in total wins. If two teams
  have the same points, the higher total of their round averages wins.

Example with 8 teams: 2nd in Random walk (7 points), 5th in Mean reversion
(4), 1st in Jumps (8) and 3rd in Pairs (6) gives 25 points.

Every round counts the same, whatever its scores look like. A round where
the best scores are around $50 matters as much as one where they are around
$400.

## 8. How the day runs

1. **Join code.** Each team gets a join code at the start of the day. It is
   your team's key on the upload page, so don't share it.
2. **Upload** your bot on the competition website (the Submit page)
   whenever you like. The page may limit how often you can upload.
3. **The upload test.** Each upload plays a short test match: 200 ticks
   of the Random walk round, alone against the house bots. It is the same
   test for everyone. It **passes** if your bot starts, keeps running, never
   raises an exception in `on_tick`, misses the 100 ms limit on at most 4 of
   the 200 ticks, and stays within its thinking time (2 seconds for the 200
   ticks, section 4). You may also get warnings, which don't fail the test:
   slow answers (over 50 ms on average), using over half of its thinking
   time, a few missed ticks, a slow start (over 3 seconds to get ready), or
   broken orders (rejects with the reasons `bad_qty`, `bad_price`,
   `unknown_asset`, `bad_action`, `unknown_order` or `too_many_actions`).
   The upload page shows the result, the warnings and the last part of your
   bot's log (from the 200-tick match).
   - If it passes, this upload is now your team's bot.
   - If it fails, fix it and upload again. A failed upload never replaces
     your last passing one.
   - **Round checks.** After a pass, the test also plays 100 ticks of each
     of the four rounds, your bot again alone against the house bots. They
     can only add warnings. If your bot raises an exception in one, or is
     stopped there (section 9), the warning names the round and quotes the
     first error with its file and line, for example `on_tick raised on 100
     of 100 ticks in a short Mean reversion test (it trades TRV): KeyError:
     'DEVS' (strategy.py line 11)`. The upload still passes, but in that
     round your bot will most likely fail the same way in every match, so
     fix it.
   - You can run exactly the same test on your laptop (see
     [GUIDE.md](GUIDE.md), section 4).
   - The round checks are short. Before you upload, also try your bot in
     every round: `python run_local.py --round all --bots strategy.py`.
4. **Scrimmages.** About every 10 minutes, the organisers' laptop plays a
   scrimmage: one match for each open round, with every team's current bot
   plus the house bots, on fresh random seeds. The replays play on the
   projector and the board shows the standings of the latest scrimmage.
   Every past scrimmage is also on the website's **Replays** tab, to watch
   in your browser or download as an `.algoday` file. Scrimmages are
   practice: they don't count for the final. The organisers decide which
   rounds are open, and they may open them one at a time during the day.
5. **The deadline.** Uploads close at a time announced on the day. Your
   **final bot** is your newest upload that was made before the deadline and
   passed its test. Near the end, the board may be frozen or hidden to keep
   the final a surprise.
6. **The final.** Every round x 32 secret seeds = **128 matches**. Every
   match has every team's final bot plus the house bots. The standings are
   worked out as in section 7 (the average of 32 matches per round, then
   points). Then the results are revealed: the projector plays one of the 32
   markets of each round as a sample, then that round's result (the average
   over all 32 markets), then the final standings. So the sample's order can
   differ from the round's result.
7. **Afterwards**, the final's seeds are published. Anyone can rebuild
   those markets (the same true values and the same hints) with
   `python run_local.py --round jumps --seed <seed>`. The other teams' bots
   won't be in your local run, so the trading there will be different.

## 9. When things go wrong

| What happens | That tick | The rest of the match |
|---|---|---|
| `on_tick` raises an exception | Your actions for that tick are lost. Your resting orders stay in the book. | Your bot keeps going, but once it has raised on more than 100 ticks it is stopped (status `disqualified`). |
| `on_tick` takes longer than 100 ms | Your actions for that tick are lost (a late answer is thrown away). Your resting orders stay in the book. | Your bot keeps going, but once it has missed more than 20 ticks it is stopped (status `timeout`). |
| Your file won't import (a syntax error, a missing module, no `on_tick`), or `on_start` raises | | Your bot never starts (status `crashed`). It doesn't trade and scores $0. |
| Starting up takes longer than 15 seconds | | Your bot never starts (status `timeout`) and scores $0. |
| Your bot uses up its thinking time (10 seconds in a 1,000-tick match) | | Your bot is stopped at that tick (status `timeout`). It keeps its position to the end. |
| Your bot's process dies (for example it calls `os._exit()`) | | Your bot is stopped (status `crashed`). |
| Your bot asks for more than 1 GB of memory | Python raises a `MemoryError`, which counts like any other exception (first row). | |

When your bot is stopped, all its resting orders are cancelled and it can't
trade again in that match. **It keeps its position until the end**: the
position is still cashed out at the true value, and the match counts like
any other. Being stopped only lasts for that match: the next match starts
your bot fresh.

Missed ticks hurt quietly: your old orders stay in the book while your bot
isn't looking.

If the organisers' laptop or website fails during the final, the matches it
affected are played again with the same seeds and the same bots. So is a
final match that couldn't start because the platform couldn't load a team's
files: a final match is only ever played with every team in it. If a team's
files are lost for good, the organisers decide what to do (for example, play
the final again on fresh seeds, with that team's previous passing upload).
Matches are not played again because a team's bot failed.

In a scrimmage, a team whose files can't be loaded sits that match out and
gets 0 points for that round. Scrimmages don't count.

## 10. Fair play

- **One team, one bot.** Each person is in one team only. Your team's bot is
  your newest passing upload.
- **Write your own bot.** You may use and change the sample bots and
  anything in the guide. Talking about ideas with other teams is fine;
  sharing code is not.
- **No collusion.** Your bot trades for your own team only. Don't arrange
  with another team to pass them profit (for example by trading with them at
  silly prices), or to go easy on each other.
- **Hands off the machinery.** Your bot runs on the organisers' laptop. It
  may read its state, think, print, and return actions. It must not:
  - use the network or the internet;
  - open, write or delete files (importing your own uploaded `.py` files is
    fine);
  - start other programs, processes or background threads;
  - try to find out the seed, the true value or other teams' code;
  - try to slow down, crash or confuse the match runner, the website or
    other bots (for example by using huge amounts of memory or processor
    time on purpose).
- **Found a bug?** Tell the organisers. Don't use it.
- **We check.** Every trade is recorded in the replays, trades between two
  teams far from the true value are flagged to the organisers automatically,
  and the organisers can read every bot's code. Breaking these rules can get
  your team disqualified. The organisers' decision is final.

Beating the house bots is the point of the game, and so is beating the other
teams by trading better. Reading the simulator code in the starter kit is
allowed too.

## 11. FAQ

**Do we need to know finance?**
No. Everything you need is on this page and in the guide.

**Can my bot use pandas, scikit-learn or another library?**
No. Only the standard library and numpy are installed on the match laptop.
Anything else makes your file fail to import, so the upload test fails.

**Does my bot know which round it's in?**
Yes. `state.info["round"]` is `"random_walk"`, `"mean_revert"`, `"jumps"` or
`"pairs"`. In the upload test it is `"smoke"` in the 200-tick match, and the
real round's name in each 100-tick round check. `state.info["description"]`
holds the round's description.

**Can my bot learn from one match to the next?**
No. Every match starts your bot fresh, and bots may not write files.

**Can I see other teams' orders or positions?**
You see the book (everyone's resting orders, without names) and every trade
(without names). You only see your own fills, orders and position.

**Is our code secret?**
Other teams never see it. Everyone can watch every bot's trades in the
replays.

**Why is our score lower than our PnL?**
That is the drawdown penalty (section 7). Smaller swings give a higher
score.

**Can we hold a negative position?**
Yes, down to -50 units (-20 in Jumps). At the end you pay the true value for
each unit you are short.

**Are the rounds in the starter kit the same as on the day?**
Yes: the same rounds with the same settings. Only the seeds differ, and the
final's seeds stay secret until it is over.

**Can we re-run a scrimmage?**
Each replay shows its seed at the top.
`python run_local.py --round <round> --seed <seed> --bots my_bot.py` rebuilds
the same market (the same true values and hints) on your laptop, without the
other teams.

**Our bot passed on our laptop but failed the upload test.**
The test is the same, so read the reason and the log on the upload page.
Common causes: a helper file that wasn't uploaded, a library that isn't
installed, or a bot that is close to the 100 ms limit or to its thinking
time (the match laptop may be slower than yours).

**Our upload passed, but with a warning about a round.**
Your bot raised an exception, or was stopped, in that round's short check
(section 8), so it will most likely fail the same way in every match of
that round. Play the round on your laptop, for example
`python run_local.py --round mean_revert --bots strategy.py`: the Notes show
the error in full.

**How many times can we upload?**
As often as the upload page allows. Only your newest passing upload plays.
