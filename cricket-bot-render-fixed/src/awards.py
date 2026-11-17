"""Match awards computed from the finished innings snapshots."""

from __future__ import annotations

from html import escape


def strike_rate(runs: int, balls: int) -> float:
    return runs * 100 / balls if balls else 0.0


def economy(runs: int, balls: int) -> float:
    return runs * 6 / balls if balls else 0.0


def overs_text(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def batting_points(batter: dict) -> float:
    points = batter["runs"] + batter["fours"] + 2 * batter["sixes"]
    if batter["balls"] >= 10:
        points += max(-3.0, min(8.0, (strike_rate(batter["runs"], batter["balls"]) - 100) / 10))
    return points


def bowling_points(bowling: dict) -> float:
    points = bowling["wickets"] * 22.0
    if bowling["balls"] >= 6:
        overs = bowling["balls"] / 6
        points += (8.0 - economy(bowling["runs"], bowling["balls"])) * overs * 1.5
    return points


def compute_awards(innings: list[dict], winner_side: str | None) -> dict:
    """Return the awards for a finished match.

    `innings` is a list of snapshots, each with `side`, `team`, `batters` (name, runs,
    balls, fours, sixes, out) and `bowlers` ({name: {balls, runs, wickets}}).
    Every award is None when nobody qualifies.
    """
    batters: list[dict] = []
    bowlers: list[dict] = []
    for item in innings:
        fielding_team = next((other["team"] for other in innings if other["side"] != item["side"]), "")
        for batter in item.get("batters", []):
            if batter["balls"] or batter["out"]:
                batters.append({**batter, "side": item["side"], "team": item["team"]})
        for name, bowling in (item.get("bowlers") or {}).items():
            if bowling["balls"]:
                other_side = next((o["side"] for o in innings if o["side"] != item["side"]), None)
                bowlers.append({"name": name, **bowling, "side": other_side, "team": fielding_team})

    # ---- Player of the match: best combined batting + bowling impact.
    impact: dict[str, dict] = {}
    for batter in batters:
        entry = impact.setdefault(batter["name"], {"name": batter["name"], "side": batter["side"], "team": batter["team"], "points": 0.0, "bat": None, "bowl": None})
        entry["points"] += batting_points(batter)
        entry["bat"] = batter
    for bowling in bowlers:
        entry = impact.setdefault(bowling["name"], {"name": bowling["name"], "side": bowling["side"], "team": bowling["team"], "points": 0.0, "bat": None, "bowl": None})
        entry["points"] += bowling_points(bowling)
        entry["bowl"] = bowling
    for entry in impact.values():
        if winner_side and entry["side"] == winner_side:
            entry["points"] *= 1.1
    potm = None
    if impact:
        best = max(impact.values(), key=lambda e: (e["points"], e["name"]))
        parts = []
        if best["bat"]:
            parts.append(f"{best['bat']['runs']}({best['bat']['balls']})")
        if best["bowl"]:
            parts.append(f"{best['bowl']['wickets']}/{best['bowl']['runs']}")
        potm = {
            "name": best["name"], "side": best["side"], "team": best["team"],
            "points": round(best["points"], 1), "summary": " & ".join(parts),
        }

    # ---- Category awards.
    best_batter = max(batters, key=lambda b: (b["runs"], strike_rate(b["runs"], b["balls"])), default=None)
    if best_batter and best_batter["runs"] <= 0:
        best_batter = None

    best_bowler = None
    if bowlers:
        best_bowler = max(
            bowlers,
            key=lambda b: (b["wickets"], -b["runs"], b["balls"]),
        )
        if best_bowler["wickets"] == 0:
            qualified = [b for b in bowlers if b["balls"] >= 6]
            best_bowler = min(qualified, key=lambda b: economy(b["runs"], b["balls"]), default=None)

    fast = [b for b in batters if b["balls"] >= 10 and b["runs"] >= 15]
    best_strike_rate = max(fast, key=lambda b: strike_rate(b["runs"], b["balls"]), default=None)

    six_hitter = max((b for b in batters if b["sixes"] > 0), key=lambda b: (b["sixes"], b["runs"]), default=None)

    thrifty = [b for b in bowlers if b["balls"] >= 6]
    best_economy = min(thrifty, key=lambda b: (economy(b["runs"], b["balls"]), -b["wickets"]), default=None)

    partnerships = [
        {**item["best_partnership"], "team": item["team"]}
        for item in innings
        if item.get("best_partnership")
    ]
    best_partnership = max(partnerships, key=lambda p: p["runs"], default=None)

    return {
        "potm": potm,
        "best_batter": best_batter,
        "best_bowler": best_bowler,
        "best_strike_rate": best_strike_rate,
        "most_sixes": six_hitter,
        "best_economy": best_economy,
        "best_partnership": best_partnership,
    }


def format_awards_message(awards: dict, result_text: str) -> str:
    """The separate 'awards' message sent when a match ends (HTML)."""
    lines = [
        "🏆 <b>MATCH AWARDS</b>",
        f"🏁 <i>{escape(result_text)}</i>",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ]
    potm = awards.get("potm")
    if potm:
        lines += [
            "🌟 <b>PLAYER OF THE MATCH</b>",
            f"👑 <b>{escape(potm['name'])}</b>  ·  {escape(potm['team'])}",
            f"📊 {escape(potm['summary'])}" if potm["summary"] else "",
            "",
        ]
    batter = awards.get("best_batter")
    if batter:
        lines.append(
            f"🏏 <b>Best Batter:</b> {escape(batter['name'])} — "
            f"<b>{batter['runs']}</b> ({batter['balls']}) · SR {strike_rate(batter['runs'], batter['balls']):.1f}"
        )
    bowler = awards.get("best_bowler")
    if bowler:
        lines.append(
            f"🎳 <b>Best Bowler:</b> {escape(bowler['name'])} — "
            f"<b>{bowler['wickets']}/{bowler['runs']}</b> ({overs_text(bowler['balls'])} ov)"
        )
    rate = awards.get("best_strike_rate")
    if rate:
        lines.append(
            f"⚡ <b>Best Strike Rate:</b> {escape(rate['name'])} — "
            f"<b>{strike_rate(rate['runs'], rate['balls']):.1f}</b> ({rate['runs']} off {rate['balls']})"
        )
    sixes = awards.get("most_sixes")
    if sixes:
        lines.append(f"💥 <b>Most Sixes:</b> {escape(sixes['name'])} — <b>{sixes['sixes']}</b>")
    thrifty = awards.get("best_economy")
    if thrifty:
        lines.append(
            f"🧱 <b>Best Economy:</b> {escape(thrifty['name'])} — "
            f"<b>{economy(thrifty['runs'], thrifty['balls']):.2f}</b> ({thrifty['runs']} off {overs_text(thrifty['balls'])})"
        )
    partnership = awards.get("best_partnership")
    if partnership:
        lines.append(
            f"🤝 <b>Best Partnership:</b> {escape(partnership['pair'][0])} &amp; "
            f"{escape(partnership['pair'][1])} — <b>{partnership['runs']}</b> ({partnership['balls']})"
        )
    return "\n".join(line for line in lines if line is not None).replace("\n\n\n", "\n\n")
