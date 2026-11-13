# AlgoDay Market: build your first bot

A hands-on tutorial. In about an hour you will set up the starter kit, watch
a match, and build three bots: one that does nothing, one that follows hints
and a simple market maker. Then you get ideas for each round. The official
rules are in [RULES.md](RULES.md).

You don't need to know any finance. Basic Python is enough: functions,
lists, `if` and `for`.

## 1. Set up (10 minutes)

1. **Install Python 3.12** from python.org (the match laptop runs 3.12). On
   Windows, tick "Add python.exe to PATH" in the installer. Then check it in
   a terminal:

   ```
   python --version
   ```

   On macOS and Linux, type `python3` wherever this guide says `python`. On
   Windows, `py` works too.

2. **Install numpy:**

   ```
   python -m pip install numpy
   ```

3. **Unzip the starter kit** and open a terminal in the folder that has
   `run_local.py` in it. On Windows: open the folder in File Explorer, click
   the address bar, type `cmd` and press Enter. On macOS: right-click the
   folder and choose Services, then New Terminal at Folder.

4. **Play a match:**

```
python run_local.py
```

You should see this:

```text
6 bots: do_nothing, random_trader, hint_follower, simple_market_maker, kalman_market_maker, pairs_trader (+ house bots)
Round Random walk (random_walk), seed 1, 1000 ticks

  rank  bot                  status      pnl $   max dd $    score $  trades
     1  kalman_market_maker  ok         135.41      32.96     118.93     282
     2  simple_market_maker  ok          98.73      28.49      84.49     311
     3  hint_follower        ok           9.15      12.47       2.91      39
     4  do_nothing           ok           0.00       0.00       0.00       0
     4  pairs_trader         ok           0.00       0.00       0.00       0
     6  random_trader        ok         -21.68      55.59     -49.48      72
     -  house-mm             house      209.36      81.98     168.37     813
     -  house-noise-1        house     -132.75     132.75    -199.13     389
     -  house-noise-2        house     -143.82     158.38    -223.01     363
     -  house-noise-3        house     -154.40     176.23    -242.51     369
  score = pnl - lambda x max drawdown; house bots are not ranked.

Played in 0.8 s (engine: python).
Bot logs (their print() output and errors): out\logs\random_walk_seed1
Replay: out\random_walk_seed1.algoday
  To watch it: click it in VS Code (set up once: python run_local.py --vscode), or drop it on the site's Replays tab.
```

Matches are deterministic: the same command gives the same numbers on every
laptop. Only the "Played in" line changes (it may also say `engine: native`;
both engines give the same results), and on macOS and Linux the paths use
`/`. If your table matches this one, you are set up.

(The one exception: if your laptop is so busy that a bot misses the 100 ms
deadline on some tick, that bot does nothing on that tick, so its numbers
change a little. `run_local.py` tells you when that happens.)

What's in the folder:

| | |
|---|---|
| `strategy.py` | a working bot to start from (a small market maker): edit it and upload it |
| `README.md` | quick setup, and how to test and upload `strategy.py` |
| `run_local.py` | plays bots against each other on your laptop |
| `bots/` | six sample bots. Read them: they are short and commented. |
| `algomarket/` | the simulator. You don't need to change it. Its comments sometimes cite `DESIGN.md`: that is the organisers' design notes, which aren't in the kit. Everything a bot needs is in this guide and the rules. |
| `docs/` | this guide (`GUIDE.md`) and the rules (`RULES.md`) |
| `viewer/` | the replay player, and the replay viewer for VS Code (section 2) |
| `out/` | made by `run_local.py`: replays (`.algoday` files) and bot logs |
| `.gitignore` | tells git to skip `out/` (only matters if you use git) |

## 2. Watch a replay

`run_local.py` saved the match as a replay: `out/random_walk_seed1.algoday`.
It plays in a tab in VS Code, next to your code. Set that up once (it adds
the kit's replay viewer to VS Code):

```
python run_local.py --vscode
```

Then open the starter folder in VS Code, click
`out/random_walk_seed1.algoday` in the file list, click the replay and
press the space bar. Play the same match again and its tab reloads with the
new match. (It also works in Cursor and VSCodium.)

**No VS Code, or the viewer won't install?** Open the competition website,
go to its **Replays** tab and drop the `.algoday` file there. It plays in
your browser, and the file is not uploaded. The Replays tab also lists every
past scrimmage, to watch in your browser or download as an `.algoday` file
(a downloaded one opens in VS Code like your own).

What you see:

- **The top bar**: the round, the asset, the seed, the tick counter, and the
  buttons: restart, play/pause, the speed (1x, 4x, 16x, 64x) and an eye
  (show the true value).
- **The price chart** (one per asset):
  - the shaded band between the green line (best bid) and the red line (best
    ask): that is the market;
  - triangles are trades: a green one pointing up means someone bought from
    an ask, a red one pointing down means someone sold to a bid. Bright ones
    involve a team; faint ones are house bots trading with each other.
    Bigger means more units;
  - hollow blue markers are hints, one shape per source (see the legend);
  - the true value (a violet line) stays hidden until the end. Press V to
    peek.

  Hover over the chart to read the bid, ask and last trade at any tick.
- **PnL**: every bot's equity (its cash plus its position valued at the true
  value), shown as a race. When the match ends, the race re-sorts into the
  official order (ranked by score; tied teams share a place; the winner's
  row turns gold), so it matches the Results card. A red ✕ (crashed), a
  clock (timeout) or a slashed circle (disqualified) appears next to a bot
  at the tick it was stopped.
