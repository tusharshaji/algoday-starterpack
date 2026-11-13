"""Equity, drawdown, score, ranks and series standings (DESIGN.md section 12,
in the organisers' design notes, which are not in the starter kit).

Money here is dollars (floats). Reported numbers are rounded to cents, and
ranks compare those rounded numbers, so what the room sees on the screen is
exactly what decides the order. Equal rounded scores share a rank
(1, 1, 3). House participants are shown but never ranked.
"""


def money(value):
    """Round to cents; never returns -0.0."""
    return round(float(value), 2) + 0.0


def to_dollars(equity_cents):
    return [value / 100.0 for value in equity_cents]


def pnl(equity):
    """Final equity (everyone starts at 0)."""
    if len(equity) == 0:
        return 0.0
    return float(equity[-1])


def max_drawdown(equity):
    """max over t of peak_t - equity[t], where the peak starts at 0."""
    peak = 0.0
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        drop = peak - value
        if drop > worst:
            worst = drop
    return float(worst)


def score(pnl_value, drawdown, lam):
    return pnl_value - lam * drawdown


def summarize(equity, lam):
    """{"pnl", "max_drawdown", "score"} in dollars, rounded to cents.
    equity: per-tick dollars."""
    final = pnl(equity)
    drawdown = max_drawdown(equity)
    return {"pnl": money(final), "max_drawdown": money(drawdown),
            "score": money(score(final, drawdown, lam))}


def competition_ranks(keys):
    """Ranks for keys where higher is better: 1 = best, ties share a rank."""
    order = sorted(range(len(keys)), key=lambda i: keys[i], reverse=True)
    ranks = [0] * len(keys)
    prev = None
    rank = 0
    for position, i in enumerate(order):
        if position == 0 or keys[i] != prev:
            rank = position + 1
            prev = keys[i]
        ranks[i] = rank
    return ranks


def _score_key(row):
    value = row.get("score")
    if value is None:
        return float("-inf")
    return money(value)


def assign_ranks(results):
    """Copies of the result rows with "rank": teams ranked by score, house None."""
    out = [dict(row) for row in results]
    teams = [row for row in out if row.get("kind") == "team"]
    ranks = competition_ranks([_score_key(row) for row in teams])
    for row in out:
        row["rank"] = None
    for row, rank in zip(teams, ranks):
        row["rank"] = rank
    return out


def series_standings(matches):
    """Overall standings across rounds and seeds.

    matches: [{"round": key, "results": [{"name", "kind", "score", ...}]}].
    Per round a participant's score is its mean over that round's matches;
    teams get n_teams - rank + 1 points per round; overall order is total
    points, then the sum of round mean scores. Returns rows best first,
    house rows last with rank and points None:
    {"name", "kind", "rank", "points", "total_score",
     "rounds": {key: {"mean_score", "matches", "rank", "points"}}}
    """
    round_keys = []
    names = []
    kinds = {}
    scores = {}
    for match in matches:
        key = match["round"]
        if key not in round_keys:
            round_keys.append(key)
        for row in match["results"]:
            name = row["name"]
            if name not in kinds:
                names.append(name)
                kinds[name] = row.get("kind", "team")
            value = row.get("score")
            scores.setdefault((key, name), []).append(0.0 if value is None else float(value))

    rows = {}
    for name in names:
        is_team = kinds[name] == "team"
        rows[name] = {"name": name, "kind": kinds[name], "rank": None,
                      "points": 0 if is_team else None, "total_score": 0.0, "rounds": {}}

    for key in round_keys:
        played = [name for name in names if (key, name) in scores]
        teams = [name for name in played if kinds[name] == "team"]
        means = {}
        for name in played:
            values = scores[(key, name)]
            means[name] = money(sum(values) / len(values))
        ranks = competition_ranks([means[name] for name in teams])
        team_rank = dict(zip(teams, ranks))
        for name in played:
            row = rows[name]
            entry = {"mean_score": means[name], "matches": len(scores[(key, name)]),
                     "rank": None, "points": None}
            if name in team_rank:
                entry["rank"] = team_rank[name]
                entry["points"] = len(teams) - team_rank[name] + 1
                row["points"] += entry["points"]
            row["total_score"] = money(row["total_score"] + means[name])
            row["rounds"][key] = entry

    team_rows = [rows[name] for name in names if kinds[name] == "team"]
    house_rows = [rows[name] for name in names if kinds[name] != "team"]
    ranks = competition_ranks([(row["points"], row["total_score"]) for row in team_rows])
    for row, rank in zip(team_rows, ranks):
        row["rank"] = rank
    team_rows.sort(key=lambda row: row["rank"])
    return team_rows + house_rows
