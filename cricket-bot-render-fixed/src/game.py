"""Cricket match engine: ball-by-ball outcome simulation."""

import random

OUTCOMES = ("wicket", "dot", "one", "two", "four", "six")
OUTCOME_RUNS = {"wicket": 0, "dot": 0, "one": 1, "two": 2, "four": 4, "six": 6}

# Multipliers applied to the base outcome weights.
BATTING_STYLES = {
    "aggressive": {"label": "Aggressive", "mods": {"wicket": 1.25, "dot": 0.8, "one": 0.9, "two": 1.0, "four": 1.35, "six": 1.4}},
    "defensive": {"label": "Defensive", "mods": {"wicket": 0.6, "dot": 1.35, "one": 1.0, "two": 0.9, "four": 0.6, "six": 0.4}},
    "ultra": {"label": "Ultra aggressive", "mods": {"wicket": 1.7, "dot": 0.7, "one": 0.7, "two": 0.9, "four": 1.6, "six": 2.2}},
    "gaps": {"label": "Hit gaps", "mods": {"wicket": 0.9, "dot": 0.8, "one": 1.2, "two": 1.4, "four": 1.3, "six": 0.6}},
    "rotate": {"label": "Rotate strike", "mods": {"wicket": 0.8, "dot": 0.7, "one": 1.6, "two": 1.3, "four": 0.7, "six": 0.5}},
}
BOWLING_STYLES = {
    "aggressive": {"label": "Aggressive", "mods": {"wicket": 1.4, "dot": 1.0, "one": 0.9, "two": 0.9, "four": 1.15, "six": 1.1}},
    "defensive": {"label": "Defensive", "mods": {"wicket": 0.7, "dot": 1.3, "one": 1.1, "two": 0.9, "four": 0.8, "six": 0.7}},
    "variation": {"label": "Variation", "mods": {"wicket": 1.15, "dot": 1.15, "one": 1.0, "two": 1.0, "four": 0.95, "six": 0.95}},
    "knuckle": {"label": "Knuckle ball", "mods": {"wicket": 1.2, "dot": 1.25, "one": 1.0, "two": 0.95, "four": 0.9, "six": 0.85}},
}
BASE_WEIGHTS = {"wicket": 0.05, "dot": 0.30, "one": 0.30, "two": 0.07, "four": 0.15, "six": 0.07}


# How strongly the batter-vs-bowler rating gap shifts each outcome's weight.
# A positive gap (batter rated higher than the bowler) means fewer wickets and
# dots and more boundaries; a negative gap does the opposite.
RATING_FACTORS = {"wicket": -0.6, "dot": -0.2, "one": 0.0, "two": 0.1, "four": 0.45, "six": 0.55}


def rating_modifiers(batter_rating: int, bowler_rating: int) -> dict:
    """Outcome multipliers from the batter's batting and the bowler's bowling rating."""
    gap = max(-1.0, min(1.0, (batter_rating - bowler_rating) / 100))
    return {
        outcome: max(0.4, 1.0 + factor * gap)
        for outcome, factor in RATING_FACTORS.items()
    }


def format_overs(balls: int) -> str:
    return f"{balls // 6}.{balls % 6}"


def create_match(overs_limit: int, max_wickets: int = 10) -> dict:
    if isinstance(overs_limit, bool) or not isinstance(overs_limit, int) or not 1 <= overs_limit <= 20:
        raise ValueError("Overs must be a whole number from 1 to 20.")
    match = {"overs_limit": overs_limit, "balls": 0, "score": 0, "wickets": 0}
    if max_wickets != 10:
        # Only stored when it differs (a Super Over ends after 2 wickets).
        match["max_wickets"] = max_wickets
    return match


def is_match_over(match: dict) -> bool:
    return (
        match["wickets"] >= match.get("max_wickets", 10)
        or match["balls"] >= match["overs_limit"] * 6
    )


# ---------------------------------------------------------------------------
# Dismissals, extras and fielding
# ---------------------------------------------------------------------------
DISMISSAL_WEIGHTS = {"caught": 0.52, "bowled": 0.20, "lbw": 0.14, "run out": 0.06, "stumped": 0.08}
EXTRA_RATES = {"wide": 0.035, "no_ball": 0.012, "bye": 0.02}


def pick_dismissal(weights: dict | None = None, has_keeper: bool = True, rng=random.random) -> str:
    """How a wicket fell. Stumpings need a wicketkeeper in the fielding XI."""
    weights = dict(weights or DISMISSAL_WEIGHTS)
    if not has_keeper and "stumped" in weights:
        weights["caught"] = weights.get("caught", 0) + weights.pop("stumped")
    total = sum(weights.values())
    roll = rng() * total
    cumulative = 0.0
    last = next(iter(weights))
    for kind, weight in weights.items():
        cumulative += weight
        last = kind
        if roll < cumulative:
            return kind
    return last


def roll_extra(rates: dict | None = None, rng=random.random) -> str | None:
    """Return "wide", "no_ball", "bye" or None for a normal delivery."""
    rates = rates or EXTRA_RATES
    roll = rng()
    cumulative = 0.0
    for kind in ("wide", "no_ball", "bye"):
        cumulative += rates.get(kind, 0.0)
        if roll < cumulative:
            return kind
    return None


def simulate_ball(match, batting_style, bowling_style, pitch_modifiers=None, rng=random.random) -> dict:
    if batting_style not in BATTING_STYLES:
        raise ValueError(f"Unknown batting style: {batting_style}")
    if bowling_style not in BOWLING_STYLES:
        raise ValueError(f"Unknown bowling style: {bowling_style}")
    if is_match_over(match):
        raise ValueError("The innings is already over.")

    pitch_modifiers = pitch_modifiers or {}
    bat = BATTING_STYLES[batting_style]["mods"]
    bowl = BOWLING_STYLES[bowling_style]["mods"]
    weights = {
        outcome: BASE_WEIGHTS[outcome] * bat[outcome] * bowl[outcome] * pitch_modifiers.get(outcome, 1.0)
        for outcome in OUTCOMES
    }
    pick = rng() * sum(weights.values())
    outcome = OUTCOMES[-1]
    for name in OUTCOMES:  # wicket is first, so rng() == 0 always gives a wicket
        pick -= weights[name]
        if pick < 0:
            outcome = name
            break

    runs = OUTCOME_RUNS[outcome]
    match["balls"] += 1
    match["score"] += runs
    if outcome == "wicket":
        match["wickets"] += 1
    return {"outcome": outcome, "runs": runs, "over": format_overs(match["balls"])}