- **Book**: the top 5 asks (above) and bids (below) with their sizes, and
  the spread in the middle.
- **Tape**: the latest trades: tick, buyer, seller, quantity and price. The
  side that started the trade is highlighted.
- **Results**, at the end: every bot's PnL, max drawdown and score.

Keys (in VS Code, click the replay first): space = play/pause, left/right
arrows = one tick (with Shift: 50 ticks), 1 to 4 = speed, V = true value,
R = restart, Esc = close the results.

The replay counts ticks from 1 to 1000. Your bot counts them from 0 to 999.

Things to look for:

- Find a hint that lands far from the market. What do the bid and ask lines
  do over the next few ticks? (The house market maker catches up slowly.)
- Watch the noise traders in the PnL race. Where does their money go?
- At the end, compare the hints with the true value. How far off were they?

## 3. How the market works (5 minutes)

- Each asset has a **true value** that nobody can see. At the end of the
  match, every unit you hold is paid out at that value.
- **Hints** are the true value plus a random error. The round tells you how
  big the errors usually are (the "error sd").
- The **order book** holds everyone's resting orders: **bids** (offers to
  buy) and **asks** (offers to sell). The book in the replay looks like
  this:

  ```text
  ask  100.40 x 5
  ask  100.30 x 5    <- best ask: the cheapest seller
  bid   99.90 x 5    <- best bid: the highest buyer
  bid   99.80 x 5
  ```

- There are two ways to trade:
  1. **Take**: trade right now with an order that is already in the book.
     You buy at the best ask ($100.30 here) or sell at the best bid
     ($99.90). It is quick and usually works, but you pay the spread.
  2. **Make**: put your own bid or ask in the book and wait. You might get a
     better price, but only if somebody wants to trade with you, and that
     somebody might know more than you do.
- **Why anyone makes money**: the noise traders buy and sell at random, and
  the house market maker reacts slowly. A bot that knows the value better
  than they do can buy cheap and sell dear.
- **Timing**: each tick, every bot sees the book as it was at the end of the
  last tick, plus this tick's hints, and they all act at the same time.
  Every cancel is done first; then the new orders go in, bot by bot, in a
  random order, except that the house noise traders always go last. You
  hear about your trades on the next tick.
- **Fresh quotes win**: when a noise trader buys or sells, every other bot's
  quotes for this tick are already in, and it takes the best price on
  offer. So your resting quote only fills when it is the best price at that
  moment. An old quote that you forgot to cancel only gets there once the
  market has moved past it, and then it is a bad price for you: a market
  maker that doesn't cancel scores below 0 (section 8 shows how far).

[RULES.md](RULES.md) sections 5 and 6 have the details: how orders match,
and the limits.

## 4. Bot 1: do nothing

The kit's `strategy.py` already works, and the README shows how to change
it. This guide takes the other road: it builds bots from scratch, in new
files, so you see every piece. Either way works, and you can copy anything
from here into `strategy.py`. Whatever file you upload is saved as
`strategy.py` (section 10).

Make a file called `my_bot.py` in the starter folder, next to
`run_local.py`:

```python
# my_bot.py: the simplest legal bot. It never trades.
def on_tick(state):
    # Return a list of actions. An empty list means "do nothing".
    return []
```

Play it against the sample hint follower:

```
python run_local.py --bots my_bot.py bots/hint_follower.py
```

```text
2 bots: my_bot, hint_follower (+ house bots)
Round Random walk (random_walk), seed 1, 1000 ticks

  rank  bot            status      pnl $   max dd $    score $  trades
     1  hint_follower  ok          22.95      42.61       1.65      74
     2  my_bot         ok           0.00       0.00       0.00       0
     -  house-mm       house      514.03      67.65     480.20    1064
     -  house-noise-1  house     -184.76     184.76    -277.15     339
     -  house-noise-2  house     -164.85     178.55    -254.12     324
     -  house-noise-3  house     -187.37     201.44    -288.09     327
  score = pnl - lambda x max drawdown; house bots are not ranked.
...
```

`my_bot` scores exactly $0.00: it never trades, so nothing can go wrong. It
is the baseline. A bot that scores below 0 did worse than not trading at all.

And look how close it was. The hint follower made $22.95, but on the way
its equity dropped by $42.61, so its score is 22.95 - 0.5 x 42.61 = $1.65:
it beat `my_bot` by less than $2. That is the drawdown penalty at work. (One
match is also mostly luck: over many matches the hint follower does much
better than that.)

Every upload is checked with a short test match (RULES.md, section 8). Run
the same test on your laptop:

```
python -c "from algomarket import match; t = match.run_smoke('my_bot.py'); print(t['verdict'], *t['warnings'], sep='\n')"
```

```text
PASS
```

A failing bot prints `FAIL:` and the reason instead. To see where, run the
same test with `python run_local.py --round smoke --seed 0 --bots my_bot.py`:
the Notes show the first error in full (file, line and message).

The test plays 200 ticks of Random walk. After a pass, it also plays 100
ticks of each of the four rounds: the **round checks**. They never fail the
test, but a round where your bot raises an exception or is stopped adds a
warning, printed after `PASS` (the upload page shows them too). For example,
a bot that uses `state.last_hint("DEVS").value` passes (the 200-tick test
trades DEVS), then gets this warning, and the same for Jumps and Pairs:

```text
on_tick raised on 100 of 100 ticks in a short Mean reversion test (it trades TRV): AttributeError: 'NoneType' object has no attribute 'value' (devs_bot.py line 4)
```

