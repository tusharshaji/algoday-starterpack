# AlgoDay Market: starter kit

You write a trading bot in Python. On the day, every team's bot trades in
one simulated market, against the other teams and a few house bots. This
kit lets you build and test your bot on your own computer first, on the
same market simulator the day runs on.

You don't need to know any finance. If you can write a Python function, you
can play.

**Already have Python 3.12 or newer, and happy in a terminal?**

```
git clone https://github.com/tusharshaji/algoday-starterpack.git
cd algoday-starterpack
python -m pip install numpy
python run_local.py --bots strategy.py
```

(On a Mac, type `python3` for `python`.) That plays the example bot against
the house bots. Everyone else: follow
[Set up](#set-up-about-5-minutes) below, one step at a time. It takes about
5 minutes.

## Contents

- [The game in one minute](#the-game-in-one-minute)
- [Set up](#set-up-about-5-minutes): Python, the kit, your first match
- [Make your bot](#make-your-bot)
- [Read the results](#read-the-results)
- [The rules](#the-rules): rounds, limits, scoring, how the day runs
- [How to win](#how-to-win)
- [Upload](#upload)
- [If something goes wrong](#if-something-goes-wrong)
- [What's in the kit](#whats-in-the-kit)
- [Cheat sheet](#cheat-sheet)

## The game in one minute

```text
                 state: hints, the order book, your cash and position
   the market  --------------------------------------------------->  your bot
  1,000 ticks  <---------------------------------------------------  on_tick(state)
                 your orders: buy, sell, cancel
```

- Your bot is one Python file, `strategy.py`, with a function
  `on_tick(state)`.
- A match lasts **1,000 ticks**. Every tick, the market calls `on_tick` and
  your bot answers with a list of orders: offers to buy or sell.
- Each asset (DEVS, say) has a hidden **true value**. No bot can see it
  during the match.
- Every bot gets the same **hints**: estimates of the true value, each one
  off by a random amount.
- After the last tick, everything you hold is **cashed in at the true
  value**.
- **Score = profit - half of your biggest drop** along the way.

So the whole game is: **buy below the true value, sell above it, and don't
take big risks.**

Where does the profit come from? All the profits and losses in a match add
up to exactly $0. The house noise traders buy and sell at random and lose
money on purpose, and the house market maker is a bit slow. Your profit
comes from them, and from teams that trade worse than you.

There are four rounds, each a different kind of market, and your one bot
plays all of them. [The rules](#the-rules) has them.

## Set up (about 5 minutes)

**1. Get the kit.**

Already reading this inside the kit folder? You have it: go to step 2.
Otherwise pick one:

- **From GitHub:** on this repository's page, click the green **Code**
  button, then **Download ZIP**.
- **From the competition site:** the **Starter pack** button on the Submit
  page.
- **With git:** `git clone https://github.com/tusharshaji/algoday-starterpack.git`
  (nothing to unzip).

Unzip it:

- Windows: right-click the zip, choose **Extract All**, then **Extract**.
  Don't work inside the zip window: Python can't run files from there.
- Mac: double-click the zip.

Open folders until you see `run_local.py` and `strategy.py`: that's the kit
folder.

**2. Check you have Python 3.12 or newer.**

- Windows: open PowerShell and type `python --version`
- Mac: open Terminal and type `python3 --version`

If it says 3.12 or higher, go to step 3. If not (or it says "not found", or
the Microsoft Store opens, or a Mac asks to install developer tools), install
Python from <https://www.python.org/downloads/>. On Windows, tick **Add
python.exe to PATH** on the installer's first screen. Then close the
terminal and open a new one.

**3. Open a terminal in the kit folder.**

- Windows 11: open the folder in File Explorer, right-click an empty spot and
  choose **Open in Terminal**. (Windows 10: click the address bar, type
  `powershell` and press Enter.)
- Mac: open Terminal, type `cd ` (with a space after it), drag the kit folder
  onto the Terminal window, press Enter.
- Or open the folder in VS Code (**File > Open Folder**) and use
  **Terminal > New Terminal**.

**4. Install numpy and play your first match.**

Windows:

```
python -m pip install numpy
python run_local.py
```

Mac:

```
python3 -m pip install numpy
python3 run_local.py
```

You should see a results table for the sample bots, then a line like
`Replay: out\random_walk_seed1.algoday`. That file is the match, saved so
you can watch it.

From here on we write `python`. On a Mac, type `python3` instead.

**5. Add the replay viewer to VS Code and watch the match.**

Replays play in a tab in VS Code (a free code editor:
<https://code.visualstudio.com/>). The kit comes with a replay viewer for
it. Add it once:

```
python run_local.py --vscode
```

It should print `VS Code: installed.` Now open the kit folder in VS Code
(**File > Open Folder**), open `out` in the file list and click
`random_walk_seed1.algoday`. The match opens in a tab: click it and press
the space bar to play.

No VS Code, or the viewer won't install? You can still watch: open the
competition site, go to its **Replays** tab and drop the `.algoday` file
there. It plays in your browser, and the file is not uploaded.

You're set up. Everything from here is the fun part.

## Make your bot

Your bot is `strategy.py`. Open it in an editor (VS Code with its Python
extension is a good choice). It already works: it's a small market maker
that quotes around the latest hints. Against the sample bots it makes money
on average in every round (about $25 to $67 a match), but only while few
teams run it: when several teams upload it unchanged, they can all score
below 0 in Jumps (`docs/GUIDE.md`, section 11, says why and how to fix it).
Read the comments at the top, then make it your own. (Rather start from a
blank file? `docs/GUIDE.md` builds bots step by step in new files. Whatever
single file you upload is saved as `strategy.py`.)

### The shape of every bot

```python
from algomarket import buy, sell, cancel_all


def on_tick(state):
    actions = []
    for asset in state.assets:                  # e.g. ["DEVS"]
        hint = state.last_hint(asset)           # the latest estimate of the true value
        if hint is None:
            continue                            # nothing to go on yet
        actions.append(cancel_all(asset))       # take down last tick's orders
        actions.append(buy(asset, round(hint.value - 0.50, 2), 2))    # buy 2, 50 cents below
        actions.append(sell(asset, round(hint.value + 0.50, 2), 2))   # sell 2, 50 cents above
    return actions
```

Every tick: look at `state`, decide, return a list of actions. That's it.
The rest is making the decision smarter.

This one is only the shape, and it loses money: it trusts one noisy hint
and never minds what it holds, so it piles up a position until its orders
are rejected. `strategy.py` fixes both: it averages the last few hints and
leans against what it holds.

### What your bot can read

| | |
|---|---|
| `state.tick`, `state.ticks_left` | where we are in the match (ticks 0 to 999) |
| `state.assets` | what this round trades, e.g. `["DEVS"]` |
| `state.info["round"]` | which round this is: `random_walk`, `mean_revert`, `jumps` or `pairs` |
| `state.last_hint(asset).value` | the latest estimate of the true value |
| `state.hint_history(asset)` | every hint so far, oldest first |
| `state.book(asset).best_bid` | the highest price someone will pay right now |
| `state.book(asset).best_ask` | the lowest price someone will sell at right now |
| `state.position(asset)`, `state.cash` | what you hold (negative = short) and your cash |
| `state.limits["position_limit"]` | the most units you may hold, long or short |
| `state.fills`, `state.rejects` | your trades and your refused orders, from the last tick |

`last_hint`, `best_bid` and `best_ask` are `None` when there is nothing yet:
check before you use them.

### What your bot can do

Return a list of these (import them with `from algomarket import ...`):

| | |
|---|---|
| `buy(asset, price, qty)` | offer to buy; it stays in the book until it's filled or you cancel it |
| `sell(asset, price, qty)` | offer to sell |
| `buy_now(asset, qty)` | buy right away, paying at most $1 above the best ask |
| `sell_now(asset, qty)` | sell right away, at most $1 below the best bid |
| `cancel(order_id)`, `cancel_all(asset)` | take orders out of the book |

### Play it

Against the house bots:

```
python run_local.py --bots strategy.py
```

Against some sample bots too:

```
python run_local.py --bots strategy.py bots/simple_market_maker.py bots/hint_follower.py
```

In other rounds, and on several seeds (one match can be lucky or unlucky):

```
python run_local.py --round mean_revert --bots strategy.py
python run_local.py --round all --seeds 3 --bots strategy.py bots/kalman_market_maker.py
```

| Round | Traded | |
|---|---|---|
| `random_walk` | DEVS | the default |
| `mean_revert` | TRV | |
| `jumps` | SESA | |
| `pairs` | WDCC and UOA | two assets that move together |
| `smoke` | DEVS | 200 ticks: the upload test's match |

Each round's rules are in `info["description"]` (strategy.py prints it to its
log). `python run_local.py --help` lists every option.

### Good to know

- Your bot runs in its own process for the whole match, so variables at the
  top of your file keep their values from one tick to the next. To change
  one inside `on_tick` (`count += 1`), first write `global count` at the top
  of `on_tick`, or Python stops with `UnboundLocalError`. Changing what is
  inside a top-level dict or list needs no `global`: with `memory = {}` at
  the top, `memory["count"] = 1` in `on_tick` just works.
- `print()` goes to your bot's log file in `out/logs/`, never to the screen.
- Stick to the Python standard library and numpy: they're all the match
  computer has. It runs Python 3.12.
- The full guide, with bots built step by step, is `docs/GUIDE.md`. Every
  rule in detail is `docs/RULES.md`. The sample bots in `bots/` each explain
  their idea at the top.

## Read the results

A match prints a table like this:

```text
  rank  bot            status      pnl $   max dd $    score $  trades
     1  strategy       ok          70.07      11.43      64.35     234
     -  house-mm       house      399.76     104.79     347.37     909
     -  house-noise-1  house     -160.25     160.25    -240.38     388
```

| Column | Means |
|---|---|
| `rank` | your place among the teams' bots (house bots are shown but not ranked: `-`) |
| `status` | `ok`, or what stopped your bot: `crashed`, `timeout` or `disqualified`, with the reason |
| `pnl $` | profit and loss: what you ended with (everyone starts at $0) |
| `max dd $` | max drawdown: your biggest fall from a high point |
| `score $` | `pnl - lambda x max drawdown`, with lambda = 0.5: here 70.07 - 0.5 x 11.43 = **64.35** |
| `trades` | how many trades you made |

`do_nothing` always scores 0: beat it.

- **Several matches** (`--round all` or `--seeds`) end with **Overall
  standings**: points per round, just like the day (see
  [Scoring](#scoring)).
- **Notes under the table.** Lines starting with `!!` or `!` mean a bot
  crashed, raised an error or was too slow. The first error in its log (in
  full: file, line and message) and the last lines of its log are printed
  under them.
- **Logs.** Everything your bot prints, and any error message, goes to its
  log in `out/logs/` (one folder per match, one file per bot).
- **The replay.** Each match is saved as one `.algoday` file in `out/`
  (`run_local.py` prints its name). Click it in VS Code and it plays in a
  tab (step 5 set that up; it works in Cursor and VSCodium too). Play the
  same match again and the tab reloads. Keys, once you have clicked the
  replay: space play/pause, left/right step, 1-4 speed, V show the true
  value.
- **The replay without VS Code.** Drop the `.algoday` file on the
  **Replays** tab of the competition site. It plays in your browser, and
  the file is not uploaded.

## The rules

The short version. Every detail is in `docs/RULES.md`.

### The rounds

| Round | Asset | Position limit | What the true value does | Hints (typical error) |
|---|---|---|---|---|
| Random walk (`random_walk`) | DEVS | 50 | wanders up and down at random, starting near $100 | analyst: every 5 ticks ($0.40) |
| Mean reversion (`mean_revert`) | TRV | 50 | gets pulled back toward $100: usually within about $1.50 of it | analyst: every 5 ticks ($0.80) |
| Jumps (`jumps`) | SESA | **20** | drifts gently near $100, but jumps by a few dollars several times a match | insider ($0.10, rare), rumour ($0.80, often; about 1 in 20 is way off), newswire ($0.25, on the tick of a jump) |
| Pairs (`pairs`) | WDCC and UOA | 50 each | WDCC wanders near $100; UOA is about half of WDCC, near $50 | WDCC every 4 ticks ($0.30); UOA every 8 ticks ($0.50) |

The typical error is the hint's standard deviation: with $0.40, about 2
hints in 3 are within $0.40 of the true value.

The same in every round: 1,000 ticks; you start with $0 cash and nothing
held; your cash may go below $0 and you may sell what you don't have (go
**short**); no fees; every asset gets a hint at tick 0. Every match also has
the **house bots**: `house-mm`, a market maker that is deliberately a bit
slow, and `house-noise-1` to `-3`, which trade at random.

### Limits

| | Limit |
|---|---|
| Position | -50 to +50 units per asset (Jumps: -20 to +20). Your resting orders count toward it. |
| Order size | 1 to 10 units, whole numbers |
| Resting orders | 10 per asset |
| Actions per tick | 20 (buys, sells and cancels together) |
| Prices | within 20% of the latest hint (`state.band(asset)` gives the range) |
| Time per tick | 100 ms (0.1 seconds) |
| Thinking time | 10 seconds per match, all ticks together (about 10 ms a tick) |
| Starting up | 15 seconds to import your file and run `on_start` |
| Memory | 1 GB |
| Your log | 2 MB per match |

An order that breaks a rule is **rejected**: it is skipped, the rest of your
list still goes ahead, and there is no fine. Next tick, `state.rejects` says
why.

### How a tick works

1. The new hints are published.
2. Every bot gets its `state` at the same moment and has 100 ms to answer.
3. **Cancels first:** every bot's cancels happen before any new order.
4. **Then new orders**, bot by bot in a random order, shuffled every tick
   (the house noise traders always go last).
5. A trade happens at the price of the order that was already resting in the
   book. You hear about your trades next tick, in `state.fills`.

After tick 999, every order is cancelled and everything you hold is cashed
in at the true value.

### When your bot goes wrong

| What happens | What it costs |
|---|---|
| `on_tick` raises an error | that tick's orders are lost; more than 100 in a match and your bot is stopped (`disqualified`) |
| `on_tick` takes longer than 100 ms | that tick's orders are lost; more than 20 in a match and your bot is stopped (`timeout`) |
| your bot uses up its 10 seconds of thinking time | it is stopped (`timeout`) |
| your file won't import (a syntax error, a missing module, no `on_tick`) | it never starts (`crashed`) and scores $0 |

A stopped bot can't trade again in that match, but it keeps what it holds to
the end. The next match starts it fresh.

### Scoring

At every tick, your **equity** is your cash plus what you hold, valued at
the true value.

- **PnL** (profit and loss) is your equity at the end.
- **Max drawdown** is the biggest drop of your equity below its highest
  point so far (the starting $0 counts as a high point).
- **Score = PnL - 0.5 x max drawdown.**

Example: your equity climbs to $80, falls to $30, climbs to $120 and ends at
$100. PnL = $100, max drawdown = $50 (from $80 down to $30), so the score is
100 - 0.5 x 50 = **$75**. The same $100 with no drop bigger than $10 would
score $95. Smooth gains beat wild swings.

**Who wins.** Each round is ranked on its own: your score for a round is
your **average** over that round's matches. Each round gives **points =
number of teams - place + 1** (with 10 teams, 1st gets 10 points and 10th
gets 1). The most points in total wins. A tie goes to the higher total of
round averages. Every round counts the same, whatever its scores look like.

Example with 8 teams: 2nd in Random walk (7 points), 5th in Mean reversion
(4), 1st in Jumps (8) and 3rd in Pairs (6) = 25 points.

### How the day runs

1. **Join code.** Each team gets one at the start. It's your key on the
   Submit page: don't share it.
2. **Upload** your bot on the competition site whenever you like.
3. **The upload test.** Each upload plays 200 ticks of Random walk, alone
   with the house bots. It passes if your bot starts, never raises an error
   in `on_tick`, misses the 100 ms limit on at most 4 ticks and stays within
   2 seconds of thinking time. A passing upload becomes your team's bot. A
   failed one never replaces your last passing one. After a pass, the test
   also plays 100 ticks of each round: those can only add warnings, but a
   warning there means your bot will likely fail that round in every match,
   so fix it.
4. **Scrimmages.** About every 10 minutes, every team's current bot plays
   one match in each open round, with the house bots, on fresh seeds. The
   replays play on the projector, the board shows the latest standings, and
   every past scrimmage is on the site's **Replays** tab. Scrimmages are
   practice: they don't count. Rounds may open one at a time during the
   day.
5. **The deadline.** Your **final bot** is your newest upload that passed
   its test before the deadline. Near the end the board may be frozen or
   hidden, to keep the final a surprise.
6. **The final.** Every round x 32 secret seeds = **128 matches**, every
   team in every match. Standings as in [Scoring](#scoring). The results are
   revealed on the projector, round by round.
7. **Afterwards**, the final's seeds are published, so you can replay those
   markets yourself.

### Fair play

- **Write your own bot.** Use and change the sample bots and anything in
  the guide. Talking ideas with other teams is fine; sharing code isn't.
- **No collusion.** Your bot trades for your team only: no passing profit to
  another team, no going easy on each other.
- **Hands off the machinery.** Your bot may read its state, think, print
  and return actions. It must not use the network, open or write files
  (importing your own `.py` files is fine), start processes or threads, try
  to find the seed, the true value or other teams' code, or try to slow
  down or crash anything.
- **Found a bug?** Tell the organisers. Don't use it.
- **We check.** Every trade is in the replays, trades between teams far from
  the true value are flagged automatically, and the organisers can read
  every bot's code. Reading the simulator code in this kit is allowed.

## How to win

### What decides it

- **Four rounds, equal points.** A bot that's solid in all four rounds beats
  one that's brilliant in one and broken in another. A round where your bot
  crashes or loses money costs you a lot of points.
- **Averages over 32 matches.** Luck evens out in the final. A steady bot
  beats a lucky one.
- **Drawdown counts half.** Steady profit beats wild swings.

### Ten habits of winning teams

1. **Upload a working bot early.** A passing upload is your safety net (a
   failed upload never replaces it) and puts you in every scrimmage. Then
   improve it and upload again.
2. **Beat $0 in every round.** `do_nothing` scores exactly $0. If your bot
   loses money in a round, it would do better sitting still there. Your bot
   knows the round (`state.info["round"]`): trade less in a round you
   haven't cracked yet, and fix it later.
3. **Estimate the true value better than everyone else.** This matters
   most. One hint is noisy: combine several, and give recent ones more
   weight (a moving average, or the Kalman filter in
   `bots/kalman_market_maker.py`). A better estimate lets you quote closer
   to the value without losing money.
4. **Keep positions small.** Big positions mean big swings, and swings cost
   drawdown. Lean against what you hold: when you own a lot, quote lower so
   you sell more (the starter's `SKEW` does this).
5. **React the tick the news arrives.** Cancels happen before new orders, so
   a bot that moves its quotes as soon as a hint lands never gets caught on
   an old price. A slow bot does: that's the house market maker's weak
   spot.
6. **Doubt odd hints, trust precise ones.** In Jumps, about 1 rumour in 20
   is several dollars off, and the insider is rare but precise. A median
   shrugs off one wild hint; an average doesn't.
7. **Don't be a copy.** If several teams upload the starter unchanged, they
   can all score below 0 in Jumps: one wild rumour moves every copy the same
   way at once. Change it.
8. **Test like it's the final.** Many seeds (`--seeds 20`), seeds you didn't
   tune on (`--seed 101 --seeds 20`), every round (`--round all`), and a
   tough field: add a strong sample twice,
   `--bots strategy.py bots/kalman_market_maker.py bots/kalman_market_maker.py`.
9. **Never crash, never stall.** Check for `None` before you use
   `last_hint`, `best_bid` or `best_ask`. Keep `on_tick` quick: keep running
   totals instead of looping over the whole history every tick.
10. **Watch the replays.** Your own, to see where you lose money (press V to
    show the true value). And the scrimmages, to see how other teams trade:
    a replay shows its seed at the top, and
    `python run_local.py --round jumps --seed <seed> --bots strategy.py`
    rebuilds that market on your laptop (without the other teams).

**A good target:** beat `bots/kalman_market_maker.py` on 20 or more fresh
seeds in every round.

### Round by round

| Round | Ideas |
|---|---|
| Random walk (DEVS) | The value keeps moving, so old hints go stale: weight recent hints more. Trade against the slow house market maker right after each hint. |
| Mean reversion (TRV) | TRV is pulled back to $100 (a gap halves in about 40 ticks). When a hint says $101.60, the truth is probably a bit closer to $100. Trading toward $100 pays, but prices can stay away for a while: watch your drawdown. |
| Jumps (SESA) | The newswire fires on the very tick of a jump, with the new value: pull your quotes and follow it at once. Doubt rumours, listen to the insider. The position limit is 20: a $3 jump on 20 units is $60. |
| Pairs (WDCC and UOA) | UOA = 0.5 x WDCC + a small gap that's pulled back to $0. WDCC's hints are more precise and twice as frequent, so price UOA from WDCC. Hedge: holding +10 UOA with -5 WDCC cancels most of the risk. See `bots/pairs_trader.py`. |

`docs/GUIDE.md`, section 11, goes deeper on each round.

## Upload

Upload `strategy.py` on the competition site (the Submit page, with your
join code), plus any helper `.py` files it imports (keep them next to it).
Don't upload `algomarket/`, `bots/` or `out/`.

Each upload first gets a quick test match: your bot alone with the house bots
for 200 ticks of Random walk. It fails if your bot crashes, raises an error
in `on_tick` or is too slow (per tick or overall). Play the same match
yourself before you upload:

```
python run_local.py --round smoke --seed 0 --bots strategy.py
```

If no `!!` or `!` notes appear, you're good. After a pass, the test also
plays 100 ticks of every round, as a check. That can't fail your upload, but
if your bot raises an error or is stopped in a round, the upload page warns
you, with the error and its line. So also try every round before you upload:

```
python run_local.py --round all --bots strategy.py
```

Before every upload:

- [ ] the upload test (`--round smoke --seed 0`) shows no `!!` or `!` notes
- [ ] every round (`--round all`) shows no notes
- [ ] only the standard library and numpy are imported
- [ ] any helper files go up with `strategy.py`

## If something goes wrong

| What you see | What to do |
|---|---|
| `python` is not found, or the Microsoft Store opens | Install Python from python.org with **Add python.exe to PATH** ticked, then open a new terminal. Or type `py` instead of `python`. |
| `No module named 'numpy'` | Run the `pip install numpy` line again with the same word you use to run (`python`, `py` or `python3`). |
| Mac: `externally-managed-environment` | Make a virtual environment once: `python3 -m venv .venv`, then `source .venv/bin/activate`, then `python -m pip install numpy`. Run `source .venv/bin/activate` again in every new terminal. |
| `can't open file ... run_local.py` | The terminal is in the wrong folder. Go to the folder that has `run_local.py` in it (step 3). |
| `python strategy.py` does nothing | That's normal: `run_local.py` runs your bot. |
| Your bot's log says `No module named ...` | Bots run with the same Python as `run_local.py`: install the package for that one (the `pip install` line, with the same word you use to run). Only the standard library and numpy are on the match computer, so anything else fails there. |
| `engine: python` at the end of the output | That's fine. The kit uses a fast compiled order book when your computer can load it and a pure-Python one otherwise. The results are exactly the same. |
| `--vscode` can't find VS Code | Add it by hand: in VS Code open the Extensions view (the four squares on the left), click the `...` at its top, choose **Install from VSIX...** and pick `viewer/algoday-replay.vsix` in the kit folder. |
| An `.algoday` file opens as text, or VS Code says it can't show it | The replay viewer isn't in this VS Code yet: run `python run_local.py --vscode`, then close VS Code and open it again. Still the same (for example you use a VS Code profile)? Add it by hand, as in the row above. |
| You don't have VS Code, or the replay viewer won't install | You don't need it to watch a match: drop the `.algoday` file on the **Replays** tab of the competition site. It plays in your browser, and the file is not uploaded. |
| It works on your laptop but the upload test fails | Read the reason and the log on the upload page. Usually: a helper file that wasn't uploaded, a library that isn't installed there, or a bot close to the time limits (the match laptop may be slower than yours). |

## What's in the kit

| | |
|---|---|
| `strategy.py` | your bot: edit this and upload it |
| `run_local.py` | plays matches on your computer |
| `bots/` | sample bots, each with its idea explained at the top: `do_nothing` (the baseline, always 0), `random_trader` (loses, on purpose), `hint_follower`, `simple_market_maker`, `kalman_market_maker`, `pairs_trader` (for the pairs round) |
| `docs/GUIDE.md` | the full guide: build bots step by step, then ideas round by round |
| `docs/RULES.md` | every rule, in detail |
| `algomarket/` | the market simulator, the same one used on the day. Your bot imports `buy`, `sell` and so on from it; you don't need to change it |
| `viewer/` | the replay player, and the replay viewer for VS Code (`algoday-replay.vsix`) |
| `out/` | made when you play: replays (`.algoday` files) and logs |
| `.gitignore` | tells git to skip `out/` (only matters if you use git) |

Got the kit with git? `git pull` gets the latest version (commit your own
changes first). Downloaded a zip? Download it again and copy your
`strategy.py` (and any helpers) across.

## Cheat sheet

| Command | Does |
|---|---|
| `python run_local.py` | all the sample bots, one match of Random walk |
| `python run_local.py --bots strategy.py` | your bot against the house bots |
| `python run_local.py --bots strategy.py bots/hint_follower.py` | your bot against a sample bot too |
| `python run_local.py --round jumps --bots strategy.py` | another round (`random_walk`, `mean_revert`, `jumps`, `pairs`, `smoke`) |
| `python run_local.py --round all --seeds 20 --bots strategy.py` | every round, 20 seeds each, with overall standings |
| `python run_local.py --seed 101 --seeds 20 --bots strategy.py` | seeds 101 to 120 (fresh ones you didn't tune on) |
| `python run_local.py --round smoke --seed 0 --bots strategy.py` | the upload test's match |
| `python run_local.py --vscode` | add the replay viewer to VS Code |
| `python run_local.py --help` | every option |
