"""Group multiplayer cricket bot implemented with Python's standard library."""

import html
import hmac
import json
import os
import random
import re
import secrets
import sqlite3
import ssl
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .game import (
    BATTING_STYLES,
    BOWLING_STYLES,
    OUTCOMES,
    create_match,
    format_overs,
    is_match_over,
    rating_modifiers,
    simulate_ball,
)
from .teams import PITCHES, TEAMS, bat_rating, bowl_rating, player_role

API_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 5
esc = html.escape
DIVIDER = "━━━━━━━━━━━━━━━━━━"
OUTCOME_TEXT = {
    "wicket": "🔴 OUT! The bowler gets the breakthrough.",
    "dot": "⚪ Dot ball.",
    "one": "🟢 1 run.",
    "two": "🟢 2 runs.",
    "four": "🔵 FOUR!",
    "six": "🟣 SIX!",
}
# Colour dot shown in front of every commentary line.
OUTCOME_ICON = {
    "wicket": "🔴",
    "six": "🟣",
    "four": "🔵",
    "dot": "⚪",
    "one": "🟢",
    "two": "🟢",
}
# Several lines per outcome so the commentary does not repeat. Variant 0 is
# the original wording; the variant used rotates with the ball number.
COMMENTARY_TEMPLATES = {
    "wicket": (
        "OUT! {bowler} beats {batter}; the batter is gone.",
        "Cleaned up! {bowler} breaks through and {batter} has to walk back.",
        "Gone! {batter} falls to a superb delivery from {bowler}.",
        "Huge wicket! {bowler} strikes and {batter} heads for the pavilion.",
    ),
    "six": (
        "SIX! {batter} launches {bowler} over the ropes.",
        "Out of the park! {batter} sends {bowler} into the stands.",
        "Massive hit! {batter} clears the boundary off {bowler}.",
        "Maximum! {batter} smashes {bowler} high and handsome.",
    ),
    "four": (
        "FOUR! {batter} finds the boundary off {bowler}.",
        "Cracking shot! {batter} pierces the gap against {bowler}.",
        "Races away! {batter} times {bowler} perfectly to the fence.",
        "Beautiful timing from {batter}! {bowler} can only watch it speed to the ropes.",
    ),
    "dot": (
        "{bowler} keeps it tight; {batter} can't score.",
        "Solid defence from {batter}; {bowler} builds the pressure.",
        "Beaten! {bowler} nearly gets {batter} with that one.",
        "Good length from {bowler}; {batter} has to respect it.",
    ),
    "one": (
        "{batter} nudges a single off {bowler}.",
        "Quick single! {batter} works {bowler} into the gap.",
        "{batter} rotates the strike off {bowler}.",
    ),
    "two": (
        "{batter} races back for {runs} runs off {bowler}.",
        "Two more! {batter} pushes {bowler} into the gap and comes back hard.",
        "Good running! {batter} turns {bowler} around for a couple.",
    ),
}
PITCH_TEXT = {
    "balanced": "Balanced pitch",
    "batting": "Batting paradise",
    "green": "Green seamer",
    "spin": "Turning track",
}