The round checks are short (and `--round smoke` doesn't play them), so
before you upload also try your bot in every round (`--round all`, section
9).

You could upload `my_bot.py` right now: it passes. It just won't win.

## 5. Look before you trade

This bot doesn't trade either. It prints what it sees:

```python
# look_bot.py: never trades. Prints what it sees every 100 ticks.
def on_start(info):
    print("round:", info["round"], "| assets:", info["assets"])
    print("limits:", info["limits"])


def on_tick(state):
    if state.tick % 100 == 0:
        for asset in state.assets:
            book = state.book(asset)
            hint = state.last_hint(asset)
            print(f"tick {state.tick} {asset}: best bid {book.best_bid}, best ask {book.best_ask}, "
                  f"last hint {hint.value:.2f} ({hint.source}, tick {hint.tick})")
    return []
```

```
python run_local.py --bots look_bot.py
```

`print()` doesn't show on the screen: it goes to your bot's log file.
`run_local.py` tells you the folder (`out/logs/random_walk_seed1/`). The file
is `00_look_bot.log` (`00` because it is the first bot in the list):

```log
round: random_walk | assets: ['DEVS']
limits: {'position_limit': 50, 'max_order_qty': 10, 'max_open_orders': 10, 'max_actions_per_tick': 20}
tick 0 DEVS: best bid None, best ask None, last hint 99.92 (analyst, tick 0)
tick 100 DEVS: best bid 99.45, best ask 99.86, last hint 98.90 (analyst, tick 100)
tick 200 DEVS: best bid 97.73, best ask 98.14, last hint 98.28 (analyst, tick 200)
tick 300 DEVS: best bid 97.29, best ask 97.7, last hint 96.27 (analyst, tick 300)
...
tick 900 DEVS: best bid 97.71, best ask 98.22, last hint 97.40 (analyst, tick 900)
```

Two things to notice:

- At tick 0 the book is empty (`None`): nobody has placed an order yet.
  `best_bid` and `best_ask` are `None` whenever a side of the book is empty,
  so always check for that.
- Hints are only estimates. At tick 300 the hint said $96.27, while the
  market was $97.29 to $97.70. Which was closer? Open the replay, press V to
  show the true value, and hover around tick 300.

The parts of `state` you will use most (section 13 has the full list):

| | |
|---|---|
| `state.tick` | this tick, from 0 to 999 |
| `state.assets` | the assets in this round, for example `["DEVS"]` |
| `state.position(asset)`, `state.cash` | what you hold, and your cash |
| `state.book(asset)` | `.best_bid`, `.best_ask`, `.bids`, `.asks` (lists of `(price, qty)`) |
| `state.last_hint(asset)` | the latest hint: `.value`, `.source`, `.tick` |
| `state.limits` | `["position_limit"]`, `["max_order_qty"]`, ... |
| `state.info` | the round's details, for example `state.info["hint_sources"]` |

## 6. Your first trade

This bot buys 5 units once, at tick 10, and keeps them to the end:

```python
# first_trade.py: buys 5 units once, at tick 10, then holds them to the end.
from algomarket import buy_now


def on_tick(state):
    for fill in state.fills:
        print(f"tick {state.tick}: bought {fill.qty} {fill.asset} at ${fill.price:.2f}")
    if state.tick == 10:
        return [buy_now(state.assets[0], 5)]
    if state.ticks_left == 0:
        print(f"last tick: position {state.positions}, cash ${state.cash:.2f}")
    return []
```

```
python run_local.py --bots first_trade.py
```

```text
1 bots: first_trade (+ house bots)
Round Random walk (random_walk), seed 1, 1000 ticks

  rank  bot            status      pnl $   max dd $    score $  trades
     1  first_trade    ok         -13.62      22.45     -24.84       1
...
```

Its log (`out/logs/random_walk_seed1/00_first_trade.log`):

```log
tick 11: bought 5 DEVS at $100.28
last tick: position {'DEVS': 5}, cash $-501.40
```

What happened:

- At tick 10 the bot sent `buy_now`. It heard about the trade at tick 11:
  you always learn about fills one tick later.
- `buy_now` buys from the asks on offer, paying at most $1 more than the
  best ask in the book the bot saw. What it can't buy that cheaply is
  dropped (it shows up in `state.cancelled` with the reason `"ioc"`).
- It bought from the house market maker's ask at $100.28. The true value at
  that moment was $99.37 (check in the replay), so it paid $0.91 per unit
  more than the units were worth. That is the price of taking.
- Its cash went to -$501.40 (5 x $100.28). Then the true value fell, down to
  $95.79 at tick 716. At that point its equity was -$501.40 + 5 x $95.79 =
  -$22.45. That was its biggest drop below $0, so its max drawdown is
  $22.45.
- The true value ended at $97.5569 (the replay rounds it to $97.56), so
  PnL = -$501.40 + 5 x $97.5569 = -$13.62. The score is PnL - 0.5 x max
  drawdown = -$24.84.

A position is a bet on the true value. The longer you hold it, the more its
swings show up as drawdown.

## 7. Bot 2: a hint follower

The idea: if someone is selling well **below** the hint, buy from them. If
someone is buying well **above** the hint, sell to them. "Well" means by more
than twice the hint's error sd, so the hint's own error is unlikely to
explain the gap.

```python
# my_follower.py: buy when the market is cheap compared with the hint,
# sell when it is expensive.
from algomarket import buy, sell

SIZE = 5   # units per trade


def on_tick(state):
    actions = []
    for asset in state.assets:
        hint = state.last_hint(asset)
        if hint is None:
            continue
        # How noisy is this hint? The round says (in dollars).
        noise = state.info["hint_sources"][hint.source]["noise"]
        margin = 2 * noise
        book = state.book(asset)
        position = state.position(asset)
        limit = state.limits["position_limit"]

        # Someone sells well below the hint: buy from them.
        if book.best_ask is not None and book.best_ask < hint.value - margin:
            if position + SIZE <= limit:
                actions.append(buy(asset, book.best_ask, SIZE, ioc=True))

        # Someone buys well above the hint: sell to them.
        if book.best_bid is not None and book.best_bid > hint.value + margin:
            if position - SIZE >= -limit:
                actions.append(sell(asset, book.best_bid, SIZE, ioc=True))
    return actions
```

Notes on the code:

- The margin comes from the round. In Random walk the analyst's error sd is
  $0.40, so the margin is $0.80. In Mean reversion it is $1.60.
- `buy(asset, book.best_ask, SIZE, ioc=True)` is an immediate-or-cancel
  order at the best ask's price. It only buys at that price or better, and it
  never leaves an order behind. `buy_now` would also take the next asks up,
  paying up to $1 more than the best ask you saw. That matters because every
  cancel is done before any new order: by the time your order goes in, the
  asks you saw may be gone, and the ones left may be dearer.
- The position checks keep each order inside the limit, so it isn't
  rejected.

From here on, we test bots against four samples, called the **sample
field**: `hint_follower`, `simple_market_maker`, `kalman_market_maker` and
`random_trader`.

```
python run_local.py --bots my_follower.py bots/hint_follower.py bots/simple_market_maker.py bots/kalman_market_maker.py bots/random_trader.py
```

```text
5 bots: my_follower, hint_follower, simple_market_maker, kalman_market_maker, random_trader (+ house bots)
Round Random walk (random_walk), seed 1, 1000 ticks

  rank  bot                  status      pnl $   max dd $    score $  trades
     1  kalman_market_maker  ok         153.04      35.64     135.22     299
     2  simple_market_maker  ok         100.53      32.89      84.08     316
     3  hint_follower        ok          11.93      13.20       5.33      35
     4  my_follower          ok          -5.71      18.72     -15.07      17
     5  random_trader        ok         -30.19      43.76     -52.07      78
...
```

`my_follower` lost $5.71, and its equity dropped by $18.72 along the way.
One match is mostly luck, so play every round, 10 seeds each:

```
python run_local.py --round all --seeds 10 --bots my_follower.py bots/hint_follower.py bots/simple_market_maker.py bots/kalman_market_maker.py bots/random_trader.py
```

```text
5 bots: my_follower, hint_follower, simple_market_maker, kalman_market_maker, random_trader (+ house bots)
Rounds random_walk, mean_revert, jumps, pairs x seeds 1-10
...
Overall standings (points per round: n_teams - rank + 1; ties broken by total score)
  rank  bot                  points    total $  random_walk  mean_revert        jumps        pairs
     1  kalman_market_maker      20     873.62       175.87       214.74       325.42       157.59
     2  simple_market_maker      14     401.78       125.22       148.44        45.63        82.49
     3  hint_follower            12     161.23        17.39        22.34       110.03        11.47
     4  my_follower              10      53.12        45.38       -58.49        71.39        -5.16
     5  random_trader             4    -296.75       -49.34       -73.18      -125.84       -48.39
...
```

The columns per round are average scores (and the points are worked out as
in the final: RULES.md, section 7). In Random walk `my_follower` even beats
the sample `hint_follower`, but it scores below 0 in Mean reversion and Pairs.
The reason: it only ever *opens* positions. It doesn't close them unless
the price swings well past the other side of the hint (by the margin
again: $0.80 in Random walk), so its inventory piles up, and holding that
inventory while the true value wanders costs drawdown.

**Exercise: take profit.** Once you hold a position, close it as soon as the
price crosses back over the hint: when you are long, sell if `best_bid` is
above the hint; when you are short, buy if `best_ask` is below it. Only trade
back down to a position of 0. Then compare with `bots/hint_follower.py`,
which does exactly this.

## 8. Bot 3: a market maker

The idea: always keep a bid a little below your estimate of the value and an
ask a little above it. When a noise trader buys from your ask and another
one sells to your bid, you earn the gap between them: the spread.

```python
# my_maker.py: keep a bid below and an ask above the latest hint.
from algomarket import buy, cancel_all, sell

HALF_SPREAD = 0.30   # dollars from the hint to each quote
SIZE = 3             # units per quote
SKEW = 0.02          # move both quotes this much per unit we hold


def on_tick(state):
    actions = []
    for asset in state.assets:
        hint = state.last_hint(asset)
        if hint is None:
            continue
        position = state.position(asset)
        limit = state.limits["position_limit"]
        # Holding a lot? Quote lower, so we sell more and buy less.
        centre = hint.value - SKEW * position

        actions.append(cancel_all(asset))   # throw away last tick's quotes
        if position + SIZE <= limit:
            actions.append(buy(asset, round(centre - HALF_SPREAD, 2), SIZE))
        if position - SIZE >= -limit:
            actions.append(sell(asset, round(centre + HALF_SPREAD, 2), SIZE))
    return actions
```

Four ideas are packed into this bot:

1. **The spread.** A wide spread earns more on each trade but fills less
   often. A tight one fills often but earns little on each trade.
2. **Inventory and skew.** If more people sell to you than buy from you, you
   end up holding a lot, and that position swings with the true value. `SKEW`
   moves both quotes against your position: when you are long, you quote
   lower, so you sell more and buy less.
3. **Getting picked off.** If your estimate is wrong and someone else's is
   better, they trade with you exactly when you are wrong. Here the estimate
   is a single hint, and in Random walk that hint's error sd ($0.40) is
   bigger than the half-spread ($0.30). So the spread has to pay for those
   bad trades.
4. **Cancels go first.** The bot cancels and re-quotes every tick, in one
   list. Every cancel is done before any new order, so:
   - your old quotes are gone before anyone can trade with them this tick;
   - your new orders never trade with your own old ones;
   - your old orders don't count towards your position limit or the
     10-order limit.

   Without `cancel_all`, your quotes would pile up: after 5 ticks you would
   have 10 resting orders, and from then on most new quotes would be
   rejected (`too_many_orders`), so your quotes would stop following the
   hints. And an old quote only fills once the market has moved past it
   (section 3).

Play it against the sample field:

```
python run_local.py --bots my_maker.py bots/hint_follower.py bots/simple_market_maker.py bots/kalman_market_maker.py bots/random_trader.py
```

```text
5 bots: my_maker, hint_follower, simple_market_maker, kalman_market_maker, random_trader (+ house bots)
Round Random walk (random_walk), seed 1, 1000 ticks

  rank  bot                  status      pnl $   max dd $    score $  trades
     1  kalman_market_maker  ok         109.71      30.25      94.59     229
     2  simple_market_maker  ok          96.89      31.69      81.04     335
     3  hint_follower        ok           3.53      14.76      -3.85      24
     4  random_trader        ok         -20.03      40.07     -40.06      80
     5  my_maker             ok         -22.50      43.90     -44.45     529
...
```

It traded a lot (529 times) and still came last on this seed, below even
the random trader, with a score of -$44.45. Is that bad luck or a bad bot?
Play 10 seeds of Random walk to find out:

```
python run_local.py --seeds 10 --bots my_maker.py bots/hint_follower.py bots/simple_market_maker.py bots/kalman_market_maker.py bots/random_trader.py
```

```text
5 bots: my_maker, hint_follower, simple_market_maker, kalman_market_maker, random_trader (+ house bots)
Rounds random_walk x seeds 1-10
...
Overall standings (points per round: n_teams - rank + 1; ties broken by total score)
  rank  bot                  points    total $  random_walk
     1  kalman_market_maker       5     128.65       128.65
     2  simple_market_maker       4     108.85       108.85
     3  my_maker                  3      52.84        52.84
     4  hint_follower             2      17.70        17.70
     5  random_trader             1     -45.29       -45.29
...
```

Over 10 seeds it averages a score of $52.84 a match: seed 1 was bad luck.

**Experiments.** Change one thing at a time in `my_maker.py` and run the
same 10 seeds again. Here is what we got (the average score of `my_maker`,
Random walk, seeds 1 to 10):

| Change | Average score |
|---|---|
| none (as above) | $52.84 |
| `HALF_SPREAD = 0.05` | -$129.51 |
| `HALF_SPREAD = 1.00` | $34.76 |
| `SKEW = 0.0` | $33.25 |
| no `cancel_all` (delete that line) | -$80.84 |

Too tight, and better-informed bots pick you off. Too wide, and your quotes
are rarely the best price, so the noise traders trade with someone else:
with `HALF_SPREAD = 1.00` it traded about 55 times a match instead of about
476. Without skew, the inventory runs away from you and costs drawdown. And
without `cancel_all`, your quotes stop following the hints (idea 4), so
they mostly fill when they are a bad price for you.

Now play every round:

```
python run_local.py --round all --seeds 10 --bots my_maker.py bots/hint_follower.py bots/simple_market_maker.py bots/kalman_market_maker.py bots/random_trader.py
```

```text
5 bots: my_maker, hint_follower, simple_market_maker, kalman_market_maker, random_trader (+ house bots)
Rounds random_walk, mean_revert, jumps, pairs x seeds 1-10
...
Overall standings (points per round: n_teams - rank + 1; ties broken by total score)
  rank  bot                  points    total $  random_walk  mean_revert        jumps        pairs
     1  kalman_market_maker      20     885.78       128.65       257.97       398.16       101.00
     2  simple_market_maker      16     536.92       108.85       173.71       173.02        81.34
     3  hint_follower            11     146.23        17.70        12.37       110.37         5.79
     4  random_trader             7    -290.27       -45.29       -72.06      -126.13       -46.79
     5  my_maker                  6    -511.11        52.84      -148.67      -357.26       -58.02
...
```

It scores above 0 in Random walk and below 0 in the other rounds, in Jumps
even further below than the random trader. Why?

- **Mean reversion**: the hints are twice as noisy ($0.80), so quotes $0.30
  either side of one hint are often on the wrong side of the true value.
- **Jumps**: about 1 rumour in 20 is several dollars off, and the quotes jump
  with it. Any bot that ignores that rumour gets a great deal from you.
- **Pairs**: UOA gets a hint only every 8 ticks, and it is noisy ($0.50).

Two fixes, and the samples show both. Get a **better estimate**:
`simple_market_maker.py` averages the last 4 hints, and
`kalman_market_maker.py` uses a Kalman filter that weighs each source by its
error sd and ignores outliers. And **quote wider when you are unsure**: the
Kalman bot's spread grows with its uncertainty.

## 9. Test like it's the final

The final plays every round with 32 seeds nobody has seen. Test for that:

- **Many seeds, every round.** `--round all --seeds 20`. One match is
  mostly luck.
- **Fresh seeds.** If you tuned on seeds 1 to 10, check on `--seed 101
  --seeds 20`. Settings that only work on the seeds you tuned on won't help
  in the final.
- **A tough field.** On the day, other teams' bots will be at least as good
  as the samples. Add strong samples twice:
  `--bots my_bot.py bots/kalman_market_maker.py bots/kalman_market_maker.py`
  (the second copy is renamed `kalman_market_maker-2`).
- **The upload test**, as in section 4, before every upload. Fix every
  warning it prints.
- **Read the Notes** that `run_local.py` prints after the table: rejected
  orders, exceptions and missed deadlines, with the first error in full and
  the end of your log.
- **Speed.** The samples take under 1 ms per tick. Each `on_tick` may take
  up to 100 ms, but a match allows 10 s of thinking in all (about 10 ms per
  tick on average). A bot that uses it all is stopped, and `run_local.py`'s
  Notes warn at half. Avoid looping over the whole hint history every tick;
  keep running totals instead.

### Measure your estimates against the truth

Your bot can't see the true value, but the replay file can: every
`out/<round>_seed<seed>.algoday` holds the true value of every tick (the
file is JSON, compressed with gzip). So you can check an estimate after the
match. For example, this script measures how far the hints were from the
true value:

```python
# hint_errors.py: after a match, how far were the hints from the true value?
# Run it in the starter folder with: python hint_errors.py
import gzip
import json
import math

replay = json.load(gzip.open("out/random_walk_seed1.algoday"))
errors = []
for tick, asset, value, source in replay["hints"]:
    errors.append(value - replay["true_value"][asset][tick])
rms = math.sqrt(sum(e * e for e in errors) / len(errors))
print(f"{len(errors)} hints, typical error ${rms:.2f}")
```

```
python hint_errors.py
```

```text
200 hints, typical error $0.40
```

That matches the analyst's published error sd of $0.40. Print your own
estimate each tick in your bot (with the tick number), and measure it the
same way: a smaller typical error than the raw hints means a better
estimate.

## 10. Upload

On the day, your team gets a join code. On the competition website, open the
Submit page, enter the join code and choose your file. A single file can
have any name; it is saved as `strategy.py`. If you use helper files, upload
them all together, with the main file called `strategy.py` (section 11 has an
example).

Each upload goes through the upload test (section 4). If it passes, it
becomes your team's bot for the scrimmages and the final. Warnings don't
stop that, but fix them: a round check that raises means your bot will most
likely raise in every match of that round. If it fails, the page shows the
reason and the end of your bot's log, and your previous passing upload
keeps playing. The full story is in RULES.md, section 8.

## 11. Going further, round by round

These are ideas, not answers. Each one is something a strong team might
build.

### Every round: one bot, four rounds

Your one bot plays every round, so give each round its own function. This
template also shows a helper file (`helpers.py` next to `strategy.py`):

```python
# my_team/helpers.py: shared code, imported by strategy.py.
def smooth(old, new, weight):
    """Move old a share `weight` of the way toward new (one EMA step)."""
    if old is None:
        return new
    return old + weight * (new - old)
```

```python
# my_team/strategy.py: one bot for every round, one function per round.
from helpers import smooth

estimates = {}   # asset -> smoothed hint value; lives for the whole match


def trade_random_walk(state):
    return []    # your Random walk ideas go here


def trade_mean_revert(state):
    return []


def trade_jumps(state):
    return []


def trade_pairs(state):
    return []


BY_ROUND = {
    "random_walk": trade_random_walk,
    "mean_revert": trade_mean_revert,
    "jumps": trade_jumps,
    "pairs": trade_pairs,
    "smoke": trade_random_walk,   # the 200-tick upload test is a short random walk
}


def on_tick(state):
    for hint in state.hints:
        estimates[hint.asset] = smooth(estimates.get(hint.asset), hint.value, 0.3)
    trade = BY_ROUND.get(state.info["round"])
    if trade is None:
        return []
    return trade(state)
```

```
python run_local.py --bots my_team/strategy.py
```

Don't give a helper file the name of a Python module (`random.py`,
`math.py`, `numpy.py`): it would hide the real one.

Ideas for every round:

- A better estimate of the true value is worth more than anything else.
- Small positions mean small drawdowns. Know what you hold and lean against
  it.
- Use `state.fills` to see what you traded and at what price.
- Beat `kalman_market_maker` on 20+ fresh seeds in every round, and you are
  doing well.

### Random walk: filtering the hints

- One hint is off by about $0.40. The average of n hints is off by about
  $0.40 divided by the square root of n. But the true value keeps moving, so
  old hints are out of date. A good estimate gives recent hints more weight.
- An exponential moving average (the `smooth` helper above) does that. A
  small weight is smooth but slow; a big weight is fast but noisy.
- The best weight depends on how far the value moves between hints compared
  with the hint noise. A Kalman filter works that out for you: see
  `bots/kalman_market_maker.py`. Its `DRIFT = 0.15` is only a guess.
- You can measure how fast the value moves from the hints themselves. For
  two hints k ticks apart, the variance of their difference is about
  2 x 0.40² + k x step², where step is the size of the value's random step
  per tick. Fit step from the hints you have seen.
- With a better estimate you can quote tighter without being picked off, and
  trade against the slow house market maker right after each hint.

### Mean reversion: use the anchor

- TRV is pulled back to $100: a gap from $100 halves in about 40 ticks. So
  the value is usually within about $1.50 of $100, while one hint can easily
  be $0.80 off.