# Batter milestones (runs -> label)
BATTER_MILESTONES = {
    50: "🔥 FIFTY",
    100: "💯 CENTURY",
    150: "🚀 150 RUNS",
    200: "👑 DOUBLE CENTURY",
}
# Team total milestones
TEAM_MILESTONES = (50, 100, 150, 200, 250, 300)
# Partnership milestones
PARTNERSHIP_MILESTONES = (50, 100, 150, 200)
# Bowler wicket-haul milestones (wickets -> label)
BOWLER_MILESTONES = {
    3: "🎳 3-WICKET HAUL",
    5: "🏆 5-WICKET HAUL",
}
# Safe limit (Telegram's hard limit is 4096 characters per message)
SCORECARD_SAFE_LENGTH = 3900
ROLE_ICON = {"BAT": "🏏", "AR": "🔄", "BOWL": "🎳", "WK": "🧤"}
ROLE_NAME = {
    "BAT": "Batters",
    "AR": "All-rounders",
    "BOWL": "Bowlers",
    "WK": "Wicketkeepers",
}
# XI selector filter modes: callback value -> (button label, role code or None for all)
XI_FILTERS = {
    "all": ("🌐 All", None),
    "bat": ("🏏 BAT", "BAT"),
    "ar": ("🔄 AR", "AR"),
    "bowl": ("🎳 BOWL", "BOWL"),
    "wk": ("🧤 WK", "WK"),
}
BOWLER_MODE_LABEL = {
    "auto": "🤖 Auto rotation",
    "manual": "🎯 Manual pick",
}
# Light-hearted on-field banter. Keep it playful and respectful.
SLEDGE_LINES = {
    "wicket": (
        "Pavilion's that way, mate. Mind the steps!",
        "Thanks for dropping by. Say hi to the dressing room!",
        "That's a statement delivery. Off you go!",
        "Nice knock... for about five minutes.",
        "Your tea is waiting for you, champ.",
    ),
    "six": (
        "Go fetch that from the stands, will you?",
        "Is that your best? Bring a bit more pace!",
        "Enjoy the view from the boundary, mate.",
        "Somebody tell the bowler it's a cricket ball, not a gift.",
    ),
    "four": (
        "Pick a line and stick to it, mate!",
        "That one was gone before you finished bowling.",
        "Is that all you've got today?",
    ),
    "dot": (
        "Feeling the pressure yet? Not a run in sight.",
        "You can't hit what you can't read, mate.",
        "Dot, dot, dot... the scoreboard is getting lonely.",
    ),
    "keeper": (
        "Stumps are calling your name, mate.",
        "Careful with those feet, I'm watching you.",
        "Did you fall asleep out there? Wake up!",
    ),
}
SIM_MODE_LABEL = {
    "ball": "🎯 Ball by ball",
    "over": "⚡ Over by over",
}


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def build_https_context() -> ssl.SSLContext:
    verify_ssl = os.environ.get("TELEGRAM_SSL_VERIFY", "true").strip().lower() not in {"0", "false", "no"}
    if verify_ssl:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class TelegramBot:
    def __init__(self, token: str, database_path: str | Path | None = None):
        self.token = token
        self.ssl_context = build_https_context()
        self.database = sqlite3.connect(
            database_path or Path(__file__).resolve().parent.parent / "bot_state.sqlite3"
        )
        self.database.execute(
            "CREATE TABLE IF NOT EXISTS matches (chat_id INTEGER PRIMARY KEY, game_json TEXT NOT NULL)"
        )
        self.sessions = {
            chat_id: json.loads(game_json)
            for chat_id, game_json in self.database.execute(
                "SELECT chat_id, game_json FROM matches"
            )
        }
        self.offset = 0
        self.username = None
        self.started_at = time.time()
        self.callback_acknowledged = False
        self.callback_chat_id = None

    def persist_sessions(self) -> None:
        with self.database:
            self.database.execute("DELETE FROM matches")
            self.database.executemany(
                "INSERT INTO matches (chat_id, game_json) VALUES (?, ?)",
                [
                    (chat_id, json.dumps(game, ensure_ascii=False))
                    for chat_id, game in self.sessions.items()
                ],
            )

    def api(self, method: str, parameters: dict | None = None):
        payload = json.dumps(parameters or {}).encode("utf-8")
        request = Request(
            API_BASE.format(token=self.token, method=method),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=40, context=self.ssl_context) as response:
                result = json.loads(response.read())
        except HTTPError as error:
            try:
                error_body = json.loads(error.read())
                description = error_body.get("description", "unknown Telegram API error")
            except (json.JSONDecodeError, UnicodeDecodeError):
                description = "Telegram returned an unreadable error response"
            raise RuntimeError(f"Telegram API {method} failed (HTTP {error.code}): {description}") from error
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed: {result.get('description', 'unknown error')}")
        return result["result"]

    def reply(
        self,
        chat_id: int,
        text: str,
        keyboard: list | None = None,
        parse_mode: str | None = None,
    ):
        parameters = {"chat_id": chat_id, "text": text}
        if keyboard:
            parameters["reply_markup"] = {"inline_keyboard": keyboard}
        if parse_mode:
            parameters["parse_mode"] = parse_mode
        return self.api("sendMessage", parameters)

    def edit(
        self,
        game: dict,
        text: str,
        keyboard: list | None = None,
        parse_mode: str | None = None,
    ) -> None:
        if not game.get("message_id"):
            sent = self.reply(game["chat_id"], text, keyboard, parse_mode)
            if isinstance(sent, dict):
                game["message_id"] = sent.get("message_id")
            return
        parameters = {
            "chat_id": game["chat_id"],
            "message_id": game["message_id"],
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard or []},
        }
        if parse_mode:
            parameters["parse_mode"] = parse_mode
        try:
            self.api("editMessageText", parameters)
        except RuntimeError as error:
            if "message is not modified" in str(error).casefold():
                return
            if "HTTP 429" in str(error):
                print(
                    "Could not redraw the match message because Telegram rate-limited edits.",
                    file=sys.stderr,
                )
                return
            print(f"Could not update the match message; posting a fresh one instead: {error}", file=sys.stderr)
            sent = self.reply(game["chat_id"], text, keyboard, parse_mode)
            if isinstance(sent, dict):
                game["message_id"] = sent.get("message_id")

    def button(self, text: str, data: str) -> dict:
        return {"text": text, "callback_data": data}

    @staticmethod
    def league_name(league: str | None) -> str:
        if league == "ipl":
            return "IPL Franchise"
        return "International"

    def mode_badge(self, league: str | None) -> str:
        if league == "ipl":
            return "🏆 IPL Franchise"
        return "🌍 International Cricket"

    def team_badge(self, team_key: str | None) -> str:
        if not team_key or team_key not in TEAMS:
            return "🏏 Team"
        team = TEAMS[team_key]
        return f"{team.get('logo', '🏏')} {team['name']}"

    def mode_keyboard(self) -> list:
        return [[
            self.button("🌍 International Cricket", "mode:international"),
            self.button("🏆 IPL Franchise", "mode:ipl"),
        ]]

    def team_keyboard(self, side: str, league: str | None = None) -> list:
        selected_league = league or "international"
        mode_row = [
            self.button(
                ("✅ " if selected_league == "international" else "") + "🌍 International Cricket",
                "mode:international",
            ),
            self.button(
                ("✅ " if selected_league == "ipl" else "") + "🏆 IPL Franchise",
                "mode:ipl",
            ),
        ]
        teams = [
            (key, team)
            for key, team in TEAMS.items()
            if team.get("league", "international") == selected_league
        ]
        if not teams:
            teams = list(TEAMS.items())
        rows = [mode_row]
        for index in range(0, len(teams), 2):
            rows.append([
                self.button(
                    f"{TEAMS[key].get('logo', '🏏')} {TEAMS[key]['name']}",
                    f"team:{side}:{key}",
                )
                for key, _ in teams[index:index + 2]
            ])
        return rows

    @staticmethod
    def normalize_lineup(lineup: list[int] | None) -> list[int]:
        if not lineup:
            return []
        seen = set()
        normalized = []
        for player_index in lineup:
            try:
                player_index = int(player_index)
            except (TypeError, ValueError):
                continue
            if 0 <= player_index and player_index not in seen:
                seen.add(player_index)
                normalized.append(player_index)
        return sorted(normalized)

    @staticmethod
    def xi_filter(game: dict, side: str) -> str:
        value = (game.get("xi_filter") or {}).get(side, "all")
        return value if value in XI_FILTERS else "all"

    @staticmethod
    def role_counts(team_key: str, lineup: list[int]) -> dict:
        players = TEAMS[team_key]["players"]
        counts = {"BAT": 0, "AR": 0, "BOWL": 0, "WK": 0}
        for index in lineup:
            if 0 <= index < len(players):
                counts[player_role(players[index])] += 1
        return counts

    def lineup_keyboard(self, game: dict, side: str) -> list:
        team = TEAMS[game["teams"][side]]
        selected = self.normalize_lineup(game["lineups"].get(side))
        game["lineups"][side] = selected
        active_filter = self.xi_filter(game, side)
        wanted_role = XI_FILTERS[active_filter][1]

        filter_buttons = [
            self.button(
                ("✅ " if key == active_filter else "") + label,
                f"xi-filter:{side}:{key}",
            )
            for key, (label, _) in XI_FILTERS.items()
        ]
        rows = [filter_buttons[:3], filter_buttons[3:]]

        visible = [
            index for index, player in enumerate(team["players"])
            if wanted_role is None or player_role(player) == wanted_role
        ]
        for start in range(0, len(visible), 2):
            row = []
            for player_index in visible[start:start + 2]:
                player = team["players"][player_index]
                mark = "✅ " if player_index in selected else ""
                row.append(self.button(
                    f"{mark}{ROLE_ICON[player_role(player)]} {player}",
                    f"xi:{side}:{player_index}",
                ))
            rows.append(row)
        rows.append([self.button(
            f"Confirm XI ({len(selected)}/11)",
            f"xi-confirm:{side}",
        )])
        return rows

    def overs_keyboard(self) -> list:
        return [
            [self.button("🟢 5 overs", "overs:5"), self.button("🔵 10 overs", "overs:10")],
            [self.button("🟣 20 overs", "overs:20"), self.button("⚡ 2 overs", "overs:2")],
        ]

    def pitch_keyboard(self) -> list:
        return [
            [self.button("⚖️ Balanced", "pitch:balanced"), self.button("🏏 Batting paradise", "pitch:batting")],
            [self.button("🟢 Green seamer", "pitch:green"), self.button("🌀 Turning track", "pitch:spin")],
        ]

    def batting_keyboard(self) -> list:
        return [
            [self.button("🔥 Aggressive", "bat:aggressive"), self.button("🛡 Defensive", "bat:defensive")],
            [self.button("🚀 Ultra aggressive", "bat:ultra"), self.button("🎯 Hit gaps", "bat:gaps")],
            [self.button("🔄 Rotate strike", "bat:rotate")],
        ]

    def bowling_keyboard(self) -> list:
        return [
            [self.button("⚡ Aggressive", "bowl:aggressive"), self.button("🛡 Defensive", "bowl:defensive")],
            [self.button("🌀 Variation", "bowl:variation"), self.button("🎭 Knuckle ball", "bowl:knuckle")],
        ]

    # ------------------------------------------------------------------
    # Toss
    # ------------------------------------------------------------------
    def toss_call_keyboard(self) -> list:
        return [[
            self.button("🪙 Heads", "toss-call:heads"),
            self.button("🪙 Tails", "toss-call:tails"),
        ]]

    def toss_choice_keyboard(self) -> list:
        return [[
            self.button("🏏 Bat first", "toss-choice:bat"),
            self.button("🎳 Bowl first", "toss-choice:bowl"),
        ]]

    def toss_prompt(self, game: dict) -> str:
        home = esc(game["captain_names"]["home"])
        away = esc(game["captain_names"].get("away") or "Opponent")
        return (
            "🪙 <b>TOSS TIME!</b>\n"
            f"{esc(self.mode_badge(game.get('league')))}\n\n"
            f"🏠 <b>{home}</b>   🆚   ✈️ <b>{away}</b>\n\n"
            f"{DIVIDER}\n"
            "🎙 <i>The captains walk out to the middle...</i>\n\n"
            f"🪙 <b>{home}</b>, call it in the air!\n"
            "👇 Heads or Tails?"
        )

    def toss_summary(self, game: dict) -> str:
        toss = game.get("toss")
        if not toss:
            return ""
        home = esc(game["captain_names"]["home"])
        winner_name = esc(game["captain_names"][toss["winner"]])
        call_ok = toss["call"] == toss["result"]
        lines = [
            f"🪙 <b>{home}</b> called <b>{toss['call'].title()}</b>",
            f"🌀 The coin lands on... <b>{toss['result'].upper()}</b>! {'✅' if call_ok else '❌'}",
            "",
        ]
        decision = toss.get("decision")
        if decision:
            icon = "🏏" if decision == "bat" else "🎳"
            lines.append(
                f"🏆 <b>{winner_name}</b> won the toss and chose to "
                f"{icon} <b>{decision.upper()}</b> first."
            )
        else:
            lines.append(f"🏆 <b>{winner_name}</b> won the toss!")
        return "\n".join(lines)

    def toss_decision_prompt(self, game: dict) -> str:
        winner_name = esc(game["captain_names"][game["toss"]["winner"]])
        return (
            f"{self.toss_summary(game)}\n\n"
            f"{DIVIDER}\n"
            f"🎙 <b>{winner_name}</b>, it's your call!\n"
            "🧠 What will you do first?\n\n"
            "🏏 <b>Bat first</b>   or   🎳 <b>Bowl first</b>\n"
            "👇 Choose below"
        )

    def apply_toss_decision(self, game: dict, decision: str) -> None:
        toss = game["toss"]
        toss["decision"] = decision
        winner = toss["winner"]
        loser = "away" if winner == "home" else "home"
        game["first_batting"] = winner if decision == "bat" else loser
        game["stage"] = "home_team"
        batting_first = game["first_batting"]
        bowling_first = "away" if batting_first == "home" else "home"
        self.edit(
            game,
            f"{self.toss_summary(game)}\n\n"
            f"{DIVIDER}\n"
            f"🏏 <b>{esc(game['captain_names'][batting_first])}</b> will bat first\n"
            f"🎳 <b>{esc(game['captain_names'][bowling_first])}</b> will bowl first\n\n"
            f"🏠 <b>{esc(game['captain_names']['home'])}</b>, choose your team "
            f"({esc(self.league_name(game.get('league')))} mode):",
            self.team_keyboard("home", game.get("league")),
            parse_mode="HTML",
        )

    @staticmethod
    def ready_prompt(game: dict | None = None) -> str:
        bowler_mode = BOWLER_MODE_LABEL[(game or {}).get("bowler_mode", "auto")]
        return (
            f"\n{DIVIDER}\n"
            "🎮 <b>Choose how to play:</b>\n\n"
            "🎯 <b>Ball by ball</b> — pick your style for every delivery\n"
            "⚡ <b>Over by over</b> — pick once per over; all 6 balls are simulated "
            "with ball-by-ball commentary\n\n"
            f"🎳 <b>Bowlers:</b> {bowler_mode}\n"
            "   🤖 Auto: bowlers rotate every over\n"
            "   🎯 Manual: the bowling captain picks who bowls each over\n\n"
            "▶️ Host, start the match when both captains are ready:"
        )

    def ready_keyboard(self, game: dict | None = None) -> list:
        return [
            [self.button("🎯 Start ball by ball", "start-match")],
            [self.button("⚡ Start over by over", "start-match-over")],
            [self.bowler_mode_button(game)],
        ]

    def bowler_mode_button(self, game: dict | None) -> dict:
        if (game or {}).get("bowler_mode") == "manual":
            return self.button("🎳 Bowlers: 🎯 Manual (tap for 🤖 Auto)", "bowler-mode:auto")
        return self.button("🎳 Bowlers: 🤖 Auto (tap for 🎯 Manual)", "bowler-mode:manual")

    # ------------------------------------------------------------------
    # Ratings, bowler selection and sledging helpers
    # ------------------------------------------------------------------
    @staticmethod
    def xi_ratings(team_key: str, lineup: list[int]) -> tuple[int, int]:
        """(average batting rating of the XI, average of its best five bowling ratings)."""
        players = TEAMS[team_key]["players"]
        names = [players[index] for index in lineup if 0 <= index < len(players)]
        if not names:
            return 0, 0
        batting = round(sum(bat_rating(name) for name in names) / len(names))
        bowling_scores = sorted(
            (bowl_rating(name) for name in names if player_role(name) in ("BOWL", "AR")),
            reverse=True,
        )[:5]
        bowling = round(sum(bowling_scores) / len(bowling_scores)) if bowling_scores else 0
        return batting, bowling

    @staticmethod
    def match_modifiers(game: dict, batter_name: str, bowler_name: str) -> dict:
        """Pitch effect multiplied by the batter-vs-bowler rating effect."""
        pitch = PITCHES[game["pitch"]]["modifiers"]
        ratings = rating_modifiers(bat_rating(batter_name), bowl_rating(bowler_name))
        return {outcome: pitch.get(outcome, 1.0) * ratings[outcome] for outcome in OUTCOMES}

    @staticmethod
    def bowler_quota(game: dict) -> int:
        """Maximum overs per bowler (T20 style: a fifth of the innings)."""
        options = max(1, len(game["innings"].get("bowler_rotation") or []))
        overs = game["overs_limit"]
        return max(1, -(-overs // 5), -(-overs // options))

    @staticmethod
    def overs_bowled(innings: dict, name: str) -> int:
        balls = innings["bowlers"].get(name, {}).get("balls", 0)
        return (balls + 5) // 6

    def current_bowler_name(self, game: dict) -> str:
        innings = game["innings"]
        if innings.get("manual_bowler"):
            return innings["manual_bowler"]
        rotation = innings.get("bowler_rotation") or []
        if not rotation:
            return innings.get("last_bowler") or "To be assigned"
        return rotation[innings.get("bowler_index", 0) % len(rotation)]

    def eligible_bowlers(self, game: dict) -> list[tuple[int, str]]:
        """Bowlers the captain may pick: not last over's bowler, still within quota."""
        innings = game["innings"]
        rotation = innings.get("bowler_rotation") or []
        quota = self.bowler_quota(game)
        last = innings.get("last_over_bowler")
        eligible = [
            (index, name) for index, name in enumerate(rotation)
            if name != last and self.overs_bowled(innings, name) < quota
        ]
        if not eligible:
            eligible = [
                (index, name) for index, name in enumerate(rotation)
                if self.overs_bowled(innings, name) < quota
            ]
        return eligible or list(enumerate(rotation))

    def next_phase(self, game: dict) -> str:
        innings = game["innings"]
        if (
            game.get("bowler_mode") == "manual"
            and innings["match"]["balls"] % 6 == 0
            and not innings.get("manual_bowler")
        ):
            return "pick_bowler"
        return "bat"

    def ai_pick_bowler(self, game: dict) -> str:
        eligible = self.eligible_bowlers(game)
        names = [name for _, name in eligible]
        weights = [bowl_rating(name) ** 2 for name in names]
        return random.choices(names, weights=weights, k=1)[0]

    def bowler_keyboard(self, game: dict) -> list:
        innings = game["innings"]
        quota = self.bowler_quota(game)
        buttons = [
            self.button(
                f"🎳 {name} ⭐{bowl_rating(name)} ({self.overs_bowled(innings, name)}/{quota})",
                f"pick-bowler:{index}",
            )
            for index, name in self.eligible_bowlers(game)
        ]
        return [buttons[start:start + 2] for start in range(0, len(buttons), 2)]

    def bowler_pick_text(self, game: dict) -> list[str]:
        innings = game["innings"]
        quota = self.bowler_quota(game)
        over_number = innings["match"]["balls"] // 6 + 1
        available = {name for _, name in self.eligible_bowlers(game)}
        unavailable = []
        for name in innings.get("bowler_rotation") or []:
            if name in available:
                continue
            if name == innings.get("last_over_bowler"):
                unavailable.append(f"{esc(name)} (bowled last over)")
            else:
                unavailable.append(f"{esc(name)} ({quota}/{quota} overs)")
        lines = [
            f"🎳 <b>Choose the bowler for over {over_number}:</b>",
            f"⭐ = bowling rating  •  (overs bowled/{quota} max)",
        ]
        if unavailable:
            lines.append("🚫 Resting: " + ", ".join(unavailable))
        return lines

    def fielding_keeper(self, game: dict) -> str | None:
        side = self.bowling_side(game)
        players = TEAMS[game["teams"][side]]["players"]
        for index in game["lineups"][side]:
            if player_role(players[index]) == "WK":
                return players[index]
        return None

    def add_sledge(self, game: dict, outcome: str, bowler: str, batter: str, over_label: str) -> None:
        """Maybe add a short, playful sledge for the ball just played."""
        if not game.get("sledging", True):
            return
        innings = game["innings"]
        streak = innings.get("dot_streak", 0) + 1 if outcome == "dot" else 0
        innings["dot_streak"] = streak
        kind, chance = None, 0.0
        if outcome == "wicket":
            kind, chance = "wicket", 0.9
        elif outcome == "six":
            kind, chance = "six", 0.7
        elif outcome == "four":
            kind, chance = "four", 0.35
        elif outcome == "dot" and streak >= 2:
            kind, chance = "dot", 0.6
        if kind is None or random.random() >= chance:
            return
        speaker, target = (batter, bowler) if kind in ("six", "four") else (bowler, batter)
        if kind == "dot":
            keeper = self.fielding_keeper(game)
            if keeper and random.random() < 0.4:
                kind, speaker = "keeper", keeper
        innings.setdefault("sledges", []).append({
            "over": over_label,
            "from": speaker,
            "to": target,
            "text": random.choice(SLEDGE_LINES[kind]),
        })
        del innings["sledges"][: -(4 if game.get("sim_mode") == "over" else 2)]

    def handle_bowler_pick(self, callback_id: str, game: dict, user_id: int, index_text: str) -> None:
        if game.get("stage") != "live" or game.get("phase") != "pick_bowler":
            self.answer_callback(callback_id, "No bowler needs to be picked right now.")
            return
        if game["captains"][self.bowling_side(game)] != user_id:
            self.answer_callback(callback_id, "🎳 Only the bowling captain can pick the bowler.")
            return
        eligible = dict(self.eligible_bowlers(game))
        try:
            index = int(index_text)
        except ValueError:
            index = -1
        if index not in eligible:
            self.answer_callback(callback_id, "That bowler is not available this over.")
            return
        game["innings"]["manual_bowler"] = eligible[index]
        game["phase"] = "bat"
        self.answer_callback(callback_id)
        self.advance_vs_bot_turn(game)

    @staticmethod
    def auto_xi(team_key: str) -> list[int]:
        """Role-balanced XI for the bot: 1 WK, 4 BOWL, 2 AR, 4 BAT where possible."""
        players = TEAMS[team_key]["players"]
        pools = {"WK": [], "BOWL": [], "AR": [], "BAT": []}
        for index, name in enumerate(players):
            pools[player_role(name)].append(index)
        for pool in pools.values():
            random.shuffle(pool)
        chosen: list[int] = []
        for role, quota in (("WK", 1), ("BOWL", 4), ("AR", 2), ("BAT", 4)):
            chosen.extend(pools[role][:quota])
            del pools[role][:quota]
        leftovers = [index for pool in pools.values() for index in pool]
        random.shuffle(leftovers)
        chosen.extend(leftovers[: 11 - len(chosen)])
        return sorted(chosen[:11])

    def lobby_text(self, game: dict) -> str:
        return (
            "🏏 <b>MATCH LOBBY</b>\n\n"
            f"🧢 <b>{esc(game['captain_names']['home'])}</b> is hosting a multiplayer\n"
            f"{esc(self.mode_badge(game.get('league')))} match.\n\n"
            f"{DIVIDER}\n"
            "👥 Another group member should join as away captain:\n"
            "👇 Tap the button below"
        )

    def xi_composition(self, game: dict, side: str) -> str:
        lineup = self.normalize_lineup(game["lineups"].get(side))
        counts = self.role_counts(game["teams"][side], lineup)
        return (
            f"🧮 <b>Your XI:</b> 🏏 {counts['BAT']} BAT  •  🔄 {counts['AR']} AR  •  "
            f"🎳 {counts['BOWL']} BOWL  •  🧤 {counts['WK']} WK"
        )

    def xi_rating_line(self, game: dict, side: str) -> list[str]:
        lineup = self.normalize_lineup(game["lineups"].get(side))
        if not lineup:
            return []
        batting, bowling = self.xi_ratings(game["teams"][side], lineup)
        return [f"⭐ <b>XI rating:</b> 🏏 Bat {batting}  •  🎳 Bowl {bowling}"]

    def xi_tips(self, game: dict, side: str) -> list[str]:
        lineup = self.normalize_lineup(game["lineups"].get(side))
        if len(lineup) != 11:
            return []
        counts = self.role_counts(game["teams"][side], lineup)
        tips = []
        if counts["WK"] == 0:
            tips.append("⚠️ No wicketkeeper in this XI — tap 🧤 WK to add one.")
        if counts["BOWL"] + counts["AR"] < 5:
            tips.append(
                f"⚠️ Only {counts['BOWL'] + counts['AR']} bowling options (BOWL + AR). "
                "Five or more is safer for a full match."
            )
        return tips

    def xi_prompt(self, game: dict, side: str, header: str = "") -> str:
        captain = esc(game["captain_names"][side])
        badge = esc(self.team_badge(game["teams"][side]))
        count = len(game["lineups"].get(side, []))
        active_filter = self.xi_filter(game, side)
        role = XI_FILTERS[active_filter][1]
        showing = "🌐 All players" if role is None else f"{ROLE_ICON[role]} {ROLE_NAME[role]} only"
        lines = [
            f"{header}"
            f"👕 <b>{captain}</b>, select exactly 11 players for {badge}\n"
            f"✅ <b>({count}/11 selected):</b>",
            "",
            self.xi_composition(game, side),
            *self.xi_rating_line(game, side),
            f"🔎 Showing: <b>{showing}</b>",
            "🏏 BAT  •  🔄 AR (all-rounder)  •  🎳 BOWL  •  🧤 WK",
        ]
        for tip in self.xi_tips(game, side):
            lines.append(tip)
        return "\n".join(lines)

    def help_text(self) -> str:
        return (
            "🏏 <b>CRICKET SIMULATOR BOT</b>\n"
            "<i>Toss  •  Pick your XI  •  Play ball by ball</i>\n\n"
            f"{DIVIDER}\n"
            "🎮 <b>START A MATCH</b>\n\n"
            "👥 <b>In a group (2 players)</b>\n"
            "▫️ /playint  —  🌍 International match\n"
            "▫️ /newmatch  —  same as /playint\n"
            "▫️ /playipl  —  🏆 IPL match\n\n"
            "🤖 <b>Solo vs the bot</b>\n"
            "▫️ /vsbot  —  🌍 International vs Bot\n"
            "▫️ /vsbotipl  —  🏆 IPL vs Bot\n\n"
            f"{DIVIDER}\n"
            "🛠 <b>DURING A MATCH</b>\n\n"
            "▫️ /toss  —  🪙 Show the toss\n"
            "▫️ /sledge  —  🗣 Sledging on/off (host)\n"
            "▫️ /refresh  —  🔄 Redraw the live board\n"
            "▫️ /cancel  —  ❌ Cancel the match (host only)\n\n"
            f"{DIVIDER}\n"
            "📡 <b>EXTRAS</b>\n\n"
            "▫️ /ping  —  🟢 Check the bot is online\n"
            "▫️ /members  —  👥 Group member count\n"
            "▫️ /help  —  📖 Show this guide\n\n"
            f"{DIVIDER}\n"
            "🗺 <b>MATCH FLOW</b>\n\n"
            "1️⃣  🪙 <b>Toss</b> — the winner chooses to bat or bowl\n"
            "2️⃣  👕 Choose the teams\n"
            "3️⃣  ⏱ Pick the overs (2 / 5 / 10 / 20)\n"
            "4️⃣  🏟 Pick the pitch\n"
            "5️⃣  ✅ Select your XI\n"
            "6️⃣  ▶️ Start: 🎯 ball by ball or ⚡ over by over\n\n"
            f"{DIVIDER}\n"
            "🧢 <b>PLAYER ROLES (International + IPL)</b>\n\n"
            "🏏 BAT — batter    🔄 AR — all-rounder\n"
            "🎳 BOWL — bowler    🧤 WK — wicketkeeper\n\n"
            "While picking your XI, tap the filter buttons "
            "(🌐 All / 🏏 BAT / 🔄 AR / 🎳 BOWL / 🧤 WK) to browse each role. "
            "Your ticked players stay ticked, and the XI counter shows your balance. "
            "Only 🎳 BOWL and 🔄 AR players bowl in the match.\n\n"
            f"{DIVIDER}\n"
            "⭐ <b>RATINGS</b>\n\n"
            "Every player has a separate 🏏 batting and 🎳 bowling rating (1-99). "
            "A strong batter against a weak bowler scores faster and gets out less; "
            "a star bowler against a weak batter takes more wickets. "
            "You see ⭐ ratings on the scorecard and the XI rating when picking your team.\n\n"
            "🎳 <b>BOWLER MODE</b>\n\n"
            "🤖 <b>Auto</b> — bowlers rotate every over\n"
            "🎯 <b>Manual</b> — the bowling captain picks each over's bowler "
            "(no back-to-back overs, max overs per bowler apply)\n"
            "The host can switch with the 🎳 Bowlers button.\n\n"
            "🗣 <b>SLEDGING</b> — playful on-field banter after wickets, sixes and "
            "dot-ball streaks. Host can use /sledge to turn it on or off.\n\n"
            f"{DIVIDER}\n"
            "🎯 <b>EVERY BALL</b>\n\n"
            "🏏 <b>Batting captain:</b>\n"
            "🔥 Aggressive  •  🛡 Defensive  •  🚀 Ultra\n"
            "🎯 Hit gaps  •  🔄 Rotate strike\n\n"
            "🎳 <b>Bowling captain:</b>\n"
            "⚡ Aggressive  •  🛡 Defensive\n"
            "🌀 Variation  •  🎭 Knuckle ball\n\n"
            "⚡ <b>Over by over mode:</b> pick your styles once and the bot "
            "plays all 6 balls with ball-by-ball commentary. The host can switch "
            "modes any time with the button under the scorecard.\n\n"
            "🎙 Live commentary, partnerships and milestones:\n"
            "🔥 50  •  💯 100  •  🤝 partnerships  •  🏆 wicket hauls"
        )

    @staticmethod
    def player_label(user: dict) -> str:
        return user.get("first_name") or user.get("username") or str(user.get("id", "Captain"))

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    @staticmethod
    def ordinal(number: int) -> str:
        if 10 <= number % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
        return f"{number}{suffix}"

    def create_lobby(self, chat: dict, user: dict, league: str | None = None) -> None:
        self.create_match_lobby(chat, user, league, vs_bot=False)

    def create_match_lobby(
        self,
        chat: dict,
        user: dict,
        league: str | None,
        vs_bot: bool,
    ) -> None:
        chat_id = chat["id"]
        if not vs_bot and chat.get("type") not in ("group", "supergroup"):
            self.reply(chat_id, "👥 Add this bot to a Telegram group to start a multiplayer match.")
            return
        if not user.get("id"):
            self.reply(chat_id, "I couldn't identify the captain. Please start the match from your own account.")
            return
        selected_league = league if league in ("international", "ipl") else "international"
        game = {
            "chat_id": chat_id,
            "stage": "join",
            "host": user.get("id"),
            "captains": {"home": user.get("id"), "away": None},
            "captain_names": {
                "home": self.player_label(user),
                "away": "Cricket AI" if vs_bot else None,
            },
            "teams": {},
            "lineups": {"home": [], "away": []},
            "message_id": None,
            "league": selected_league,
            "vs_bot": vs_bot,
            "toss": None,
            "first_batting": "home",
        }
        self.sessions[chat_id] = game
        if vs_bot:
            # Single player: straight to the toss.
            game["stage"] = "toss_call"
            self.edit(game, self.toss_prompt(game), self.toss_call_keyboard(), parse_mode="HTML")
            return
        self.edit(
            game,
            self.lobby_text(game),
            [[self.button("🧢 Join as away captain", "join")]],
            parse_mode="HTML",
        )

    def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        if self.callback_acknowledged:
            if text and self.callback_chat_id is not None:
                self.reply(self.callback_chat_id, f"⚠️ {text}")
            return
        self.callback_acknowledged = True
        parameters = {"callback_query_id": callback_id}
        if text:
            parameters["text"] = text
        try:
            self.api("answerCallbackQuery", parameters)
        except RuntimeError as error:
            # An expired callback should not prevent its match action from being processed.
            print(f"Could not acknowledge Telegram callback {callback_id}: {error}", file=sys.stderr)

    @staticmethod
    def is_current_screen(game: dict, message: dict) -> bool:
        message_id = message.get("message_id")
        if game.get("message_id") is None and message_id is not None:
            game["message_id"] = message_id
        return message_id is not None and message_id == game.get("message_id")

    def handle_message(self, message: dict) -> None:
        chat = message["chat"]
        chat_id = chat["id"]
        text = message.get("text", "").strip()
        command_match = re.match(r"^/([A-Za-z0-9_]+)(?:@([A-Za-z0-9_]+))?(?=\s|$)", text)
        if not command_match:
            return
        command = command_match.group(1).lower()
        target = command_match.group(2)
        if target and self.username and target.casefold() != self.username.casefold():
            return
        if target and not self.username:
            return
        user = message.get("from") or {}

        busy_text = "⚠️ A match is already in progress.\n\nUse /cancel before starting another."

        if command in ("start", "help"):
            self.reply(chat_id, self.help_text(), parse_mode="HTML")
        elif command == "ping":
            uptime_seconds = int(time.time() - self.started_at)
            uptime_text = self._format_duration(uptime_seconds)
            self.reply(
                chat_id,
                f"🟢 <b>Pong!</b> Bot is online.\n⏱ Uptime: <b>{esc(uptime_text)}</b>",
                parse_mode="HTML",
            )
        elif command == "members":
            try:
                count = self.api("getChatMembersCount", {"chat_id": chat_id})
            except (RuntimeError, URLError, TimeoutError) as error:
                self.reply(chat_id, f"⚠️ I could not fetch group members right now: {error}")
                return
            self.reply(chat_id, f"👥 <b>Group members: {esc(str(count))}</b>", parse_mode="HTML")
        elif command == "refresh":
            game = self.sessions.get(chat_id)
            if not game:
                self.reply(chat_id, "ℹ️ There is no active match or lobby to refresh.")
                return
            self.refresh_game(game)
        elif command == "sledge":
            game = self.sessions.get(chat_id)
            if not game:
                self.reply(chat_id, "ℹ️ Start a match first, then use /sledge to switch the banter on or off.")
            elif game.get("host") != user.get("id"):
                self.reply(chat_id, "⚠️ Only the match host can switch sledging on or off.")
            else:
                game["sledging"] = not game.get("sledging", True)
                state = "ON 🗣" if game["sledging"] else "OFF 🤐"
                self.reply(chat_id, f"🗣 Sledging is now <b>{state}</b>", parse_mode="HTML")
        elif command == "toss":
            game = self.sessions.get(chat_id)
            if game and game.get("stage") in ("toss_call", "toss_decision"):
                self.refresh_game(game)
            elif game and game.get("toss") and game["toss"].get("decision"):
                self.reply(chat_id, self.toss_summary(game), parse_mode="HTML")
            else:
                self.reply(
                    chat_id,
                    "🪙 <b>No toss yet</b>\n\n"
                    "Start a match with /playint, /playipl, /vsbot or /vsbotipl.\n"
                    "The toss is the first step — the winner chooses to 🏏 bat or 🎳 bowl.",
                    parse_mode="HTML",
                )
        elif command in ("playint", "newmatch"):
            current_game = self.sessions.get(chat_id)
            if current_game and current_game.get("stage") != "complete":
                self.reply(chat_id, busy_text)
                return
            self.create_lobby(chat, user, "international")
        elif command == "playipl":
            current_game = self.sessions.get(chat_id)
            if current_game and current_game.get("stage") != "complete":
                self.reply(chat_id, busy_text)
                return
            self.create_lobby(chat, user, "ipl")
        elif command in ("vsbot", "vsbotipl"):
            current_game = self.sessions.get(chat_id)
            if current_game and current_game.get("stage") != "complete":
                self.reply(chat_id, busy_text)
                return
            league = "ipl" if command == "vsbotipl" else "international"
            self.create_match_lobby(chat, user, league, vs_bot=True)
        elif command == "cancel":
            game = self.sessions.get(chat_id)
            if not game:
                self.reply(chat_id, "ℹ️ There is no match to cancel.")
            elif game.get("host") != user.get("id"):
                self.reply(chat_id, "⚠️ Only the match host can cancel this match.")
            else:
                self.sessions.pop(chat_id, None)
                self.reply(chat_id, "❌ Match cancelled.\n\nSend /playint or /playipl to start another.")
        else:
            self.reply(chat_id, "❓ Unknown command. Use /help to see the available commands.")

    def handle_callback(self, callback: dict) -> None:
        callback_id = callback["id"]
        self.callback_acknowledged = False
        message = callback.get("message", {})
        chat = message.get("chat")
        if not chat:
            self.answer_callback(callback_id)
            return
        chat_id = chat["id"]
        self.callback_chat_id = chat_id
        self.answer_callback(callback_id)
        user = callback.get("from", {})
        user_id = user.get("id")
        data = callback.get("data", "")

        if data == "new":
            self.answer_callback(callback_id)
            self.create_lobby(chat, user)
            return
        if data.startswith("mode:"):
            league = data.partition(":")[2]
            if league not in ("international", "ipl"):
                self.answer_callback(callback_id, "Choose a valid match format.")
                return
            game = self.sessions.get(chat_id)
            if not game or game["stage"] not in ("home_team", "away_team"):
                self.answer_callback(callback_id, "No team selection is active to change the mode.")
                return
            if not self.is_current_screen(game, message):
                self.answer_callback(callback_id, "This screen is out of date. Use /refresh for the current options.")
                return
            side = "home" if game["stage"] == "home_team" else "away"
            if game["captains"].get(side) != user_id:
                self.answer_callback(callback_id, "Only the active captain can change the match mode.")
                return
            game["league"] = league
            self.answer_callback(callback_id)
            self.edit(
                game,
                f"✨ <b>{esc(self.mode_badge(league))}</b> selected\n\n"
                f"{DIVIDER}\n"
                f"👕 Choose the <b>{side}</b> team for this roster:",
                self.team_keyboard(side, league),
                parse_mode="HTML",
            )
            return
        if data == "join":
            game = self.sessions.get(chat_id)
            if not game or game["stage"] != "join":
                self.answer_callback(callback_id, "This match is not waiting for a captain.")
                return
            if not self.is_current_screen(game, message):
                self.answer_callback(callback_id, "This screen is out of date. Use /refresh for the current options.")
                return
            if user_id == game["host"]:
                self.answer_callback(callback_id, "A different group member must join as the away captain.")
                return
            game["captains"]["away"] = user_id
            game["captain_names"]["away"] = self.player_label(user)
            game["stage"] = "toss_call"
            self.answer_callback(callback_id)
            self.edit(
                game,
                f"🧢 <b>{esc(game['captain_names']['away'])}</b> joined as away captain!\n\n"
                + self.toss_prompt(game),
                self.toss_call_keyboard(),
                parse_mode="HTML",
            )
            return

        game = self.sessions.get(chat_id)
        if not game:
            self.answer_callback(callback_id, "No active match. Send /playint or /playipl in a group.")
            return
        if not self.is_current_screen(game, message):
            self.answer_callback(callback_id, "This screen is out of date. Use /refresh for the current options.")
            return

        # ---------------- Toss ----------------
        if data.startswith("toss-call:"):
            call = data.partition(":")[2]
            if game["stage"] != "toss_call" or user_id != game["host"]:
                self.answer_callback(callback_id, "🪙 Only the host (home captain) can call the toss.")
                return
            if call not in ("heads", "tails"):
                self.answer_callback(callback_id, "Call heads or tails.")
                return
            result = random.choice(["heads", "tails"])
            winner = "home" if call == result else "away"
            game["toss"] = {"call": call, "result": result, "winner": winner, "decision": None}
            self.answer_callback(callback_id)
            if game.get("vs_bot") and winner == "away":
                self.apply_toss_decision(game, random.choice(["bat", "bowl"]))
                return
            game["stage"] = "toss_decision"
            self.edit(
                game,
                self.toss_decision_prompt(game),
                self.toss_choice_keyboard(),
                parse_mode="HTML",
            )
            return

        if data.startswith("toss-choice:"):
            decision = data.partition(":")[2]
            if game["stage"] != "toss_decision":
                self.answer_callback(callback_id, "The toss decision is no longer active.")
                return
            winner = game["toss"]["winner"]
            if game["captains"][winner] != user_id:
                self.answer_callback(callback_id, "🏆 Only the toss winner can choose to bat or bowl.")
                return
            if decision not in ("bat", "bowl"):
                self.answer_callback(callback_id, "Choose to bat or bowl.")
                return
            self.answer_callback(callback_id)
            self.apply_toss_decision(game, decision)
            return

        # ---------------- Teams ----------------
        if data.startswith("team:"):
            _, side, team_key = data.split(":", 2)
            expected_stage = f"{side}_team"
            if side not in ("home", "away") or game["stage"] != expected_stage:
                self.answer_callback(callback_id, "That team selection is no longer active.")
                return
            if game["captains"][side] != user_id:
                self.answer_callback(callback_id, "Only that side's captain can choose its team.")
                return
            if team_key not in TEAMS:
                self.answer_callback(callback_id, "Unknown team.")
                return
            if TEAMS[team_key].get("league", "international") != game.get("league", "international"):
                self.answer_callback(callback_id, f"Choose a team from the {self.league_name(game.get('league'))} selection.")
                return
            if side == "away" and team_key == game["teams"].get("home"):
                self.answer_callback(callback_id, "Choose a different team from the home side.")
                return
            self.answer_callback(callback_id)
            game["teams"][side] = team_key
            if side == "home":
                if game.get("vs_bot"):
                    candidates = [
                        key for key, team in TEAMS.items()
                        if team.get("league", "international") == game.get("league")
                        and key != team_key
                    ]
                    if not candidates:
                        self.answer_callback(callback_id, "No opponent team is available.")
                        return
                    away_team = random.choice(candidates)
                    game["teams"]["away"] = away_team
                    game["lineups"]["away"] = self.auto_xi(away_team)
                    game["stage"] = "overs"
                    self.edit(
                        game,
                        f"🏠 <b>Your team:</b> {esc(self.team_badge(team_key))}\n"
                        f"🤖 <b>Opponent:</b> {esc(self.team_badge(away_team))}\n\n"
                        f"{DIVIDER}\n"
                        "⏱ Choose the match length:",
                        self.overs_keyboard(),
                        parse_mode="HTML",
                    )
                    return
                game["stage"] = "away_team"
                self.edit(
                    game,
                    f"🏠 <b>Home team:</b> {esc(self.team_badge(team_key))} "
                    f"(captain: {esc(game['captain_names']['home'])})\n\n"
                    f"{DIVIDER}\n"
                    f"✈️ <b>{esc(game['captain_names']['away'])}</b>, choose the away team:",
                    self.team_keyboard("away", game.get("league")),
                    parse_mode="HTML",
                )
            else:
                game["stage"] = "overs"
                self.edit(
                    game,
                    f"🏠 <b>Home:</b> {esc(self.team_badge(game['teams']['home']))}\n"
                    f"✈️ <b>Away:</b> {esc(self.team_badge(team_key))}\n\n"
                    f"{DIVIDER}\n"
                    "⏱ Both teams are set. Host, choose the match length:",
                    self.overs_keyboard(),
                    parse_mode="HTML",
                )
            return

        # ---------------- Overs ----------------
        if data.startswith("overs:"):
            if game["stage"] != "overs" or user_id != game["host"]:
                self.answer_callback(callback_id, "Only the host can choose overs at this stage.")
                return
            try:
                game["overs_limit"] = int(data.partition(":")[2])
                create_match(game["overs_limit"])
            except ValueError:
                self.answer_callback(callback_id, "Choose a valid over limit.")
                return
            game["stage"] = "pitch"
            self.answer_callback(callback_id)
            self.edit(
                game,
                f"⏱ <b>{game['overs_limit']} overs</b> per innings\n\n"
                f"{DIVIDER}\n"
                "🏟 Choose the pitch for this match:",
                self.pitch_keyboard(),
                parse_mode="HTML",
            )
            return

        # ---------------- Pitch (now BEFORE the XI selection) ----------------
        if data.startswith("pitch:"):
            pitch = data.partition(":")[2]
            if game["stage"] != "pitch" or user_id != game["host"]:
                self.answer_callback(callback_id, "Only the host can choose the pitch at this stage.")
                return
            if pitch not in PITCHES:
                self.answer_callback(callback_id, "Choose a valid pitch.")
                return
            game["pitch"] = pitch
            game["stage"] = "home_xi"
            self.answer_callback(callback_id)
            self.edit(
                game,
                self.xi_prompt(
                    game,
                    "home",
                    header=(
                        f"🏟 <b>Pitch:</b> {esc(PITCHES[pitch]['name'])}  •  "
                        f"⏱ <b>{game['overs_limit']} overs</b>\n\n{DIVIDER}\n"
                    ),
                ),
                self.lineup_keyboard(game, "home"),
                parse_mode="HTML",
            )
            return

        # ---------------- XI selection ----------------
        if data.startswith("xi:"):
            _, side, raw_index = data.split(":", 2)
            if side not in ("home", "away") or game["stage"] != f"{side}_xi":
                self.answer_callback(callback_id, "That lineup selection is no longer active.")
                return
            if game["captains"][side] != user_id:
                self.answer_callback(callback_id, "Only that side's captain can select its XI.")
                return
            try:
                player_index = int(raw_index)
                roster_size = len(TEAMS[game["teams"][side]]["players"])
            except (ValueError, KeyError):
                self.answer_callback(callback_id, "Invalid player selection.")
                return
            if not 0 <= player_index < roster_size:
                self.answer_callback(callback_id, "Invalid player selection.")
                return
            lineup = self.normalize_lineup(game["lineups"].get(side))
            if player_index in lineup:
                lineup.remove(player_index)
            elif len(lineup) < 11:
                lineup.append(player_index)
            else:
                self.answer_callback(callback_id, "Your XI already has 11 players. Unselect one to change it.")
                return
            game["lineups"][side] = self.normalize_lineup(lineup)
            self.answer_callback(callback_id)
            self.edit(
                game,
                self.xi_prompt(game, side),
                self.lineup_keyboard(game, side),
                parse_mode="HTML",
            )
            return

        if data.startswith("xi-filter:"):
            _, side, mode = data.split(":", 2)
            if side not in ("home", "away") or game["stage"] != f"{side}_xi":
                self.answer_callback(callback_id, "That lineup selection is no longer active.")
                return
            if game["captains"][side] != user_id:
                self.answer_callback(callback_id, "Only that side's captain can use the role filter.")
                return
            if mode not in XI_FILTERS:
                self.answer_callback(callback_id, "Unknown role filter.")
                return
            game.setdefault("xi_filter", {})[side] = mode
            self.answer_callback(callback_id)
            self.edit(
                game,
                self.xi_prompt(game, side),
                self.lineup_keyboard(game, side),
                parse_mode="HTML",
            )
            return

        if data.startswith("xi-confirm:"):
            side = data.partition(":")[2]
            if side not in ("home", "away") or game["stage"] != f"{side}_xi":
                self.answer_callback(callback_id, "That lineup selection is no longer active.")
                return
            if game["captains"][side] != user_id:
                self.answer_callback(callback_id, "Only that side's captain can confirm its XI.")
                return
            valid_lineup = self.normalize_lineup(game["lineups"].get(side))
            if len(valid_lineup) != 11:
                self.answer_callback(callback_id, "Select exactly 11 players first.")
                return
            game["lineups"][side] = valid_lineup
            self.answer_callback(callback_id)
            if side == "home" and not game.get("vs_bot"):
                game["stage"] = "away_xi"
                self.edit(
                    game,
                    self.xi_prompt(game, "away", header="✅ <b>Home XI confirmed!</b>\n\n"),
                    self.lineup_keyboard(game, "away"),
                    parse_mode="HTML",
                )
                return
            # Vs bot (home confirmed) or away confirmed -> everything is ready.
            game["stage"] = "ready"
            self.edit(
                game,
                self.match_preview(game) + self.ready_prompt(game),
                self.ready_keyboard(game),
                parse_mode="HTML",
            )
            return

        if data in ("start-match", "start-match-over"):
            if game["stage"] != "ready" or user_id != game["host"]:
                self.answer_callback(callback_id, "Only the host can start the match.")
                return
            game["sim_mode"] = "over" if data == "start-match-over" else "ball"
            self.answer_callback(callback_id)
            game["innings_number"] = 1
            game["batting_side"] = game.get("first_batting", "home")
            game["results"] = []
            self.start_innings(game)
            return

        if data == "second-innings":
            if game["stage"] != "innings_break" or user_id != game["host"]:
                self.answer_callback(callback_id, "The host starts the second innings.")
                return
            self.answer_callback(callback_id)
            game["innings_number"] = 2
            game["batting_side"] = "away" if game["batting_side"] == "home" else "home"
            game["target"] = game["results"][0]["score"] + 1
            self.start_innings(game)
            return

        if data.startswith("bowler-mode:"):
            mode = data.partition(":")[2]
            if user_id != game["host"] or game["stage"] not in ("ready", "live"):
                self.answer_callback(callback_id, "🎳 Only the host can change the bowler mode, before or during the match.")
                return
            if mode not in BOWLER_MODE_LABEL:
                self.answer_callback(callback_id, "Unknown bowler mode.")
                return
            game["bowler_mode"] = mode
            self.answer_callback(callback_id)
            if game["stage"] == "live":
                innings = game["innings"]
                if mode == "auto" and game.get("phase") == "pick_bowler":
                    game["phase"] = "bat"
                elif (
                    mode == "manual"
                    and game.get("phase") == "bat"
                    and innings["match"]["balls"] % 6 == 0
                    and not innings.get("manual_bowler")
                ):
                    game["phase"] = "pick_bowler"
                self.advance_vs_bot_turn(game)
            else:
                self.refresh_game(game)
            return

        if data.startswith("pick-bowler:"):
            self.handle_bowler_pick(callback_id, game, user_id, data.partition(":")[2])
            return

        if data.startswith("sim-mode:"):
            mode = data.partition(":")[2]
            if game["stage"] != "live" or user_id != game["host"]:
                self.answer_callback(callback_id, "🎮 Only the host can switch the simulation mode during a live match.")
                return
            if mode not in SIM_MODE_LABEL:
                self.answer_callback(callback_id, "Unknown simulation mode.")
                return
            game["sim_mode"] = mode
            self.answer_callback(callback_id)
            self.render_scorecard(game)
            return

        if data.startswith("bat:"):
            self.handle_batting_choice(callback_id, game, user_id, data.partition(":")[2])
            return
        if data.startswith("bowl:"):
            self.handle_bowling_choice(callback_id, game, user_id, data.partition(":")[2])
            return

        self.answer_callback(callback_id, "Unknown action.")

    def match_preview(self, game: dict) -> str:
        home, away = game["teams"]["home"], game["teams"]["away"]
        home_team = TEAMS[home]
        away_team = TEAMS[away]
        lines = [
            f"🏏 <b>{esc(home_team.get('logo', '🏏'))} {esc(home_team['name'])} vs "
            f"{esc(away_team['name'])} {esc(away_team.get('logo', '🏏'))}</b>",
            DIVIDER,
            f"🎮 Mode: {'Vs Bot • ' if game.get('vs_bot') else ''}{esc(self.mode_badge(game.get('league')))}",
        ]
        toss = game.get("toss")
        if toss and toss.get("decision"):
            winner_team = TEAMS[game["teams"][toss["winner"]]]["name"]
            icon = "🏏" if toss["decision"] == "bat" else "🎳"
            lines.append(
                f"🪙 Toss: <b>{esc(winner_team)}</b> won and chose to {icon} {toss['decision']} first"
            )
        lines.append(f"👥 {len(game['lineups']['home'])} players selected for each side")
        for side, icon in (("home", "🏠"), ("away", "✈️")):
            counts = self.role_counts(game["teams"][side], game["lineups"][side])
            lines.append(
                f"{icon} XI: 🏏 {counts['BAT']}  🔄 {counts['AR']}  "
                f"🎳 {counts['BOWL']}  🧤 {counts['WK']}"
            )
        for side, icon in (("home", "🏠"), ("away", "✈️")):
            batting, bowling = self.xi_ratings(game["teams"][side], game["lineups"][side])
            lines.append(
                f"⭐ {icon} {esc(TEAMS[game['teams'][side]]['name'])}: "
                f"🏏 Bat <b>{batting}</b>  •  🎳 Bowl <b>{bowling}</b>"
            )
        lines.append(f"⏱ Format: <b>{game['overs_limit']} overs</b> per innings")
        lines.append(f"🏟 Pitch: <b>{esc(PITCHES[game['pitch']]['name'])}</b>")
        return "\n".join(lines) + "\n"

    @staticmethod
    def new_partnership() -> dict:
        return {"runs": 0, "balls": 0, "contrib": {}}

    @staticmethod
    def new_innings(lineup: list[str], overs_limit: int) -> dict:
        return {
            "match": create_match(overs_limit),
            "batters": [
                {"name": name, "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "out": False}
                for name in lineup
            ],
            "bowlers": {},
            "next_batter": 2,
            "striker": 0,
            "non_striker": 1,
            "bowler_rotation": [],
            "bowler_index": 0,
            "manual_bowler": None,
            "last_over_bowler": None,
            "dot_streak": 0,
            "sledges": [],
            "last_wicket": None,
            "commentary": [],
            "partnership": {"runs": 0, "balls": 0, "contrib": {}},
            "partnerships": [],
            "milestones": [],
            "milestone_alert": [],
        }

    def start_innings(self, game: dict) -> None:
        side = game["batting_side"]
        team_key = game["teams"][side]
        batting_xi = [TEAMS[team_key]["players"][index] for index in game["lineups"][side]]
        game["innings"] = self.new_innings(batting_xi, game["overs_limit"])
        bowling_side = self.bowling_side(game)
        bowling_team_key = game["teams"][bowling_side]
        bowling_xi = [TEAMS[bowling_team_key]["players"][index] for index in game["lineups"][bowling_side]]
        # Only bowlers and all-rounders bowl (falls back to everyone for odd XIs).
        bowling_options = [
            name for name in bowling_xi if player_role(name) in ("BOWL", "AR")
        ]
        rotation = bowling_options if len(bowling_options) >= 3 else bowling_xi
        game["innings"]["bowler_rotation"] = rotation
        game["innings"]["bowler_index"] = 0
        game["innings"]["last_bowler"] = rotation[0]
        game["stage"] = "live"
        game["phase"] = self.next_phase(game)
        self.advance_vs_bot_turn(game)

    def batting_side_name(self, game: dict) -> str:
        return TEAMS[game["teams"][game["batting_side"]]]["name"]

    def bowling_side(self, game: dict) -> str:
        return "away" if game["batting_side"] == "home" else "home"

    def innings_over(self, game: dict) -> bool:
        return is_match_over(game["innings"]["match"]) or (
            game["innings_number"] == 2 and game["innings"]["match"]["score"] >= game["target"]
        )

    def handle_batting_choice(self, callback_id: str, game: dict, user_id: int, style: str) -> None:
        if game.get("stage") == "live" and game.get("phase") == "pick_bowler":
            self.answer_callback(callback_id, "🎳 Wait: the bowling captain is picking the bowler.")
            return
        if game.get("stage") != "live" or game.get("phase") != "bat":
            self.answer_callback(callback_id, "Wait for the batting captain's turn.")
            return
        if game["captains"][game["batting_side"]] != user_id:
            self.answer_callback(callback_id, "Only the batting captain can choose this ball.")
            return
        if style not in BATTING_STYLES:
            self.answer_callback(callback_id, "Unknown batting style.")
            return
        game["batting_style"] = style
        game["phase"] = "bowl"
        self.answer_callback(callback_id)
        self.advance_vs_bot_turn(game)

    def handle_bowling_choice(self, callback_id: str, game: dict, user_id: int, style: str) -> None:
        if game.get("stage") != "live" or game.get("phase") != "bowl":
            self.answer_callback(callback_id, "Wait for the bowling captain's turn.")
            return
        side = self.bowling_side(game)
        if game["captains"][side] != user_id:
            self.answer_callback(callback_id, "Only the bowling captain can choose this ball.")
            return
        if style not in BOWLING_STYLES:
            self.answer_callback(callback_id, "Unknown bowling style.")
            return

        self.answer_callback(callback_id)
        self.play_turn(game, style)

    def ai_batting_style(self, game: dict) -> str:
        match = game["innings"]["match"]
        overs_left = max(0, game["overs_limit"] * 6 - match["balls"])
        if match["wickets"] >= 7:
            return "defensive"
        if game["innings_number"] == 2:
            runs_needed = max(0, game["target"] - match["score"])
            required_rate = runs_needed * 6 / overs_left if overs_left else float("inf")
            if required_rate >= 12:
                return "ultra"
            if required_rate >= 8:
                return "aggressive"
            return "gaps" if required_rate > 5 else "rotate"
        if overs_left <= 12:
            return "aggressive"
        return "gaps"

    def ai_bowling_style(self, game: dict) -> str:
        innings = game["innings"]
        match = innings["match"]
        current_rate = self.run_rate(match["score"], match["balls"])
        if game["pitch"] == "green":
            return "knuckle"
        if game["pitch"] == "spin":
            return "variation"
        if current_rate >= 9:
            return "defensive"
        if match["wickets"] >= 4:
            return "aggressive"
        return "variation"

    def advance_vs_bot_turn(self, game: dict) -> None:
        if game.get("stage") != "live" or not game.get("vs_bot"):
            self.render_scorecard(game)
            return
        if game["phase"] == "pick_bowler" and self.bowling_side(game) == "away":
            game["innings"]["manual_bowler"] = self.ai_pick_bowler(game)
            game["phase"] = "bat"
        if game["phase"] == "bat" and game["batting_side"] == "away":
            game["batting_style"] = self.ai_batting_style(game)
            game["phase"] = "bowl"
        elif game["phase"] == "bowl" and self.bowling_side(game) == "away":
            self.play_turn(game, self.ai_bowling_style(game))
            return
        self.render_scorecard(game)

    def play_turn(self, game: dict, style: str) -> None:
        """Play one ball or a whole over depending on the match's simulation mode."""
        if game.get("sim_mode") == "over":
            self.play_over(game, style)
        else:
            self.play_delivery(game, style)

    def play_delivery(self, game: dict, style: str) -> None:
        self._play_ball(game, style)
        self._after_turn(game)

    def _after_turn(self, game: dict) -> None:
        if self.innings_over(game):
            self.finish_innings(game)
        else:
            game["phase"] = self.next_phase(game)
            self.advance_vs_bot_turn(game)

    @staticmethod
    def ball_token(outcome: str, runs: int) -> str:
        if outcome == "wicket":
            return "W"
        return str(runs)

    def play_over(self, game: dict, bowling_style: str) -> None:
        """Simulate every remaining ball of the current over in one go."""
        innings = game["innings"]
        match = innings["match"]
        score_before = match["score"]
        wickets_before = match["wickets"]
        tokens: list[str] = []
        events: list[str] = []
        bowler_name = ""
        for _ in range(6):
            result = self._play_ball(game, bowling_style)
            tokens.append(self.ball_token(result["outcome"], result["runs"]))
            events.extend(result["events"])
            bowler_name = result["bowler"]
            if match["balls"] % 6 == 0 or self.innings_over(game):
                break
        innings["milestone_alert"] = events
        # Show only this over's ball-by-ball commentary (plus its end-of-over line).
        added = len(tokens) + (1 if match["balls"] % 6 == 0 and not is_match_over(match) else 0)
        innings["commentary"] = innings["commentary"][-added:]
        over_number = (match["balls"] - 1) // 6 + 1
        innings["last_over"] = {
            "number": over_number,
            "bowler": bowler_name,
            "runs": match["score"] - score_before,
            "wickets": match["wickets"] - wickets_before,
            "balls": tokens,
        }
        self._after_turn(game)

    def _play_ball(self, game: dict, style: str) -> dict:
        innings = game["innings"]
        match = innings["match"]
        side = self.bowling_side(game)
        bowler_team = TEAMS[game["teams"][side]]["players"]
        bowler_xi = [bowler_team[index] for index in game["lineups"][side]]
        rotation = innings.get("bowler_rotation") or bowler_xi
        current_index = innings.get("bowler_index", 0) % len(rotation)
        bowler_name = self.current_bowler_name(game)
        striker_name = innings["batters"][innings["striker"]]["name"]

        # Make sure older saved matches have the new tracking fields.
        innings.setdefault("partnership", self.new_partnership())
        innings["partnership"].setdefault("contrib", {})
        innings.setdefault("partnerships", [])
        innings.setdefault("milestones", [])

        score_before = match["score"]

        delivery = simulate_ball(
            match,
            game["batting_style"],
            style,
            self.match_modifiers(game, striker_name, bowler_name),
        )

        events: list[str] = []
        batter = innings["batters"][innings["striker"]]
        non_striker_name = innings["batters"][innings["non_striker"]]["name"]
        runs_before = batter["runs"]

        batter["balls"] += 1
        batter["runs"] += delivery["runs"]
        if delivery["runs"] == 4:
            batter["fours"] += 1
        elif delivery["runs"] == 6:
            batter["sixes"] += 1
        bowler = innings["bowlers"].setdefault(
            bowler_name, {"balls": 0, "runs": 0, "wickets": 0}
        )
        bowler["balls"] += 1
        bowler["runs"] += delivery["runs"]

        # --- Batter milestones: 50 / 100 / 150 / 200 ---
        for threshold, label in BATTER_MILESTONES.items():
            if runs_before < threshold <= batter["runs"]:
                events.append(
                    f"{label}: {batter['name']} reaches {threshold} off {batter['balls']} balls"
                )

        # --- Team milestones: 50 / 100 / 150 / 200 ... ---
        for threshold in TEAM_MILESTONES:
            if score_before < threshold <= match["score"]:
                events.append(f"📈 {self.batting_side_name(game)} reach {threshold}")

        # --- Partnership tracking ---
        partnership = innings["partnership"]
        partnership_before = partnership["runs"]
        partnership["runs"] += delivery["runs"]
        partnership["balls"] += 1
        contrib = partnership["contrib"]
        contrib[batter["name"]] = contrib.get(batter["name"], 0) + delivery["runs"]
        contrib.setdefault(non_striker_name, 0)
        for threshold in PARTNERSHIP_MILESTONES:
            if partnership_before < threshold <= partnership["runs"]:
                events.append(
                    f"🤝 {threshold}-run partnership: {batter['name']} & {non_striker_name}"
                )

        if delivery["outcome"] == "wicket":
            batter["out"] = True
            bowler["wickets"] += 1
            innings["last_wicket"] = batter["name"]

            # --- Bowler milestones: 3-wicket haul / 5-wicket haul ---
            if bowler["wickets"] in BOWLER_MILESTONES:
                events.append(
                    f"{BOWLER_MILESTONES[bowler['wickets']]}: {bowler_name} "
                    f"{bowler['wickets']}/{bowler['runs']}"
                )

            # --- Close the partnership ---
            innings["partnerships"].append({
                "wicket": match["wickets"],
                "runs": partnership["runs"],
                "balls": partnership["balls"],
                "pair": [batter["name"], non_striker_name],
                "contrib": dict(contrib),
                "unbroken": False,
            })
            innings["partnership"] = self.new_partnership()

            if innings["next_batter"] < len(innings["batters"]):
                innings["striker"] = innings["next_batter"]
                innings["next_batter"] += 1
            if match["balls"] % 6 == 0:
                innings["striker"], innings["non_striker"] = (
                    innings["non_striker"],
                    innings["striker"],
                )
        else:
            if delivery["runs"] % 2:
                innings["striker"], innings["non_striker"] = (
                    innings["non_striker"],
                    innings["striker"],
                )
            if match["balls"] % 6 == 0:
                innings["striker"], innings["non_striker"] = (
                    innings["non_striker"],
                    innings["striker"],
                )

        commentary = self.ball_commentary(
            bowler_name,
            batter["name"],
            delivery["outcome"],
            delivery["runs"],
            variant=match["balls"] - 1,
        )
        innings["last_ball"] = (
            f"{BATTING_STYLES[game['batting_style']]['label']} vs "
            f"{BOWLING_STYLES[style]['label']}: {OUTCOME_TEXT[delivery['outcome']]}"
        )
        innings["commentary"].append({"over": delivery["over"], "text": commentary})
        if match["balls"] % 6 == 0 and not is_match_over(match):
            innings["commentary"].append({
                "over": format_overs(match["balls"]),
                "text": (
                    f"⏱ End of over {match['balls'] // 6}: "
                    f"{match['score']}/{match['wickets']}  •  "
                    f"RR {self.run_rate(match['score'], match['balls']):.2f}"
                ),
            })
        del innings["commentary"][: -(8 if game.get("sim_mode") == "over" else 6)]
        self.add_sledge(game, delivery["outcome"], bowler_name, batter["name"], delivery["over"])

        # Milestone alert for this ball + permanent milestone log.
        innings["milestone_alert"] = events
        for event in events:
            innings["milestones"].append({"over": delivery["over"], "text": event})
        del innings["milestones"][:-40]

        innings["last_bowler"] = bowler_name
        if match["balls"] % 6 == 0:
            innings["bowler_index"] = (innings.get("bowler_index", 0) + 1) % len(rotation)
            innings["manual_bowler"] = None
            innings["last_over_bowler"] = bowler_name
        else:
            innings["bowler_index"] = current_index

        return {
            "outcome": delivery["outcome"],
            "runs": delivery["runs"],
            "events": events,
            "bowler": bowler_name,
        }

    @staticmethod
    def ball_commentary(
        bowler: str, batter: str, outcome: str, runs: int, variant: int = 0
    ) -> str:
        key = outcome
        if outcome not in ("wicket", "six", "four", "dot"):
            key = "one" if runs == 1 else "two"
        templates = COMMENTARY_TEMPLATES[key]
        line = templates[variant % len(templates)].format(
            bowler=bowler, batter=batter, runs=runs
        )
        return f"{OUTCOME_ICON.get(outcome, '🟢')} {line}"

    @staticmethod
    def match_result_text(game: dict) -> str:
        first, second = game["results"]
        if second["score"] > first["score"]:
            margin = 10 - second["wickets"]
            return f"{second['team']} win by {margin} wickets!"
        if second["score"] < first["score"]:
            return f"{first['team']} win by {first['score'] - second['score']} runs!"
        return "The match is tied!"

    def finish_innings(self, game: dict) -> None:
        innings = game["innings"]
        match = innings["match"]
        side = game["batting_side"]

        # An unbroken partnership at the end of the innings still counts.
        partnership = innings.get("partnership")
        if partnership and partnership.get("balls") and match["wickets"] < 10:
            striker = innings["batters"][innings["striker"]]["name"]
            non_striker = innings["batters"][innings["non_striker"]]["name"]
            innings.setdefault("partnerships", []).append({
                "wicket": match["wickets"] + 1,
                "runs": partnership["runs"],
                "balls": partnership["balls"],
                "pair": [striker, non_striker],
                "contrib": dict(partnership.get("contrib", {})),
                "unbroken": True,
            })
            innings["partnership"] = self.new_partnership()

        partnerships = innings.get("partnerships", [])
        best_partnership = max(partnerships, key=lambda p: p["runs"], default=None)

        game["results"].append({
            "side": side,
            "team": TEAMS[game["teams"][side]]["name"],
            "score": match["score"],
            "wickets": match["wickets"],
            "balls": match["balls"],
            "milestones": [item["text"] for item in innings.get("milestones", [])],
            "best_partnership": best_partnership,
        })
        if game["innings_number"] == 1:
            game["stage"] = "innings_break"
            self.render_scorecard(game)
            return

        game["stage"] = "complete"
        self.render_scorecard(game, self.match_result_text(game))

    @staticmethod
    def run_rate(runs: int, balls: int) -> float:
        return runs * 6 / balls if balls else 0.0

    @staticmethod
    def batter_strike_rate(batter: dict) -> float:
        return batter["runs"] * 100 / batter["balls"] if batter["balls"] else 0.0

    @staticmethod
    def batter_badge(runs: int) -> str:
        if runs >= 200:
            return " 👑"
        if runs >= 150:
            return " 🚀"
        if runs >= 100:
            return " 💯"
        if runs >= 50:
            return " 🔥"
        return ""

    @staticmethod
    def bowler_badge(wickets: int) -> str:
        if wickets >= 5:
            return " 🏆5W"
        if wickets >= 3:
            return " 🎳3W"
        return ""

    def match_net_run_rates(self, game: dict) -> dict[str, float] | None:
        if len(game.get("results", [])) != 2:
            return None

        results = {result["side"]: result for result in game["results"]}
        net_run_rates = {}
        for side in ("home", "away"):
            batting = results[side]
            bowling = results["away" if side == "home" else "home"]
            batting_overs = (
                game["overs_limit"] if batting["wickets"] == 10 else batting["balls"] / 6
            )
            bowling_overs = (
                game["overs_limit"] if bowling["wickets"] == 10 else bowling["balls"] / 6
            )
            net_run_rates[side] = (
                self.run_rate(batting["score"], batting_overs * 6)
                - self.run_rate(bowling["score"], bowling_overs * 6)
            )
        return net_run_rates

    def scorecard_text(
        self,
        game: dict,
        final_result: str | None = None,
        compact: bool = False,
    ) -> str:
        escape = html.escape
        innings = game["innings"]
        match = innings["match"]
        team_name = self.batting_side_name(game)
        overs = game["overs_limit"]
        striker = innings["batters"][innings["striker"]]
        non_striker = innings["batters"][innings["non_striker"]]
        rotation = innings.get("bowler_rotation") or []
        current_index = innings.get("bowler_index", 0) % len(rotation) if rotation else 0
        pick_pending = game["stage"] == "live" and game.get("phase") == "pick_bowler"
        current_bowler = self.current_bowler_name(game)
        next_bowler = rotation[(current_index + 1) % len(rotation)] if rotation else "To be assigned"
        bowler_stats = innings["bowlers"].get(
            current_bowler, {"balls": 0, "runs": 0, "wickets": 0}
        )
        current_run_rate = self.run_rate(match["score"], match["balls"])
        # Traffic-light colour for the score: green = healthy, red = in trouble.
        if match["wickets"] <= 3:
            score_icon = "🟢"
        elif match["wickets"] <= 6:
            score_icon = "🟡"
        else:
            score_icon = "🔴"

        lines = [
            f"🏏 <b>{escape(TEAMS[game['teams']['home']]['name'])} vs "
            f"{escape(TEAMS[game['teams']['away']]['name'])}</b>",
            DIVIDER,
            f"✨ <b>{game['innings_number']}{'st' if game['innings_number'] == 1 else 'nd'} INNINGS</b>"
            f"  •  {escape(team_name)}",
            "",
            f"{score_icon} <b>Score: {match['score']}/{match['wickets']} "
            f"({format_overs(match['balls'])}/{overs} overs)</b>",
            f"📈 <b>Run rate (RR/CRR): {current_run_rate:.2f} runs/over</b>",
        ]
        if game.get("target"):
            runs_needed = max(0, game["target"] - match["score"])
            balls_remaining = max(0, overs * 6 - match["balls"])
            required_run_rate = (
                runs_needed * 6 / balls_remaining if balls_remaining else 0.0
            )
            lines.append(
                f"🎯 <b>Target: {game['target']}</b>  •  Need <b>{runs_needed}</b> runs "
                f"from <b>{balls_remaining}</b> balls"
            )
            lines.append(f"⚡ <b>Required RR (RRR): {required_run_rate:.2f}</b>")
        for index, result in enumerate(game.get("results", []), start=1):
            lines.append(
                f"📋 {index}{'st' if index == 1 else 'nd'} innings: "
                f"{escape(result['team'])} <b>{result['score']}/{result['wickets']}</b> "
                f"<code>({format_overs(result['balls'])}/{overs} overs)</code>"
            )
        lines.append("")
        lines.append(f"🏟 Pitch: {escape(PITCHES[game['pitch']]['name'])}")
        lines.append(f"🎮 Mode: {SIM_MODE_LABEL.get(game.get('sim_mode', 'ball'), SIM_MODE_LABEL['ball'])}")
        toss = game.get("toss")
        if toss and toss.get("decision") and not compact:
            winner_team = TEAMS[game["teams"][toss["winner"]]]["name"]
            toss_icon = "🏏" if toss["decision"] == "bat" else "🎳"
            lines.append(
                f"🪙 Toss: {escape(winner_team)} won, chose to {toss_icon} {toss['decision']}"
            )

        # Live milestone banner for the ball just played.
        if game["stage"] == "live":
            alerts = innings.get("milestone_alert", [])
            if alerts:
                lines.append("")
            for alert in alerts:
                lines.append(f"🎉 <b>{escape(alert)}</b>")

        lines.append(f"\n{DIVIDER}")
        lines.append(
            f"🏏 <b>Strike:</b> {escape(striker['name'])}* "
            f"<b>{striker['runs']}({striker['balls']})</b>{self.batter_badge(striker['runs'])}"
            f" ⭐{bat_rating(striker['name'])}"
        )
        lines.append(
            f"🧍 <b>Non-striker:</b> {escape(non_striker['name'])} "
            f"<b>{non_striker['runs']}({non_striker['balls']})</b>{self.batter_badge(non_striker['runs'])}"
            f" ⭐{bat_rating(non_striker['name'])}"
        )
        lines.append(
            f"⚡ <b>Batting SR: {self.batter_strike_rate(striker):.2f} | "
            f"Non-striker SR: {self.batter_strike_rate(non_striker):.2f}</b>"
        )

        # Current partnership.
        partnership = innings.get("partnership") or self.new_partnership()
        contrib = partnership.get("contrib", {})
        lines.append("")
        lines.append(
            f"🤝 <b>Partnership:</b> <b>{partnership['runs']}</b> runs "
            f"({partnership['balls']} balls) "
            f"<code>{escape(striker['name'])} {contrib.get(striker['name'], 0)}"
            f" • {escape(non_striker['name'])} {contrib.get(non_striker['name'], 0)}</code>"
        )

        lines.append("")
        if pick_pending:
            lines.append("🎳 <b>Current bowler:</b> ⏳ waiting for the bowling captain's pick")
        else:
            lines.append(
                f"🎳 <b>Current bowler:</b> {escape(current_bowler)} "
                f"<code>{format_overs(bowler_stats['balls'])}-{bowler_stats['runs']}-{bowler_stats['wickets']}</code>"
                f"{self.bowler_badge(bowler_stats['wickets'])} "
                f"(Econ {self.run_rate(bowler_stats['runs'], bowler_stats['balls']):.2f})"
                f" ⭐{bowl_rating(current_bowler)}"
            )
        if game.get("bowler_mode") == "manual":
            lines.append("⏭ <b>Next bowler:</b> picked by the bowling captain each over")
        else:
            lines.append(f"⏭ <b>Next bowler:</b> {escape(next_bowler)}")
        if innings.get("last_wicket"):
            lines.append(f"🧤 Last wicket: {escape(innings['last_wicket'])}")
        if innings.get("last_ball"):
            lines.append(f"💥 Last ball: {escape(innings['last_ball'])}")
        last_over = innings.get("last_over")
        if last_over and game.get("sim_mode") == "over" and game["stage"] in ("live", "innings_break", "complete"):
            lines.append(f"\n{DIVIDER}")
            lines.append(
                f"📦 <b>OVER {last_over['number']} SUMMARY</b>  •  🎳 {escape(last_over['bowler'])}"
            )
            over_icon = "🔴" if last_over["wickets"] else ("🟢" if last_over["runs"] >= 8 else "⚪")
            lines.append(
                f"{over_icon} <b>{last_over['runs']} runs</b>  •  "
                f"<b>{last_over['wickets']} wkt{'s' if last_over['wickets'] != 1 else ''}</b>"
            )
            lines.append("<code>" + "  ".join(last_over["balls"]) + "</code>")
        commentary = innings.get("commentary", [])
        if commentary and not compact:
            lines.append(f"\n{DIVIDER}")
            lines.append("🎙 <b>BALL-BY-BALL COMMENTARY</b>\n")
            for position, item in enumerate(commentary):
                text = escape(item["text"])
                if position == len(commentary) - 1:
                    lines.append(f"👉 <code>{escape(item['over'])}</code> <b>{text}</b>")
                else:
                    lines.append(f"▫️ <code>{escape(item['over'])}</code> {text}")
        sledges = innings.get("sledges", [])
        if sledges and game.get("sledging", True) and not compact:
            lines.append(f"\n{DIVIDER}")
            lines.append("🗣 <b>SLEDGING</b>\n")
            for item in sledges:
                lines.append(
                    f"🗣 <b>{escape(item['from'])}</b> → {escape(item['to'])}: "
                    f"<i>“{escape(item['text'])}”</i>"
                )
        lines.append(f"\n{DIVIDER}")
        lines.append("📊 <b>BATTERS</b>  <code>R(B)   4s 6s</code>\n")
        for index, batter in enumerate(innings["batters"]):
            if (
                batter["balls"] == 0
                and not batter["out"]
                and index not in (innings["striker"], innings["non_striker"])
            ):
                continue
            marker = "*" if index == innings["striker"] and not batter["out"] else ""
            if batter["out"]:
                marker = " out"
                icon = "🔴"
            elif index == innings["striker"]:
                icon = "🟢"
            else:
                icon = "🔵"
            lines.append(
                f"{icon} {escape(batter['name'])}{marker}  <b>{batter['runs']}({batter['balls']})</b>"
                f"   {batter['fours']}  {batter['sixes']}{self.batter_badge(batter['runs'])}"
            )
        lines.append(f"\n{DIVIDER}")
        lines.append("🎯 <b>BOWLING</b>\n")
        if innings["bowlers"]:
            for name, stats in innings["bowlers"].items():
                lines.append(
                    f"🎳 {escape(name)}: "
                    f"<code>{format_overs(stats['balls'])}-{stats['runs']}-{stats['wickets']}</code>"
                    f"{self.bowler_badge(stats['wickets'])}"
                )
        else:
            lines.append("No balls bowled yet.")

        if not final_result and not compact:
            # Completed partnerships for the live / break view.
            partnerships = innings.get("partnerships", [])
            if partnerships:
                lines.append(f"\n{DIVIDER}")
                lines.append("🤝 <b>PARTNERSHIPS</b>\n")
                for item in partnerships[-10:]:
                    suffix = "*" if item.get("unbroken") else ""
                    lines.append(
                        f"▫️ {self.ordinal(item['wicket'])} wkt: "
                        f"{escape(item['pair'][0])} &amp; {escape(item['pair'][1])} "
                        f"<b>{item['runs']}{suffix}</b>({item['balls']})"
                    )
            # Milestone log.
            milestones = innings.get("milestones", [])
            if milestones:
                lines.append(f"\n{DIVIDER}")
                lines.append("🏅 <b>MILESTONES</b>\n")
                for item in milestones[-5:]:
                    lines.append(f"▫️ <code>{escape(item['over'])}</code> {escape(item['text'])}")

        if game["stage"] == "innings_break":
            lines.append(f"\n{DIVIDER}")
            lines.append("⏸ <b>INNINGS BREAK</b>\n")
            lines.append(f"Innings complete: <b>{match['score']}/{match['wickets']}</b>.")
            lines.append(f"🎯 Target to chase: <b>{match['score'] + 1}</b>")
            lines.append("The other captain will chase.")
        elif final_result:
            lines.append(f"\n{DIVIDER}")
            lines.append("🏆 <b>MATCH RESULT</b>\n")
            lines.append(f"🏁 <b>{escape(final_result)}</b>")
            if not compact:
                # Match-wide highlights from both innings.
                for number, result in enumerate(game.get("results", []), start=1):
                    highlights = result.get("milestones") or []
                    best = result.get("best_partnership")
                    if not highlights and not best:
                        continue
                    lines.append(
                        f"\n<b>🏅 {self.ordinal(number)} INNINGS HIGHLIGHTS</b> "
                        f"({escape(result['team'])})"
                    )
                    if best:
                        lines.append(
                            f"🤝 Best partnership: {escape(best['pair'][0])} &amp; "
                            f"{escape(best['pair'][1])} <b>{best['runs']}</b>({best['balls']})"
                            f"{'*' if best.get('unbroken') else ''}"
                        )
                    for text in highlights[-6:]:
                        lines.append(f"▫️ {escape(text)}")
            net_run_rates = self.match_net_run_rates(game)
            if net_run_rates is not None:
                lines.append(f"\n{DIVIDER}")
                lines.append("🏆 <b>MATCH NET RUN RATE (NRR)</b>")
                home_nrr = net_run_rates["home"]
                away_nrr = net_run_rates["away"]
                if home_nrr == away_nrr:
                    lines.append("🤝 Net run rate is tied")
                    lines.append(
                        f"{escape(self.team_badge(game['teams']['home']))}: <b>{home_nrr:+.2f}</b>"
                    )
                    lines.append(
                        f"{escape(self.team_badge(game['teams']['away']))}: <b>{away_nrr:+.2f}</b>"
                    )
                else:
                    leading_side = "home" if home_nrr > away_nrr else "away"
                    trailing_side = "away" if leading_side == "home" else "home"
                    lines.append(
                        f"🟢🥇 <b>Best NRR:</b> "
                        f"{escape(self.team_badge(game['teams'][leading_side]))} "
                        f"<b>{net_run_rates[leading_side]:+.2f}</b>"
                    )
                    lines.append(
                        f"🔴 {escape(self.team_badge(game['teams'][trailing_side]))} "
                        f"<b>{net_run_rates[trailing_side]:+.2f}</b>"
                    )
                lines.append(DIVIDER)
        elif game["stage"] == "live":
            active_side = game["batting_side"] if game["phase"] == "bat" else self.bowling_side(game)
            role = "Batting" if game["phase"] == "bat" else "Bowling"
            role_icon = "🏏" if game["phase"] == "bat" else "🎳"
            captain = game["captain_names"][active_side]
            lines.append(f"\n{DIVIDER}")
            lines.append(f"🎮 <b>{role} captain:</b> {escape(captain)}")
            over_note = " (applies to the whole over)" if game.get("sim_mode") == "over" else ""
            if game["phase"] == "pick_bowler":
                lines.extend(self.bowler_pick_text(game))
            else:
                lines.append(
                    f"{role_icon} <b>Choose batting approach:</b>{over_note}"
                    if game["phase"] == "bat"
                    else f"{role_icon} <b>Choose bowling style:</b>{over_note}"
                )
        return "\n".join(lines)

    def live_keyboard(self, game: dict) -> list | None:
        if game["stage"] == "innings_break":
            return [[self.button("▶️ Start second innings", "second-innings")]]
        if game["stage"] != "live":
            return None
        if game["phase"] == "pick_bowler":
            keyboard = self.bowler_keyboard(game)
        elif game["phase"] == "bat":
            keyboard = self.batting_keyboard()
        else:
            keyboard = self.bowling_keyboard()
        if game.get("sim_mode") == "over":
            switch = [self.button("🎯 Switch to ball by ball", "sim-mode:ball")]
        else:
            switch = [self.button("⚡ Switch to over by over", "sim-mode:over")]
        return keyboard + [switch, [self.bowler_mode_button(game)]]

    def render_scorecard(self, game: dict, final_result: str | None = None) -> None:
        text = self.scorecard_text(game, final_result)
        if len(text) > SCORECARD_SAFE_LENGTH:
            # Telegram messages are capped at 4096 characters; fall back to a compact card.
            text = self.scorecard_text(game, final_result, compact=True)
        self.edit(
            game,
            text,
            self.live_keyboard(game),
            parse_mode="HTML",
        )

    def refresh_game(self, game: dict) -> None:
        stage = game.get("stage")
        if stage == "join":
            self.edit(
                game,
                self.lobby_text(game),
                [[self.button("🧢 Join as away captain", "join")]],
                parse_mode="HTML",
            )
            return
        if stage == "toss_call":
            self.edit(game, self.toss_prompt(game), self.toss_call_keyboard(), parse_mode="HTML")
            return
        if stage == "toss_decision":
            self.edit(
                game,
                self.toss_decision_prompt(game),
                self.toss_choice_keyboard(),
                parse_mode="HTML",
            )
            return
        if stage == "home_team":
            self.edit(
                game,
                f"{self.toss_summary(game)}\n\n{DIVIDER}\n"
                f"🏠 <b>{esc(game['captain_names']['home'])}</b>, choose the home team "
                f"({esc(self.league_name(game['league']))} mode):",
                self.team_keyboard("home", game.get("league")),
                parse_mode="HTML",
            )
            return
        if stage == "away_team":
            self.edit(
                game,
                f"🏠 <b>Home team:</b> {esc(self.team_badge(game['teams']['home']))}\n\n{DIVIDER}\n"
                f"✈️ <b>{esc(game['captain_names']['away'])}</b>, choose the away team:",
                self.team_keyboard("away", game.get("league")),
                parse_mode="HTML",
            )
            return
        if stage == "overs":
            self.edit(
                game,
                "⏱ Both teams are set. Host, choose the match length:",
                self.overs_keyboard(),
                parse_mode="HTML",
            )
            return
        if stage == "pitch":
            self.edit(game, "🏟 Choose the pitch for this match:", self.pitch_keyboard(), parse_mode="HTML")
            return
        if stage == "home_xi":
            self.edit(
                game,
                self.xi_prompt(game, "home"),
                self.lineup_keyboard(game, "home"),
                parse_mode="HTML",
            )
            return
        if stage == "away_xi":
            self.edit(
                game,
                self.xi_prompt(game, "away"),
                self.lineup_keyboard(game, "away"),
                parse_mode="HTML",
            )
            return
        if stage == "ready":
            self.edit(
                game,
                self.match_preview(game) + self.ready_prompt(game),
                self.ready_keyboard(game),
                parse_mode="HTML",
            )
            return
        if stage in ("live", "innings_break", "complete"):
            final_result = self.match_result_text(game) if stage == "complete" else None
            self.render_scorecard(game, final_result)
            return
        self.reply(game["chat_id"], "This screen cannot be refreshed right now.")

    def handle_update(self, update: dict) -> None:
        try:
            message = update.get("message")
            if message:
                self.handle_message(message)
                return
            callback = update.get("callback_query")
            if callback:
                self.handle_callback(callback)
        finally:
            self.persist_sessions()

    def create_webhook_server(self, webhook_secret: str) -> HTTPServer:
        bot = self

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/health":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"ok")

            def do_POST(self) -> None:
                if self.path != "/telegram":
                    self.send_error(404)
                    return
                provided_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
                if not hmac.compare_digest(provided_secret, webhook_secret):
                    self.send_error(403)
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self.send_error(400)
                    return
                if content_length <= 0 or content_length > 1_000_000:
                    self.send_error(413)
                    return
                try:
                    update = json.loads(self.rfile.read(content_length))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.send_error(400)
                    return
                if not isinstance(update, dict):
                    self.send_error(400)
                    return
                try:
                    bot.handle_update(update)
                except (RuntimeError, URLError, KeyError, ValueError) as error:
                    print(f"Could not handle Telegram webhook update: {error}", file=sys.stderr)
                    if "HTTP 429" in str(error):
                        self.send_response(200)
                        self.end_headers()
                        return
                    self.send_error(500)
                    return
                self.send_response(200)
                self.end_headers()

        return HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), WebhookHandler)

    def run_webhook(self, hostname: str) -> None:
        webhook_secret = secrets.token_urlsafe(32)
        server = self.create_webhook_server(webhook_secret)
        try:
            self.api(
                "setWebhook",
                {
                    "url": f"https://{hostname}/telegram",
                    "secret_token": webhook_secret,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            print("Cricket Simulator bot is running with Telegram webhooks.", flush=True)
            server.serve_forever()
        finally:
            server.server_close()

    def set_command_menu(self) -> None:
        commands = [
            ("playint", "🌍 Start an international match (group)"),
            ("playipl", "🏆 Start an IPL match (group)"),
            ("vsbot", "🤖 Play international cricket vs the bot"),
            ("vsbotipl", "🤖 Play IPL cricket vs the bot"),
            ("toss", "🪙 Show the toss"),
            ("sledge", "🗣 Turn sledging on or off (host)"),
            ("refresh", "🔄 Redraw the live board"),
            ("cancel", "❌ Cancel the match (host only)"),
            ("ping", "🟢 Check the bot is online"),
            ("members", "👥 Group member count"),
            ("help", "📖 How to play"),
        ]
        try:
            self.api(
                "setMyCommands",
                {"commands": [{"command": name, "description": text} for name, text in commands]},
            )
        except (RuntimeError, URLError, TimeoutError) as error:
            print(f"Could not register the command menu: {error}", file=sys.stderr)

    def run(self) -> None:
        bot_info = self.api("getMe")
        self.username = bot_info.get("username")
        if not self.username:
            raise RuntimeError("Telegram getMe did not return this bot's username.")
        self.set_command_menu()
        hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
        if hostname:
            self.run_webhook(hostname)
            return
        try:
            pending = self.api(
                "getUpdates",
                {
                    "offset": -1,
                    "timeout": 0,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            if pending:
                self.offset = pending[-1]["update_id"] + 1
        except (RuntimeError, URLError, TimeoutError) as error:
            print(f"Could not clear stale Telegram updates at startup: {error}", file=sys.stderr)
        print("Cricket Simulator bot is running.", flush=True)
        while True:
            try:
                updates = self.api(
                    "getUpdates",
                    {
                        "offset": self.offset,
                        "timeout": POLL_TIMEOUT,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )
                for update in updates:
                    self.offset = update["update_id"] + 1
                    try:
                        self.handle_update(update)
                    except (RuntimeError, URLError, KeyError, ValueError) as error:
                        print(f"Could not handle Telegram update {update['update_id']}: {error}", file=sys.stderr)
            except (RuntimeError, URLError, TimeoutError) as error:
                print(f"Telegram polling error: {error}. Retrying in 5 seconds.", file=sys.stderr)
                time.sleep(5)


def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or token == "put_your_bot_token_here":
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your environment or .env file before starting the bot.")
    TelegramBot(token).run()


if __name__ == "__main__":
    main()