- So when a hint says $101.60, the truth is probably a bit closer to $100
  than that. Combine the hint with what you know about where TRV usually
  sits.
- Between hints, your estimate should drift back toward $100 too: after 5
  ticks, about 92% of a gap is left (0.5 to the power 5/40 is about 0.917).
- Prices far from $100 tend to come back, so trading toward $100 pays. But
  they can stay away for a while, so watch your drawdown.

### Jumps: react to news, doubt rumours

- The newswire fires on the very tick of a jump, with the new value (error
  sd $0.25). For a while after a jump, the house market maker, and any slow
  bot, keep quoting near the old value.
- Cancels go first, so you can pull your own quotes in the same tick the
  news arrives.
- About 1 rumour in 20 is several dollars off. Don't let one rumour move your
  estimate a lot: compare it with your estimate and with the precise
  sources.
- The kit's `strategy.py` averages the last 4 hints, rumours included. If
  only one team runs it, it makes money in Jumps, but when several teams
  run it unchanged they can all score below 0 there: a rumour that is way
  off moves every copy's quotes the same way at once, and the other bots
  trade with all of them. In our tests (seven copies), the median of the
  last 5 hints instead of the average lifted their score well above 0.
- The insider is precise but rare. When it speaks, listen.
- The position limit is 20 here: a $3 jump on 20 units is $60. Keep positions
  small when you are unsure.

### Pairs: price one asset from the other

- UOA = 0.5 x WDCC + gap. WDCC's hints are more precise ($0.30 against
  $0.50) and twice as frequent, so most of what you know about UOA comes
  from WDCC.
- Each UOA hint tells you about the gap: gap = UOA hint - 0.5 x (your
  WDCC estimate). The gap is pulled back to $0 (it halves in about 50 ticks),
  so let your gap estimate fade toward $0 between UOA hints.
- Fair UOA = 0.5 x (fair WDCC) + (gap estimate). `bots/pairs_trader.py`
  does this.
- **Hedging**: if you hold +10 UOA, holding -5 WDCC cancels most of the
  risk from WDCC's random walk. What's left is the gap, which keeps being
  pulled back to $0. Hedged positions swing less, so they cost less
  drawdown.

### For the statisticians

Each round is a small state-space model: a hidden value with known dynamics,
seen through noisy observations whose error sd is published. Filtering,
outlier detection and estimating parameters from data all pay off. But this
is a market, not a forecasting contest: your orders change what other bots
do, so inventory, spread and timing matter as much as the estimate.

## 12. Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| `python` is not found | On Windows try `py`; on macOS and Linux, `python3`. Or reinstall Python with "Add python.exe to PATH" ticked. |
| `run_local.py` says `No module named 'numpy'` | Install it: `python -m pip install numpy`. |
| Your bot's log says `No module named ...` | Bots run with the same Python as `run_local.py`, so install the module for that Python. Only the standard library and numpy are on the match laptop: anything else fails there (RULES.md, section 4). |
| `pip` says `externally-managed-environment` (macOS, Linux) | Use a virtual environment (below). |
| `can't find the bot file` | Run the command in the starter folder, and check the file name. |
| `on_tick raised an exception` | A bug. The Notes show the first error in full (file, line, message) and the end of the log; later errors name the file and line too. |
| `TypeError: unsupported operand type(s) for -: 'NoneType' and 'float'` | You did maths with `best_bid` or `best_ask` while that side of the book was empty (it always is at tick 0). Check for `None` first. |
| `AttributeError: 'NoneType' object has no attribute 'value'` | `last_hint` returned `None`, often because the asset name is hard-coded (`"DEVS"`) and this round trades something else. Loop over `state.assets`. |
| Upload-test warning: `on_tick raised on 100 of 100 ticks in a short Mean reversion test (it trades TRV): ...` | Your bot passed, but it breaks in that round. The warning ends with the error, file and line: often an asset name is hard-coded (the row above). To see the error in full, play that round: `python run_local.py --round mean_revert --bots my_bot.py`. |
| Upload-test warning: `stopped at tick 0 in a short Pairs test (it trades WDCC and UOA): ...` | Your bot was stopped in that round, for the reason given. `crashed (start_error)` means `on_start` raised there, for example on `info["start_prices"]["DEVS"]` in a round without DEVS. |
| Upload-test warning: `slow start: took 3.6 s to get ready` | Importing your file and running `on_start` took over 3 s (the limit is 15 s). Every match waits for the slowest bot, so keep heavy work out of import and `on_start`. |
| `UnboundLocalError: cannot access local variable 'count' where it is not associated with a value` | `on_tick` changes a top-level variable (`count += 1`) without declaring it. Put `global count` at the top of `on_tick`, or keep the value in a dict (section 13). |
| `IndexError: list index out of range` at `state.hints[0]` | `state.hints` only holds the hints published this tick, and most ticks have none. Use `state.last_hint(asset)` (and check it for `None`), or loop: `for hint in state.hints:`. |
| `missed the 100 ms deadline` | Your `on_tick` is too slow. Keep running totals instead of re-reading the whole history every tick. |
| `too slow overall` (`over_budget`) | Your `on_tick` takes more than about 10 ms on average, so it used up the match's 10 s of thinking time. Keep running totals instead of re-reading the whole history every tick. |
| Orders rejected | The Notes say why. RULES.md, section 6 lists every reason. |
| 0 trades, no rejects and no errors (and the upload test passes) | `on_tick` returns nothing: check that it ends with `return actions`. Returning `None` is allowed (it means "do nothing"), so nothing warns you. |
| Your orders never fill | Your prices aren't competitive: a resting order only fills when it is the best price on its side (section 3). Check them against `best_bid` and `best_ask`. |
| `buy_now` or `sell_now` sometimes trades nothing | When your order went in, nothing was on offer within $1 of the best price you saw (the other bots' cancels go first). `state.cancelled` shows it next tick, with the reason `"ioc"`. |
| Rejects with `bad_action` at index 0 | `on_tick` returned something that isn't a list of actions: a string, a number, or a set (`{...}`) instead of a list (`[...]`). |
| An `.algoday` replay opens as text in VS Code, or you have no VS Code | The replay viewer isn't in this VS Code yet: run `python run_local.py --vscode`, then close VS Code and open it again (README.md, section 6, has more). Or skip VS Code: drop the file on the **Replays** tab of the competition website (section 2). |

**A virtual environment** gives the bots their own copy of numpy. In the
starter folder, on Windows:

```
python -m venv .venv
.venv\Scripts\python -m pip install numpy
.venv\Scripts\python run_local.py
```

On macOS and Linux:

```
python3 -m venv .venv
.venv/bin/python -m pip install numpy
.venv/bin/python run_local.py
```

Then always start `run_local.py` with that Python.

## 13. Cheat sheet

### `state` (dollars)

| | |
|---|---|
| `state.tick`, `state.ticks`, `state.ticks_left` | this tick (0 to 999), the number of ticks, the ticks after this one (0 on the last tick) |
| `state.assets` | the assets in this round |
| `state.info` | the match info: `["round"]`, `["description"]`, `["hint_sources"]` (each with its `"noise"`, the error sd in dollars), `["limits"]`, `["start_prices"]`, `["participants"]` |
| `state.limits` | `["position_limit"]`, `["max_order_qty"]`, `["max_open_orders"]`, `["max_actions_per_tick"]` |
| `state.cash` | your cash |
| `state.position(asset)`, `state.positions` | your position in one asset, or all of them as a dict |
| `state.book(asset)` | `.bids` and `.asks` (lists of `(price, qty)`, best first, up to 5 levels), `.best_bid`, `.best_ask`, `.mid`, `.spread` (each `None` if a side is empty) |
| `state.hints` | the hints published this tick: each has `.asset`, `.value`, `.source`, `.tick` |
| `state.last_hint(asset)`, `state.last_hint(asset, source)` | the latest hint (optionally from one source), or `None` |
| `state.hint_history(asset)`, `state.hint_history(asset, source)` | every hint so far, oldest first |
| `state.trades` | everyone's trades from the last tick: `.asset`, `.price`, `.qty`, `.aggressor` (`"buy"` or `"sell"`: the side that started it) |
| `state.fills` | your trades from the last tick: `.order_id`, `.asset`, `.side`, `.price`, `.qty`, `.aggressor` (`True` if your order was the incoming one) |
| `state.open_orders` | your resting orders (all assets): `.order_id`, `.asset`, `.side`, `.price`, `.qty` |
| `state.rejects` | your rejected actions from the last tick: `.index` (position in your list), `.reason` |
| `state.cancelled` | your orders the exchange cancelled: `.order_id`, `.asset`, `.qty`, `.reason` (`"ioc"` for the unfilled part of an immediate-or-cancel order, `"self_trade"`) |
| `state.band(asset)` | `(lowest, highest)` price allowed right now |

Top-level variables in your file keep their values for the whole match.
To change a top-level number or string inside `on_tick`, put `global name`
at the top of `on_tick`: without it, `count += 1` raises
`UnboundLocalError`, and `count = 0` only sets a new local variable.
Changing what is inside a top-level dict or list
(`estimates[asset] = value`) needs no `global`. `on_start(info)` runs once
before tick 0 if you define it.

### Actions

`from algomarket import buy, sell, buy_now, sell_now, cancel, cancel_all`

| | |
|---|---|
| `buy(asset, price, qty)`, `sell(asset, price, qty)` | rests in the book until it fills or you cancel it |
| `buy(asset, price, qty, ioc=True)`, `sell(...)` | trades what it can right now at `price` or better; the rest is dropped |
| `buy_now(asset, qty)`, `sell_now(asset, qty)` | trades right now with the orders on offer, at most $1 worse than the best price you saw (`best_ask` for `buy_now`, `best_bid` for `sell_now`); the rest is dropped. `buy_now(asset, qty, max_slippage=0.5)` sets your own limit, in dollars. |
| `cancel(order_id)` | cancels one resting order (an id, or an order from `state.open_orders`) |
| `cancel_all(asset)`, `cancel_all()` | cancels all your resting orders on one asset, or everywhere |

You only learn a new order's id on the next tick (in `state.open_orders` or
`state.fills`), so `cancel_all` is usually simpler.

### `run_local.py`

| | |
|---|---|
| `python run_local.py` | all six samples, Random walk, seed 1 |
| `--bots a.py b.py` | play these bots (plus the house bots) |
| `--round jumps` | `random_walk`, `mean_revert`, `jumps`, `pairs`, `smoke`, or `all` (the four real rounds) |
| `--seed 7`, `--seeds 10` | the first seed, and how many seeds to play |
| `--vscode` | plays nothing: sets up VS Code so a match's `.algoday` file in `out/` plays in a tab |
| `--timeout 0.1` | seconds per tick (0.1, as on the day) |
| `--help` | every option |
