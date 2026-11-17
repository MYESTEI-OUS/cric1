"""Group multiplayer cricket bot implemented with Python's standard library."""

import copy
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

from .awards import compute_awards, format_awards_message
from .game import (
    BATTING_STYLES,
    BOWLING_STYLES,
    DISMISSAL_WEIGHTS,
    OUTCOMES,
    create_match,
    format_overs,
    is_match_over,
    pick_dismissal,
    rating_modifiers,
    roll_extra,
    simulate_ball,
)
from .scorecard_png import render_scorecard_png
from .stats import StatsStore
from .teams import PITCHES, TEAMS, bat_rating, bowl_rating, player_role

API_BASE = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 5
esc = html.escape
DIVIDER = "━━━━━━━━━━━━━━━━━━"
OUTCOME_TEXT = {
    "bye": "🟢 Bye! One run to the total.",
    "wicket": "🔴 OUT! The bowler gets the breakthrough.",
    "dot": "⚪ Dot ball.",
    "one": "🟢 1 run.",
    "two": "🟢 2 runs.",
    "four": "🔵 FOUR!",
    "six": "🟣 SIX!",
}
# Colour dot shown in front of every commentary line.
OUTCOME_ICON = {
    "bye": "🟢",
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
    "bye": (
        "Bye! {bowler} beats everyone, the keeper misses it and they sneak a run.",
        "Misfield... no, it's a bye! A run the batters didn't earn.",
        "Beaten all ends up! It runs away for a bye.",
    ),
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
# Extras (wides / no-balls) and fielding moments.
EXTRA_COMMENTARY = {
    "wide": (
        "🟡 WIDE! {bowler} strays down the leg side. +1 run.",
        "🟡 WIDE! Too much width from {bowler}. +1 run.",
        "🟡 WIDE! {bowler} loses his line. +1 run.",
    ),
    "no_ball": (
        "🟠 NO BALL! {bowler} oversteps. +1 run and a FREE HIT next ball!",
        "🟠 NO BALL! Big front-foot no-ball from {bowler}. FREE HIT coming up!",
    ),
}
# Chance (0-1) that a DRS review overturns each kind of dismissal.
DRS_SUCCESS = {"lbw": 0.35, "caught": 0.22, "stumped": 0.18, "bowled": 0.03}
DRS_REASONS = {
    "lbw": ("Ball tracking shows it clipping leg stump... but umpire's call.", "Ball tracking: it was going over the stumps!"),
    "caught": ("UltraEdge shows a clear spike. The catch stands.", "UltraEdge: no bat involved, it was pad/air!"),
    "stumped": ("Foot was dragging on the line. Out.", "Replay shows the foot was grounded in time!"),
    "bowled": ("Hawk-Eye confirms the stumps were hit.", "The bails never fell. Not out!"),
}
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
            database_path
            or os.environ.get("BOT_DATABASE_PATH")
            or Path(__file__).resolve().parent.parent / "bot_state.sqlite3"
        )
        self.database.execute(
            "CREATE TABLE IF NOT EXISTS matches (chat_id INTEGER PRIMARY KEY, game_json TEXT NOT NULL)"
        )
        self.stats = StatsStore(self.database)
        self.admin_ids = {
            int(part) for part in os.environ.get("ADMIN_USER_IDS", "").replace(" ", "").split(",")
            if part.lstrip("-").isdigit()
        }
        # Game rules that the admin can tune with /admin set.
        self.rules = {
            "wide": 0.035,
            "no_ball": 0.012,
            "bye": 0.02,
            "drop_catch": 0.12,
            "drs_reviews": 2,
            "dismissals": dict(DISMISSAL_WEIGHTS),
        }
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
        return self._read_response(method, request)

    def api_upload(self, method: str, fields: dict, file_field: str, filename: str, data: bytes):
        """Call a Telegram method with a file attached (multipart upload)."""
        boundary = "cricketbot" + secrets.token_hex(12)
        body = bytearray()
        for key, value in fields.items():
            body += (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            ).encode("utf-8")
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'
        ).encode("utf-8")
        body += data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = Request(
            API_BASE.format(token=self.token, method=method),
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        return self._read_response(method, request)

    def _read_response(self, method: str, request: Request):
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

    def is_chat_admin(self, chat_id: int, user_id: int | None) -> bool:
        if not user_id or chat_id > 0:
            return False
        try:
            member = self.api("getChatMember", {"chat_id": chat_id, "user_id": user_id})
        except (RuntimeError, URLError, TimeoutError):
            return False
        return isinstance(member, dict) and member.get("status") in ("administrator", "creator")

    def profile_text(self, user: dict) -> str:
        user_id = user.get("id")
        profile = self.stats.captain_profile(user_id) if user_id else None
        spectator = self.stats.spectator_profile(user_id) if user_id else None
        name = esc((profile or spectator or {}).get("name") or self.player_label(user))
        if not profile and not spectator:
            return (
                f"👤 <b>{name}</b>\n\nNo matches recorded yet.\n"
                "Play one with /playint, /playipl or /vsbot, and your profile builds as you play!"
            )
        lines = ["👤 <b>CAPTAIN PROFILE</b>", f"🏏 <b>{name}</b>", DIVIDER]
        if profile:
            matches = profile["matches"]
            win_rate = round(100 * profile["wins"] / matches) if matches else 0
            title = "🥇 Legend" if profile["wins"] >= 10 else "🥈 Pro" if profile["wins"] >= 3 else "🥉 Rookie"
            lines += [
                f"🎖 Rank: <b>{title}</b>",
                "",
                f"🎮 Matches: <b>{matches}</b>",
                f"🏆 Wins <b>{profile['wins']}</b>  •  ❌ Losses <b>{profile['losses']}</b>  •  🤝 Ties <b>{profile['ties']}</b>",
                f"📈 Win rate: <b>{win_rate}%</b>",
                "",
                f"💥 Highest total: <b>{profile['highest_total']}</b>",
                f"🏏 Runs scored: <b>{profile['runs_for']}</b>  •  🛡 Conceded: <b>{profile['runs_against']}</b>",
                f"🪙 Toss wins: <b>{profile['toss_wins']}</b>",
                f"🌟 Player of the Match awards: <b>{profile['potm']}</b>",
                f"⚡ Super Overs: <b>{profile['super_overs']}</b>",
            ]
            if profile["drs_used"]:
                pct = round(100 * profile["drs_success"] / profile["drs_used"])
                lines.append(f"📺 DRS: <b>{profile['drs_success']}/{profile['drs_used']}</b> successful ({pct}%)")
        if spectator:
            lines += [
                "",
                f"🔮 <b>Spectator:</b> {spectator['points']} points  •  "
                f"{spectator['correct']}/{spectator['predictions']} correct predictions",
            ]
        return "\n".join(lines)

    def stats_text(self) -> str:
        medals = ["🥇", "🥈", "🥉", "4.", "5."]
        lines = ["📊 <b>CRICKET STATS</b>", DIVIDER]
        captains = self.stats.top_captains()
        runs = self.stats.top_run_scorers()
        wickets = self.stats.top_wicket_takers()
        predictors = self.stats.top_predictors()
        if not (captains or runs or wickets or predictors):
            lines.append("No matches played yet. Finish a match and the leaderboards appear here!")
            return "\n".join(lines)
        if captains:
            lines.append("\n👑 <b>TOP CAPTAINS</b>")
            for medal, row in zip(medals, captains):
                lines.append(f"{medal} {esc(row['name'])} — {row['wins']}W {row['losses']}L ({row['matches']} played)")
        if runs:
            lines.append("\n🟠 <b>ORANGE CAP — most runs</b>")
            for medal, row in zip(medals, runs):
                extra = f", {row['hundreds']}×100" if row["hundreds"] else ""
                lines.append(f"{medal} {esc(row['name'])} — <b>{row['runs']}</b> (HS {row['highest']}, {row['fifties']}×50{extra})")
        if wickets:
            lines.append("\n🟣 <b>PURPLE CAP — most wickets</b>")
            for medal, row in zip(medals, wickets):
                lines.append(f"{medal} {esc(row['name'])} — <b>{row['wickets']}</b> (best {row['best_w']}/{row['best_r']})")
        if predictors:
            lines.append("\n🔮 <b>TOP PREDICTORS</b>")
            for medal, row in zip(medals, predictors):
                lines.append(f"{medal} {esc(row['name'])} — <b>{row['points']}</b> pts ({row['correct']}/{row['predictions']})")
        totals = self.stats.totals()
        lines.append(f"\n{DIVIDER}\n🎮 Matches recorded: <b>{totals['matches']}</b>")
        return "\n".join(lines)

    RULE_LIMITS = {
        "wide": (0.0, 0.3), "no_ball": (0.0, 0.3), "bye": (0.0, 0.3), "drop_catch": (0.0, 0.5),
    }
    broadcast_delay = 0.06

    def rules_text(self) -> str:
        rules = self.rules
        return (
            "⚙️ <b>RULES</b>\n"
            f"▫️ wide: <b>{rules['wide'] * 100:.1f}%</b>\n"
            f"▫️ no_ball: <b>{rules['no_ball'] * 100:.1f}%</b>\n"
            f"▫️ bye: <b>{rules['bye'] * 100:.1f}%</b>\n"
            f"▫️ drop_catch: <b>{rules['drop_catch'] * 100:.1f}%</b>\n"
            f"▫️ drs_reviews: <b>{rules['drs_reviews']}</b> per innings"
        )

    def handle_admin(self, chat: dict, user: dict, args: str) -> None:
        chat_id = chat["id"]
        if not self.admin_ids:
            self.reply(
                chat_id,
                "🛠 <b>Admin tools are switched off.</b>\n\n"
                "To enable them: send /myid to get your Telegram ID, then in Render open "
                "<b>Environment</b>, add <code>ADMIN_USER_IDS</code> with that number, and redeploy.",
                parse_mode="HTML",
            )
            return
        if user.get("id") not in self.admin_ids:
            self.reply(chat_id, "⛔ This command is only for the bot admin.")
            return
        if chat.get("type") != "private":
            self.reply(chat_id, "🔒 Please use /admin in a private chat with me.")
            return
        parts = args.split(maxsplit=1)
        action = parts[0].lower() if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if action in ("", "help", "stats", "panel"):
            totals = self.stats.totals()
            active = [g for g in self.sessions.values() if g.get("stage") != "complete"]
            self.reply(
                chat_id,
                "🛠 <b>ADMIN PANEL</b>\n"
                f"{DIVIDER}\n"
                f"⏱ Uptime: <b>{esc(self._format_duration(int(time.time() - self.started_at)))}</b>\n"
                f"🎮 Live matches: <b>{len(active)}</b>  (saved sessions: {len(self.sessions)})\n"
                f"📊 Matches played: <b>{totals['matches']}</b>  •  Captains: <b>{totals['captains']}</b>\n"
                f"👤 Players tracked: <b>{totals['players']}</b>  •  Spectators: <b>{totals['spectators']}</b>\n"
                f"💬 Known chats: <b>{totals['chats']}</b>\n\n"
                f"{self.rules_text()}\n\n"
                f"{DIVIDER}\n"
                "/admin matches — list live matches\n"
                "/admin end &lt;chat_id&gt; — end a match\n"
                "/admin broadcast &lt;text&gt; — message every known chat\n"
                "/admin rules — show the rules\n"
                "/admin set &lt;rule&gt; &lt;value&gt; — change a rule\n"
                "/admin resetstats confirm — wipe all stats",
                parse_mode="HTML",
            )
        elif action == "matches":
            lines = ["🎮 <b>LIVE MATCHES</b>"]
            for session_chat, game in self.sessions.items():
                if game.get("stage") == "complete":
                    continue
                teams = game.get("teams") or {}
                home = TEAMS.get(teams.get("home"), {}).get("name", "?")
                away = TEAMS.get(teams.get("away"), {}).get("name", "?")
                lines.append(f"▫️ <code>{session_chat}</code> — {esc(home)} vs {esc(away)} — {esc(str(game.get('stage')))}")
            if len(lines) == 1:
                lines.append("No live matches.")
            self.reply(chat_id, "\n".join(lines), parse_mode="HTML")
        elif action == "end":
            try:
                target = int(rest)
            except ValueError:
                self.reply(chat_id, "Usage: /admin end <chat_id>")
                return
            if self.sessions.pop(target, None) is None:
                self.reply(chat_id, f"ℹ️ No match found in chat {target}.")
                return
            self.safe_reply(target, "🛑 This match was ended by the bot admin.")
            self.reply(chat_id, f"✅ Ended the match in chat {target}.")
        elif action == "broadcast":
            if not rest or len(rest) > 1000:
                self.reply(chat_id, "Usage: /admin broadcast <text> (1-1000 characters)")
                return
            sent = failed = 0
            for target in self.stats.known_chat_ids()[:300]:
                if self.safe_reply(target, f"📢 {rest}") is None:
                    failed += 1
                else:
                    sent += 1
                if self.broadcast_delay:
                    time.sleep(self.broadcast_delay)
            self.reply(chat_id, f"📢 Broadcast done: ✅ {sent} sent, ❌ {failed} failed.")
        elif action == "rules":
            self.reply(chat_id, self.rules_text(), parse_mode="HTML")
        elif action == "set":
            pieces = rest.split()
            if len(pieces) != 2:
                self.reply(chat_id, "Usage: /admin set <rule> <value>  (wide, no_ball, bye, drop_catch: 0 to 0.3 — drs_reviews: 0 to 5)")
                return
            name, raw = pieces[0].lower(), pieces[1]
            try:
                number = float(raw)
            except ValueError:
                self.reply(chat_id, "⚠️ The value must be a number.")
                return
            if name == "drs_reviews":
                if not number.is_integer() or not 0 <= number <= 5:
                    self.reply(chat_id, "⚠️ drs_reviews must be a whole number from 0 to 5.")
                    return
                self.rules["drs_reviews"] = int(number)
            elif name in self.RULE_LIMITS:
                low, high = self.RULE_LIMITS[name]
                if not low <= number <= high:
                    self.reply(chat_id, f"⚠️ {name} must be between {low} and {high}.")
                    return
                self.rules[name] = number
            else:
                self.reply(chat_id, "⚠️ Unknown rule. Use: wide, no_ball, bye, drop_catch, drs_reviews.")
                return
            self.reply(chat_id, "✅ Updated.\n\n" + self.rules_text(), parse_mode="HTML")
        elif action == "resetstats":
            if rest.lower() != "confirm":
                self.reply(chat_id, "⚠️ This wipes ALL stats. Send <code>/admin resetstats confirm</code> to continue.", parse_mode="HTML")
                return
            self.stats.reset()
            self.reply(chat_id, "🧹 All stats were wiped.")
        else:
            self.reply(chat_id, "Unknown admin command. Send /admin to see the options.")

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

    def help_more_text(self) -> str:
        return (
            "🆕 <b>MATCH FEATURES</b>\n"
            f"{DIVIDER}\n\n"
            "📺 <b>DRS REVIEWS</b> (ball-by-ball mode)\n"
            "After a wicket the batting captain can tap 📺 Review. Two reviews per "
            "innings. A failed review is lost, a successful one is kept. Run outs "
            "can't be reviewed.\n\n"
            "🟡 <b>EXTRAS &amp; FREE HITS</b>\n"
            "Wides and no-balls add a run and the ball is bowled again. A no-ball "
            "gives a 🆓 FREE HIT. Byes can happen too.\n\n"
            "🧤 <b>FIELDING</b>\n"
            "Wickets are bowled, lbw, caught, stumped or run out, with the fielder "
            "named. Catches can be dropped!\n\n"
            "⚡ <b>SUPER OVER</b>\n"
            "A tied match goes to a Super Over: one over, two wickets, the best 3 "
            "batters and the best bowler.\n\n"
            f"{DIVIDER}\n"
            "🎉 <b>CELEBRATIONS</b>\n"
            "Fifties, hundreds, wicket hauls, hat-tricks, maidens and big stands "
            "arrive as their own message.\n\n"
            "🏆 <b>AWARDS &amp; PNG SCORECARD</b>\n"
            "At the end you get Player of the Match, best batter, best bowler and "
            "more, plus a picture scorecard. Use /scorecard any time.\n\n"
            "🔮 <b>SPECTATORS</b>\n"
            "Not a captain? Predict the winner when the match starts: +10 points for "
            "a correct pick, +2 for taking part.\n\n"
            "👤 <b>PROFILE &amp; STATS</b>\n"
            "/profile shows your record. /stats shows the leaderboards. "
            "Reply to someone's message with /profile to see theirs.\n\n"
            "🛠 <b>ADMIN</b>\n"
            "The bot owner can use /admin in a private chat. Group admins can also "
            "/cancel a match."
        )

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
            "📊 <b>STATS &amp; PICTURES</b>\n\n"
            "▫️ /scorecard  —  🖼 PNG scorecard of the match\n"
            "▫️ /profile  —  👤 Your captain profile\n"
            "▫️ /stats  —  🏆 Leaderboards (orange &amp; purple cap)\n"
            "▫️ /myid  —  🆔 Your Telegram ID\n\n"
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
        args = text[command_match.end():].strip()
        try:
            self.stats.touch_chat(chat_id, chat.get("title", ""))
        except sqlite3.Error:
            pass

        busy_text = "⚠️ A match is already in progress.\n\nUse /cancel before starting another."

        if command in ("start", "help"):
            self.reply(chat_id, self.help_text(), parse_mode="HTML")
            self.reply(chat_id, self.help_more_text(), parse_mode="HTML")
        elif command == "myid":
            self.reply(
                chat_id,
                f"🆔 Your Telegram user ID: <code>{esc(str(user.get('id')))}</code>\n"
                f"💬 This chat ID: <code>{chat_id}</code>",
                parse_mode="HTML",
            )
        elif command == "profile":
            target = (message.get("reply_to_message") or {}).get("from") or user
            self.reply(chat_id, self.profile_text(target), parse_mode="HTML")
        elif command == "stats":
            self.reply(chat_id, self.stats_text(), parse_mode="HTML")
        elif command == "scorecard":
            game = self.sessions.get(chat_id)
            if not game or game.get("stage") not in ("live", "innings_break", "complete"):
                self.reply(chat_id, "ℹ️ There is no match to show yet. Start one with /playint, /playipl or /vsbot.")
            elif not self.send_scorecard_png(
                game,
                "🏁 " + self.final_result_text(game) if game["stage"] == "complete" else "📸 Scorecard so far",
            ):
                self.reply(chat_id, "⚠️ I could not create the scorecard picture right now. Try again in a moment.")
        elif command == "admin":
            self.handle_admin(chat, user, args)
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
            elif game.get("host") != user.get("id") and not self.is_chat_admin(chat_id, user.get("id")):
                self.reply(chat_id, "⚠️ Only the match host or a group admin can cancel this match.")
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

        if data.startswith("predict:"):
            self.handle_predict(
                callback_id, self.sessions.get(chat_id), user, data.partition(":")[2], message
            )
            return

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
            self.open_predictions(game)
            self.start_innings(game)
            return

        if data == "second-innings":
            if game["stage"] != "innings_break" or user_id != game["host"]:
                self.answer_callback(callback_id, "The host starts the second innings.")
                return
            self.answer_callback(callback_id)
            other_side = "away" if game["batting_side"] == "home" else "home"
            if game["innings_number"] == 3:
                game["innings_number"] = 4
                game["batting_side"] = other_side
                game["target"] = game["super_over"]["results"][0]["score"] + 1
                self.start_super_over_innings(game)
                return
            game["innings_number"] = 2
            game["batting_side"] = other_side
            game["target"] = game["results"][0]["score"] + 1
            self.close_predictions(game)
            self.start_innings(game)
            return

        if data in ("drs:review", "drs:accept"):
            if game.get("stage") != "live" or game.get("phase") != "drs":
                self.answer_callback(callback_id, "📺 There is no decision to review right now.")
                return
            if game["captains"][game["batting_side"]] != user_id:
                self.answer_callback(callback_id, "📺 Only the batting captain can decide on a review.")
                return
            self.answer_callback(callback_id)
            self.resolve_drs(game, data == "drs:review")
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
    def new_innings(lineup: list[str], overs_limit: int, max_wickets: int = 10) -> dict:
        return {
            "match": create_match(overs_limit, max_wickets),
            "batters": [
                {"name": name, "runs": 0, "balls": 0, "fours": 0, "sixes": 0, "out": False, "how_out": None}
                for name in lineup
            ],
            "extras": {"wd": 0, "nb": 0, "b": 0},
            "free_hit": False,
            "fow": [],
            "over_log": [],
            "over_runs": 0,
            "over_wickets": 0,
            "wicket_streak": {"bowler": None, "count": 0},
            "reviews_left": 0,
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
        game["innings"]["reviews_left"] = int(self.rules.get("drs_reviews", 0))
        game["stage"] = "live"
        game["phase"] = self.next_phase(game)
        self.advance_vs_bot_turn(game)

    def batting_side_name(self, game: dict) -> str:
        return TEAMS[game["teams"][game["batting_side"]]]["name"]

    def bowling_side(self, game: dict) -> str:
        return "away" if game["batting_side"] == "home" else "home"

    def innings_over(self, game: dict) -> bool:
        return is_match_over(game["innings"]["match"]) or (
            game["innings_number"] in (2, 4)
            and game["innings"]["match"]["score"] >= game["target"]
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
        overs_left = max(0, match["overs_limit"] * 6 - match["balls"])
        if match["wickets"] >= match.get("max_wickets", 10) - 3:
            return "defensive"
        if game["innings_number"] in (2, 4):
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
        if game["phase"] == "drs":
            if game["batting_side"] == "away":
                self.resolve_drs(game, self.ai_wants_review(game))
                return
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
        result = self._play_ball(game, style)
        self.deliver_celebrations(game, result["celebrations"])
        self._after_turn(game)

    def _after_turn(self, game: dict) -> None:
        if game["innings"].get("drs_pending"):
            # A wicket just fell and the batting side may review it.
            game["phase"] = "drs"
            self.advance_vs_bot_turn(game)
            return
        if self.innings_over(game):
            self.finish_innings(game)
        else:
            game["phase"] = self.next_phase(game)
            self.advance_vs_bot_turn(game)

    @staticmethod
    def ball_token(outcome: str, runs: int) -> str:
        return {"wicket": "W", "wide": "Wd", "no_ball": "Nb", "bye": "B"}.get(outcome, str(runs))

    def play_over(self, game: dict, bowling_style: str) -> None:
        """Simulate every remaining ball of the current over in one go."""
        innings = game["innings"]
        match = innings["match"]
        score_before = match["score"]
        wickets_before = match["wickets"]
        tokens: list[str] = []
        events: list[str] = []
        celebrations: list[str] = []
        bowler_name = ""
        for _ in range(24):  # wides and no-balls can stretch an over
            result = self._play_ball(game, bowling_style)
            tokens.append(self.ball_token(result["outcome"], result["runs"]))
            events.extend(result["events"])
            celebrations.extend(result["celebrations"])
            bowler_name = result["bowler"]
            over_done = match["balls"] % 6 == 0 and not result.get("extra")
            if over_done or self.innings_over(game):
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
        self.deliver_celebrations(game, celebrations)
        self._after_turn(game)

    # ------------------------------------------------------------------
    # Celebrations (sent as their own message), DRS and super-over helpers
    # ------------------------------------------------------------------
    def deliver_celebrations(self, game: dict, celebrations: list[str]) -> None:
        """Send milestone celebrations now, or hold them while a DRS review is pending."""
        if game["innings"].get("drs_pending"):
            game["innings"]["pending_celebrations"] = celebrations
        else:
            self.send_celebrations(game, celebrations)

    def send_celebrations(self, game: dict, celebrations: list[str]) -> None:
        if not celebrations:
            return
        try:
            self.reply(game["chat_id"], "\n\n".join(celebrations), parse_mode="HTML")
        except (RuntimeError, URLError, TimeoutError) as error:
            print(f"Could not send the celebration message: {error}", file=sys.stderr)

    def safe_reply(self, chat_id: int, text: str, **kwargs):
        """Send an optional extra message; never let a failure break the match."""
        try:
            return self.reply(chat_id, text, **kwargs)
        except (RuntimeError, URLError, TimeoutError) as error:
            print(f"Could not send an extra message: {error}", file=sys.stderr)
            return None

    @staticmethod
    def batter_celebration(threshold: int, batter: dict) -> str:
        banner = {
            50: "🔥🔥 <b>FIFTY!</b> 🔥🔥",
            100: "💯💯 <b>CENTURY!</b> 💯💯",
            150: "🚀🚀 <b>150 UP!</b> 🚀🚀",
            200: "👑👑 <b>DOUBLE CENTURY!</b> 👑👑",
        }.get(threshold, f"🌟 <b>{threshold}!</b>")
        strike_rate = batter["runs"] * 100 / batter["balls"] if batter["balls"] else 0.0
        return (
            f"{banner}\n🏏 <b>{esc(batter['name'])}</b> reaches <b>{threshold}</b> "
            f"off {batter['balls']} balls\n"
            f"📊 {batter['runs']}({batter['balls']}) • {batter['fours']}×4 • "
            f"{batter['sixes']}×6 • SR {strike_rate:.1f}"
        )

    @staticmethod
    def haul_celebration(wickets: int, bowler_name: str, stats: dict) -> str:
        banner = {
            3: "🎳🎳 <b>THREE-WICKET HAUL!</b> 🎳🎳",
            5: "🏆🏆 <b>FIVE-WICKET HAUL!</b> 🏆🏆",
        }.get(wickets, f"🎳 <b>{wickets} WICKETS!</b>")
        return (
            f"{banner}\n🎯 <b>{esc(bowler_name)}</b> now has "
            f"<b>{stats['wickets']}/{stats['runs']}</b> ({format_overs(stats['balls'])} ov)"
        )

    @staticmethod
    def dismissal_text(kind: str, bowler: str, fielder: str | None) -> str:
        return {
            "bowled": f"b {bowler}",
            "lbw": f"lbw b {bowler}",
            "caught": f"c {fielder} b {bowler}",
            "stumped": f"st {fielder} b {bowler}",
            "run out": f"run out ({fielder})",
        }[kind]

    def drs_possible(self, game: dict) -> bool:
        return (
            game.get("sim_mode") != "over"
            and game.get("stage") == "live"
            and game["innings"].get("reviews_left", 0) > 0
        )

    def ai_wants_review(self, game: dict) -> bool:
        pending = game["innings"].get("drs_pending") or {}
        if game["innings"].get("reviews_left", 0) <= 0:
            return False
        chance = {"lbw": 0.5, "caught": 0.35, "stumped": 0.3}.get(pending.get("kind"), 0.0)
        return random.random() < chance

    def drs_keyboard(self, game: dict) -> list:
        left = game["innings"].get("reviews_left", 0)
        return [
            [self.button(f"📺 Review ({left} left)", "drs:review")],
            [self.button("✅ Accept the decision", "drs:accept")],
        ]

    def resolve_drs(self, game: dict, review: bool) -> None:
        innings = game["innings"]
        pending = innings.pop("drs_pending", None)
        held = innings.pop("pending_celebrations", [])
        if not pending:
            self._after_turn(game)
            return
        side = game["batting_side"]
        stats = game.setdefault(
            "drs_stats", {"home": {"used": 0, "success": 0}, "away": {"used": 0, "success": 0}}
        )[side]
        name = esc(pending["batter"])
        if not review:
            self.send_celebrations(game, held)
            self._after_turn(game)
            return
        stats["used"] += 1
        success = random.random() < DRS_SUCCESS.get(pending["kind"], 0.2)
        reasons = DRS_REASONS[pending["kind"]]
        if success:
            stats["success"] += 1
            self.safe_reply(
                game["chat_id"],
                f"📺 <b>DRS REVIEW</b>  •  {name}\n🔍 Checking the replays...\n\n"
                f"✅ <b>OVERTURNED — NOT OUT!</b>\n<i>{esc(reasons[1])}</i>",
                parse_mode="HTML",
            )
            game["innings"] = pending["snapshot"]
            self._play_ball(game, None, forced={
                "outcome": "dot",
                "runs": 0,
                "commentary": f"📺 REVIEW SUCCESSFUL! {pending['batter']} survives — NOT OUT.",
                "last_ball": "📺 DRS: decision overturned — NOT OUT!",
            })
        else:
            innings["reviews_left"] = max(0, innings.get("reviews_left", 0) - 1)
            self.safe_reply(
                game["chat_id"],
                f"📺 <b>DRS REVIEW</b>  •  {name}\n🔍 Checking the replays...\n\n"
                f"❌ <b>DECISION STANDS — OUT!</b>\n<i>{esc(reasons[0])}</i>\n"
                f"📺 Reviews left: <b>{innings['reviews_left']}</b>",
                parse_mode="HTML",
            )
            innings["commentary"].append({
                "over": format_overs(innings["match"]["balls"]),
                "text": f"📺 REVIEW LOST: {pending['batter']} has to go ({pending['how']}).",
            })
            del innings["commentary"][:-6]
            self.send_celebrations(game, held)
        self._after_turn(game)

    def ensure_innings_fields(self, innings: dict) -> None:
        """Older saved matches may lack the newer tracking fields."""
        innings.setdefault("partnership", self.new_partnership())
        innings["partnership"].setdefault("contrib", {})
        innings.setdefault("partnerships", [])
        innings.setdefault("milestones", [])
        innings.setdefault("extras", {"wd": 0, "nb": 0, "b": 0})
        innings.setdefault("free_hit", False)
        innings.setdefault("fow", [])
        innings.setdefault("over_log", [])
        innings.setdefault("over_runs", 0)
        innings.setdefault("over_wickets", 0)
        innings.setdefault("wicket_streak", {"bowler": None, "count": 0})
        innings.setdefault("reviews_left", 0)
        innings.setdefault("sledges", [])

    def _play_extra(self, game: dict, kind: str, bowler_name: str) -> dict:
        """A wide or a no-ball: one run to the total, and the ball is not counted."""
        innings = game["innings"]
        match = innings["match"]
        score_before = match["score"]
        match["score"] += 1
        innings["extras"]["wd" if kind == "wide" else "nb"] += 1
        innings["bowlers"].setdefault(bowler_name, {"balls": 0, "runs": 0, "wickets": 0})["runs"] += 1
        innings["partnership"]["runs"] += 1
        innings["over_runs"] += 1
        if kind == "no_ball":
            innings["free_hit"] = True
        events = [
            f"📈 {self.batting_side_name(game)} reach {threshold}"
            for threshold in TEAM_MILESTONES
            if score_before < threshold <= match["score"]
        ]
        template = EXTRA_COMMENTARY[kind]
        text = template[match["score"] % len(template)].format(bowler=bowler_name)
        label = format_overs(match["balls"]) + ("wd" if kind == "wide" else "nb")
        innings["commentary"].append({"over": label, "text": text})
        del innings["commentary"][: -(8 if game.get("sim_mode") == "over" else 6)]
        innings["last_ball"] = (
            "🟡 WIDE! +1 run." if kind == "wide" else "🟠 NO BALL! +1 run. FREE HIT next ball!"
        )
        innings["milestone_alert"] = events
        for event in events:
            innings["milestones"].append({"over": label, "text": event})
        return {
            "outcome": kind, "runs": 1, "events": events, "bowler": bowler_name,
            "celebrations": [], "extra": True,
        }

    def _play_ball(self, game: dict, style: str | None, forced: dict | None = None) -> dict:
        innings = game["innings"]
        self.ensure_innings_fields(innings)
        match = innings["match"]
        side = self.bowling_side(game)
        fielding_players = TEAMS[game["teams"][side]]["players"]
        bowler_xi = [fielding_players[index] for index in game["lineups"][side]]
        rotation = innings.get("bowler_rotation") or bowler_xi
        current_index = innings.get("bowler_index", 0) % len(rotation)
        bowler_name = self.current_bowler_name(game)
        striker_name = innings["batters"][innings["striker"]]["name"]

        # A copy of the innings from before this ball lets a DRS review undo a wicket.
        snapshot = copy.deepcopy(innings) if forced is None and self.drs_possible(game) else None

        extra = None if forced else roll_extra(self.rules)
        if extra in ("wide", "no_ball"):
            return self._play_extra(game, extra, bowler_name)

        score_before = match["score"]
        if forced is not None or extra == "bye":
            outcome, runs = (forced["outcome"], forced["runs"]) if forced else ("bye", 1)
            match["balls"] += 1
            match["score"] += runs
            ball = match["balls"] - 1
            delivery = {"outcome": outcome, "runs": runs, "over": f"{ball // 6}.{ball % 6 + 1}"}
        else:
            delivery = simulate_ball(
                match,
                game["batting_style"],
                style,
                self.match_modifiers(game, striker_name, bowler_name),
            )

        # ---- Fielding: how did the wicket fall (or was it dropped / a free hit)?
        dismissal = None
        note = None
        fielder = None
        if delivery["outcome"] == "wicket":
            keeper = next(
                (name for name in bowler_xi if player_role(name) == "WK" and name != bowler_name), None
            )
            kind = pick_dismissal(self.rules["dismissals"], has_keeper=keeper is not None)
            others = [name for name in bowler_xi if name != bowler_name] or [bowler_name]
            if kind == "stumped":
                fielder = keeper
            elif kind == "caught":
                fielder = keeper if keeper and random.random() < 0.25 else random.choice(others)
            elif kind == "run out":
                fielder = random.choice(others)
            if innings.get("free_hit") and kind != "run out":
                note = "free_hit"
            elif kind == "caught" and random.random() < self.rules.get("drop_catch", 0.0):
                note = "dropped"
            if note:
                match["wickets"] -= 1
                delivery = {**delivery, "outcome": "dot", "runs": 0}
            else:
                dismissal = (kind, fielder, self.dismissal_text(kind, bowler_name, fielder))
        innings["free_hit"] = False

        batter_runs = 0 if delivery["outcome"] == "bye" else delivery["runs"]
        events: list[str] = []
        celebrations: list[str] = []
        batter = innings["batters"][innings["striker"]]
        non_striker_name = innings["batters"][innings["non_striker"]]["name"]
        runs_before = batter["runs"]

        batter["balls"] += 1
        batter["runs"] += batter_runs
        if batter_runs == 4:
            batter["fours"] += 1
        elif batter_runs == 6:
            batter["sixes"] += 1
        bowler = innings["bowlers"].setdefault(
            bowler_name, {"balls": 0, "runs": 0, "wickets": 0}
        )
        bowler["balls"] += 1
        bowler["runs"] += batter_runs  # byes are not charged to the bowler
        innings["over_runs"] += delivery["runs"]
        if delivery["outcome"] == "bye":
            innings["extras"]["b"] += delivery["runs"]

        # --- Batter milestones: 50 / 100 / 150 / 200 ---
        for threshold, label in BATTER_MILESTONES.items():
            if runs_before < threshold <= batter["runs"]:
                events.append(
                    f"{label}: {batter['name']} reaches {threshold} off {batter['balls']} balls"
                )
                celebrations.append(self.batter_celebration(threshold, batter))

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
        contrib[batter["name"]] = contrib.get(batter["name"], 0) + batter_runs
        contrib.setdefault(non_striker_name, 0)
        for threshold in PARTNERSHIP_MILESTONES:
            if partnership_before < threshold <= partnership["runs"]:
                events.append(
                    f"🤝 {threshold}-run partnership: {batter['name']} & {non_striker_name}"
                )
                celebrations.append(
                    f"🤝🤝 <b>{threshold}-RUN PARTNERSHIP!</b> 🤝🤝\n"
                    f"🏏 <b>{esc(batter['name'])}</b> &amp; <b>{esc(non_striker_name)}</b> "
                    f"are in full flow"
                )

        streak = innings["wicket_streak"]
        if dismissal:
            kind, fielder, how = dismissal
            credited = kind != "run out"
            batter["out"] = True
            batter["how_out"] = how
            innings["over_wickets"] += 1
            if credited:
                bowler["wickets"] += 1
            innings["last_wicket"] = f"{batter['name']} {how}"
            innings["fow"].append({
                "score": match["score"], "wicket": match["wickets"],
                "batter": batter["name"], "over": delivery["over"],
            })

            # --- Bowler milestones: 3-wicket haul / 5-wicket haul ---
            if credited and bowler["wickets"] in BOWLER_MILESTONES:
                events.append(
                    f"{BOWLER_MILESTONES[bowler['wickets']]}: {bowler_name} "
                    f"{bowler['wickets']}/{bowler['runs']}"
                )
                celebrations.append(self.haul_celebration(bowler["wickets"], bowler_name, bowler))

            # --- Hat-trick: three wickets in three consecutive balls by one bowler ---
            if credited:
                if streak.get("bowler") == bowler_name:
                    streak["count"] += 1
                else:
                    streak = innings["wicket_streak"] = {"bowler": bowler_name, "count": 1}
                if streak["count"] == 3:
                    events.append(f"🎩 HAT-TRICK: {bowler_name}")
                    celebrations.append(
                        f"🎩🎩 <b>HAT-TRICK!</b> 🎩🎩\n🎳 <b>{esc(bowler_name)}</b> "
                        f"takes three wickets in three balls!"
                    )
            else:
                innings["wicket_streak"] = {"bowler": None, "count": 0}

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
            innings["wicket_streak"] = {"bowler": None, "count": 0}
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

        if note == "dropped":
            commentary = (
                f"🟡 DROPPED! {fielder} spills a sitter off {bowler_name}; "
                f"{batter['name']} survives!"
            )
        elif note == "free_hit":
            commentary = (
                f"🆓 FREE HIT! {batter['name']} survives — no dismissal off a no-ball!"
            )
        elif forced:
            commentary = forced["commentary"]
        else:
            commentary = self.ball_commentary(
                bowler_name,
                batter["name"],
                delivery["outcome"],
                delivery["runs"],
                variant=match["balls"] - 1,
            )
            if dismissal:
                commentary += f" ({dismissal[2]})"
        if forced:
            innings["last_ball"] = forced["last_ball"]
        elif note:
            innings["last_ball"] = (
                "🟡 Dropped catch! Not out." if note == "dropped" else "🆓 Free hit: not out."
            )
        else:
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

        # --- End of over: runs-per-over log and maiden overs ---
        if match["balls"] % 6 == 0:
            innings["over_log"].append({
                "runs": innings["over_runs"],
                "wickets": innings["over_wickets"],
                "bowler": bowler_name,
            })
            if innings["over_runs"] == 0:
                events.append(f"🧱 MAIDEN: {bowler_name} (over {match['balls'] // 6})")
                celebrations.append(
                    f"🧱🧱 <b>MAIDEN OVER!</b> 🧱🧱\n🎳 <b>{esc(bowler_name)}</b> gives nothing "
                    f"away in over {match['balls'] // 6}"
                )
            innings["over_runs"] = 0
            innings["over_wickets"] = 0

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

        # A wicket (other than a run out) can be reviewed in ball-by-ball play.
        if (
            dismissal
            and dismissal[0] != "run out"
            and snapshot is not None
            and innings.get("reviews_left", 0) > 0
        ):
            innings["drs_pending"] = {
                "snapshot": snapshot,
                "batter": batter["name"],
                "kind": dismissal[0],
                "how": dismissal[2],
            }

        return {
            "outcome": delivery["outcome"],
            "runs": delivery["runs"],
            "events": events,
            "bowler": bowler_name,
            "celebrations": celebrations,
            "extra": False,
        }

    @staticmethod
    def ball_commentary(
        bowler: str, batter: str, outcome: str, runs: int, variant: int = 0
    ) -> str:
        key = outcome
        if outcome not in COMMENTARY_TEMPLATES:
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

    def innings_snapshot(self, game: dict, innings: dict, side: str, label: str = "") -> dict:
        """A plain, self-contained record of an innings (used for results, stats, awards, PNG)."""
        self.ensure_innings_fields(innings)
        match = innings["match"]
        batted, names = [], set()
        for index, batter in enumerate(innings["batters"]):
            if batter["balls"] or batter["out"] or index in (innings["striker"], innings["non_striker"]):
                names.add(batter["name"])
                batted.append({
                    "name": batter["name"], "runs": batter["runs"], "balls": batter["balls"],
                    "fours": batter["fours"], "sixes": batter["sixes"], "out": batter["out"],
                    "how_out": batter.get("how_out"),
                })
        partnerships = innings.get("partnerships", [])
        return {
            "side": side,
            "team": TEAMS[game["teams"][side]]["name"],
            "label": label,
            "score": match["score"],
            "wickets": match["wickets"],
            "balls": match["balls"],
            "overs_limit": match["overs_limit"],
            "batters": batted,
            "did_not_bat": [b["name"] for b in innings["batters"] if b["name"] not in names],
            "bowlers": {name: dict(stats) for name, stats in innings["bowlers"].items()},
            "extras": dict(innings["extras"]),
            "fow": list(innings["fow"]),
            "over_log": list(innings["over_log"]),
            "milestones": [item["text"] for item in innings.get("milestones", [])],
            "best_partnership": max(partnerships, key=lambda p: p["runs"], default=None),
        }

    def finish_innings(self, game: dict) -> None:
        innings = game["innings"]
        self.ensure_innings_fields(innings)
        match = innings["match"]
        side = game["batting_side"]

        # An unbroken partnership at the end of the innings still counts.
        partnership = innings.get("partnership")
        if partnership and partnership.get("balls") and match["wickets"] < match.get("max_wickets", 10):
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
        # The last, unfinished over still goes into the runs-per-over log.
        if innings["over_runs"] or innings["over_wickets"]:
            innings["over_log"].append({
                "runs": innings["over_runs"], "wickets": innings["over_wickets"],
                "bowler": innings.get("last_bowler"),
            })
            innings["over_runs"] = 0
            innings["over_wickets"] = 0

        number = game["innings_number"]
        label = {1: "1st INNINGS", 2: "2nd INNINGS", 3: "SUPER OVER - 1st", 4: "SUPER OVER - 2nd"}[number]
        snapshot = self.innings_snapshot(game, innings, side, label)
        if number >= 3:
            self.finish_super_over_innings(game, snapshot)
            return
        game["results"].append(snapshot)
        if number == 1:
            game["stage"] = "innings_break"
            self.render_scorecard(game)
            return
        first, second = game["results"]
        if second["score"] == first["score"]:
            self.start_super_over(game)
            return
        self.complete_match(game)

    # ------------------------------------------------------------------ Super Over
    def start_super_over(self, game: dict) -> None:
        first, second = game["results"]
        game["super_over"] = {"results": [], "winner": None}
        self.safe_reply(
            game["chat_id"],
            f"🤝🤝 <b>IT'S A TIE — {first['score']} ALL!</b> 🤝🤝\n\n"
            "⚡ <b>SUPER OVER</b> to decide the winner!\n"
            "🏏 One over each, 2 wickets, best 3 batters and the best bowler\n"
            f"▶️ <b>{esc(second['team'])}</b> bat first (they batted second)",
            parse_mode="HTML",
        )
        game["innings_number"] = 3
        game["batting_side"] = second["side"]
        game["target"] = None
        self.start_super_over_innings(game)

    def start_super_over_innings(self, game: dict) -> None:
        side = game["batting_side"]
        batting_players = TEAMS[game["teams"][side]]["players"]
        batting_xi = [batting_players[index] for index in game["lineups"][side]]
        top_three = sorted(batting_xi, key=lambda name: (-bat_rating(name), name))[:3]
        innings = self.new_innings(top_three, 1, max_wickets=2)
        game["innings"] = innings
        bowling_side = self.bowling_side(game)
        bowling_players = TEAMS[game["teams"][bowling_side]]["players"]
        bowling_xi = [bowling_players[index] for index in game["lineups"][bowling_side]]
        candidates = [name for name in bowling_xi if player_role(name) in ("BOWL", "AR")] or bowling_xi
        best = max(candidates, key=lambda name: (bowl_rating(name), name))
        innings["bowler_rotation"] = [best]
        innings["bowler_index"] = 0
        innings["last_bowler"] = best
        innings["manual_bowler"] = best
        innings["reviews_left"] = min(1, int(self.rules.get("drs_reviews", 0)))
        game["stage"] = "live"
        game["phase"] = self.next_phase(game)
        self.advance_vs_bot_turn(game)

    @staticmethod
    def boundary_count(game: dict, side: str) -> int:
        innings_list = list(game.get("results", [])) + list((game.get("super_over") or {}).get("results", []))
        return sum(
            batter["fours"] + batter["sixes"]
            for item in innings_list if item["side"] == side
            for batter in item.get("batters", [])
        )

    def finish_super_over_innings(self, game: dict, snapshot: dict) -> None:
        super_over = game["super_over"]
        super_over["results"].append(snapshot)
        if game["innings_number"] == 3:
            game["stage"] = "innings_break"
            self.render_scorecard(game)
            return
        first, second = super_over["results"]
        if second["score"] > first["score"]:
            winner = second["side"]
        elif second["score"] < first["score"]:
            winner = first["side"]
        else:
            home, away = self.boundary_count(game, "home"), self.boundary_count(game, "away")
            winner = "home" if home > away else "away" if away > home else None
        super_over["winner"] = winner
        self.complete_match(game)

    def final_result_text(self, game: dict) -> str:
        super_over = game.get("super_over")
        if super_over and len(super_over.get("results", [])) == 2:
            first, second = super_over["results"]
            line = (
                f"{first['team']} {first['score']}/{first['wickets']} vs "
                f"{second['team']} {second['score']}/{second['wickets']}"
            )
            winner = super_over.get("winner")
            if winner is None:
                return f"The Super Over is tied too ({line}). Match shared!"
            team = TEAMS[game["teams"][winner]]["name"]
            suffix = " on boundary count" if first["score"] == second["score"] else ""
            return f"{team} win the Super Over{suffix}! ({line})"
        return self.match_result_text(game)

    def winner_side(self, game: dict) -> str | None:
        super_over = game.get("super_over")
        if super_over and len(super_over.get("results", [])) == 2:
            return super_over.get("winner")
        first, second = game["results"]
        if second["score"] > first["score"]:
            return second["side"]
        if second["score"] < first["score"]:
            return first["side"]
        return None

    # ------------------------------------------------------------------ Match completion
    def complete_match(self, game: dict) -> None:
        """Awards, PNG scorecard, predictions and stats each go out as their own message."""
        game["stage"] = "complete"
        result = self.final_result_text(game)
        winner = self.winner_side(game)
        awards = compute_awards(game["results"], winner)
        game["awards"] = awards
        self.safe_reply(game["chat_id"], format_awards_message(awards, result), parse_mode="HTML")
        self.send_scorecard_png(game, f"🏁 {result}")
        self.resolve_predictions(game, winner)
        self.record_stats(game, result, winner)
        self.render_scorecard(game, result)

    @staticmethod
    def png_innings(snapshot: dict, fallback_label: str, default_overs: int) -> dict:
        return {
            "label": snapshot.get("label") or fallback_label,
            "team": snapshot["team"],
            "score": snapshot["score"],
            "wickets": snapshot["wickets"],
            "balls": snapshot["balls"],
            "overs_limit": snapshot.get("overs_limit", default_overs),
            "batters": snapshot.get("batters", []),
            "did_not_bat": snapshot.get("did_not_bat", []),
            "bowlers": [{"name": name, **stats} for name, stats in (snapshot.get("bowlers") or {}).items()],
            "extras": snapshot.get("extras") or {},
            "fow": snapshot.get("fow") or [],
            "over_log": snapshot.get("over_log") or [],
        }

    def scorecard_view(self, game: dict) -> dict:
        """Everything the PNG renderer needs, built from the game state."""
        stage = game.get("stage")
        home = TEAMS[game["teams"]["home"]]["name"]
        away = TEAMS[game["teams"]["away"]]["name"]
        pieces = [
            self.league_name(game.get("league")),
            f"{game['overs_limit']} overs",
            f"{PITCHES[game['pitch']]['name']} pitch",
        ]
        toss = game.get("toss")
        if toss and toss.get("decision"):
            winner_team = TEAMS[game["teams"][toss["winner"]]]["name"]
            pieces.append(f"Toss: {winner_team} chose to {toss['decision']}")
        default_overs = game["overs_limit"]
        innings_views = [
            self.png_innings(snapshot, f"INNINGS {number}", default_overs)
            for number, snapshot in enumerate(game.get("results", []), start=1)
        ]
        innings_views += [
            self.png_innings(snapshot, "SUPER OVER", 1)
            for snapshot in (game.get("super_over") or {}).get("results", [])
        ]
        if stage == "live" and game.get("innings"):
            number = game["innings_number"]
            label = {1: "1st INNINGS", 2: "2nd INNINGS", 3: "SUPER OVER - 1st", 4: "SUPER OVER - 2nd"}[number]
            live = self.innings_snapshot(game, game["innings"], game["batting_side"], f"{label} (LIVE)")
            innings_views.append(self.png_innings(live, label, default_overs))
        awards_lines = []
        awards = game.get("awards") or {}
        if stage == "complete":
            if awards.get("potm"):
                potm = awards["potm"]
                awards_lines.append(f"Player of the Match: {potm['name']} ({potm['summary']})")
            if awards.get("best_batter"):
                batter = awards["best_batter"]
                awards_lines.append(f"Best Batter: {batter['name']} {batter['runs']}({batter['balls']})")
            if awards.get("best_bowler"):
                bowler = awards["best_bowler"]
                awards_lines.append(f"Best Bowler: {bowler['name']} {bowler['wickets']}/{bowler['runs']}")
        return {
            "title": f"{home} vs {away}",
            "status": {"live": "LIVE", "innings_break": "INNINGS BREAK", "complete": "FINAL"}.get(stage, ""),
            "subtitle": "  |  ".join(pieces),
            "result": self.final_result_text(game) if stage == "complete" else None,
            "innings": innings_views,
            "awards": awards_lines,
            "footer": f"Cricket Simulator Bot  |  {time.strftime('%d %b %Y')}",
        }

    def send_scorecard_png(self, game: dict, caption: str, chat_id: int | None = None) -> bool:
        """Draw the scorecard as a PNG and send it as a photo. Returns False on failure."""
        try:
            png = render_scorecard_png(self.scorecard_view(game))
            self.api_upload(
                "sendPhoto",
                {"chat_id": chat_id or game["chat_id"], "caption": caption[:1000]},
                "photo",
                "scorecard.png",
                png,
            )
            return True
        except (RuntimeError, URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            print(f"Could not send the PNG scorecard: {error}", file=sys.stderr)
            return False

    def record_stats(self, game: dict, result: str, winner: str | None) -> None:
        awards = game.get("awards") or {}
        captains = {}
        for side in ("home", "away"):
            captain_id = game["captains"].get(side)
            captains[side] = (
                {"id": captain_id, "name": game["captain_names"].get(side, "")} if captain_id else None
            )
        summary = {
            "chat_id": game["chat_id"],
            "home_team": TEAMS[game["teams"]["home"]]["name"],
            "away_team": TEAMS[game["teams"]["away"]]["name"],
            "result": result,
            "winner_side": winner,
            "toss_winner_side": (game.get("toss") or {}).get("winner"),
            "captains": captains,
            "innings": game["results"],
            "potm": awards.get("potm"),
            "drs": game.get("drs_stats"),
            "super_over": bool(game.get("super_over")),
        }
        try:
            self.stats.record_match(summary)
        except sqlite3.Error as error:
            print(f"Could not record match stats: {error}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Spectator mode: non-captains predict the winner
    # ------------------------------------------------------------------
    def prediction_text(self, game: dict) -> str:
        predictions = game["predictions"]
        home = esc(TEAMS[game["teams"]["home"]]["name"])
        away = esc(TEAMS[game["teams"]["away"]]["name"])
        lines = [
            "🔮 <b>SPECTATOR PREDICTIONS</b>",
            DIVIDER,
            f"🏏 <b>{home}</b> vs <b>{away}</b>",
            "",
            "Who will win? Spectators only: captains can't vote!",
            "🎯 Correct pick: <b>+10</b> points  •  🎟 Taking part: <b>+2</b>",
            f"👥 Votes so far: <b>{len(predictions['votes'])}</b>",
        ]
        if not predictions.get("open"):
            lines.append("\n🔒 <b>Predictions are closed.</b>")
        return "\n".join(lines)

    def prediction_keyboard(self, game: dict) -> list | None:
        predictions = game["predictions"]
        if not predictions.get("open"):
            return None
        counts = {"home": 0, "away": 0}
        for vote in predictions["votes"].values():
            counts[vote["pick"]] += 1
        return [[
            self.button(f"🏠 {TEAMS[game['teams']['home']]['name']} ({counts['home']})", "predict:home"),
            self.button(f"✈️ {TEAMS[game['teams']['away']]['name']} ({counts['away']})", "predict:away"),
        ]]

    def refresh_prediction_message(self, game: dict) -> None:
        predictions = game.get("predictions")
        if not predictions or not predictions.get("message_id"):
            return
        keyboard = self.prediction_keyboard(game)
        try:
            self.api("editMessageText", {
                "chat_id": game["chat_id"],
                "message_id": predictions["message_id"],
                "text": self.prediction_text(game),
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": keyboard or []},
            })
        except (RuntimeError, URLError, TimeoutError) as error:
            print(f"Could not update the prediction message: {error}", file=sys.stderr)

    def open_predictions(self, game: dict) -> None:
        if game.get("vs_bot"):
            return
        game["predictions"] = {"message_id": None, "open": True, "votes": {}}
        message = self.safe_reply(
            game["chat_id"],
            self.prediction_text(game),
            keyboard=self.prediction_keyboard(game),
            parse_mode="HTML",
        )
        if isinstance(message, dict):
            game["predictions"]["message_id"] = message.get("message_id")

    def handle_predict(self, callback_id: str, game: dict | None, user: dict, pick: str, message: dict) -> None:
        predictions = (game or {}).get("predictions")
        if not predictions or not predictions.get("open"):
            self.answer_callback(callback_id, "🔒 Predictions are closed.")
            return
        if message.get("message_id") != predictions.get("message_id"):
            self.answer_callback(callback_id, "This prediction message is out of date.")
            return
        user_id = user.get("id")
        if user_id in game["captains"].values():
            self.answer_callback(callback_id, "🎟 Captains can't predict their own match. Spectators only!")
            return
        if pick not in ("home", "away"):
            self.answer_callback(callback_id, "Unknown prediction.")
            return
        predictions["votes"][str(user_id)] = {"name": self.player_label(user), "pick": pick}
        team = TEAMS[game["teams"][pick]]["name"]
        self.answer_callback(callback_id, f"🔮 You predicted {team}!")
        self.refresh_prediction_message(game)

    def close_predictions(self, game: dict) -> None:
        predictions = game.get("predictions")
        if predictions and predictions.get("open"):
            predictions["open"] = False
            self.refresh_prediction_message(game)

    def resolve_predictions(self, game: dict, winner: str | None) -> None:
        predictions = game.get("predictions")
        if not predictions:
            return
        self.close_predictions(game)
        votes = predictions.get("votes") or {}
        if not votes:
            return
        voters = [
            {"id": int(user_id), "name": vote["name"], "pick": vote["pick"]}
            for user_id, vote in votes.items()
        ]
        try:
            results = self.stats.record_predictions(voters, winner)
        except sqlite3.Error as error:
            print(f"Could not record predictions: {error}", file=sys.stderr)
            results = [
                {**voter, "correct": winner == voter["pick"], "points": 10 if winner == voter["pick"] else 2}
                for voter in voters
            ]
        right = [r for r in results if r["correct"]]
        wrong = [r for r in results if not r["correct"]]
        title = (
            f"🏆 <b>{esc(TEAMS[game['teams'][winner]]['name'])}</b> won the match!"
            if winner else "🤝 The match ended level, so nobody called it."
        )
        lines = ["🔮 <b>PREDICTION RESULTS</b>", DIVIDER, title, ""]
        if right:
            lines.append(f"✅ <b>Correct ({len(right)}):</b> +10 each")
            lines.append(", ".join(esc(r["name"]) for r in right[:15]))
        if wrong:
            lines.append(f"\n❌ <b>Missed it ({len(wrong)}):</b> +2 each")
            lines.append(", ".join(esc(r["name"]) for r in wrong[:15]))
        self.safe_reply(game["chat_id"], "\n".join(lines), parse_mode="HTML")

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
        overs = match["overs_limit"]
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
            f"{self.innings_heading(game)}  •  {escape(team_name)}",
            "",
            f"{score_icon} <b>Score: {match['score']}/{match['wickets']} "
            f"({format_overs(match['balls'])}/{overs} overs)</b>",
            f"📈 <b>Run rate (RR/CRR): {current_run_rate:.2f} runs/over</b>",
        ]
        extras = innings.get("extras") or {}
        if sum(extras.values()):
            parts = [f"{label} {extras[key]}" for key, label in (("wd", "wd"), ("nb", "nb"), ("b", "b")) if extras.get(key)]
            lines.append(f"➕ Extras: <b>{sum(extras.values())}</b> ({', '.join(parts)})")
        if innings.get("free_hit") and game["stage"] == "live":
            lines.append("🆓 <b>FREE HIT!</b> The next ball cannot get a batter out (except run out)")
        if game["stage"] == "live" and game.get("sim_mode") != "over" and self.rules.get("drs_reviews", 0):
            lines.append(f"📺 DRS reviews left: <b>{innings.get('reviews_left', 0)}</b>")
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
                f"<code>({format_overs(result['balls'])}/{result.get('overs_limit', game['overs_limit'])} overs)</code>"
            )
        for index, result in enumerate((game.get("super_over") or {}).get("results", []), start=1):
            lines.append(
                f"⚡ Super Over {index}{'st' if index == 1 else 'nd'}: "
                f"{escape(result['team'])} <b>{result['score']}/{result['wickets']}</b>"
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
                marker = f" <i>{escape(batter['how_out'])}</i>" if batter.get("how_out") and not compact else " out"
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
            if game["innings_number"] == 3:
                lines.append("⚡ Super Over: the other team has one over to beat it!")
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
            batting_turn = game["phase"] in ("bat", "drs")
            active_side = game["batting_side"] if batting_turn else self.bowling_side(game)
            role = "Batting" if batting_turn else "Bowling"
            role_icon = "🏏" if batting_turn else "🎳"
            captain = game["captain_names"][active_side]
            lines.append(f"\n{DIVIDER}")
            lines.append(f"🎮 <b>{role} captain:</b> {escape(captain)}")
            over_note = " (applies to the whole over)" if game.get("sim_mode") == "over" else ""
            if game["phase"] == "drs":
                pending = innings.get("drs_pending") or {}
                lines.append(
                    f"📺 <b>OUT!</b> {escape(pending.get('batter', ''))} is given out "
                    f"<i>({escape(pending.get('how', ''))})</i>"
                )
                lines.append(
                    f"📺 <b>Review the decision?</b> {innings.get('reviews_left', 0)} review(s) left"
                )
            elif game["phase"] == "pick_bowler":
                lines.extend(self.bowler_pick_text(game))
            else:
                lines.append(
                    f"{role_icon} <b>Choose batting approach:</b>{over_note}"
                    if game["phase"] == "bat"
                    else f"{role_icon} <b>Choose bowling style:</b>{over_note}"
                )
        return "\n".join(lines)

    @staticmethod
    def innings_heading(game: dict) -> str:
        number = game["innings_number"]
        if number >= 3:
            return f"⚡ <b>SUPER OVER • {'1st' if number == 3 else '2nd'} INNINGS</b>"
        return f"✨ <b>{number}{'st' if number == 1 else 'nd'} INNINGS</b>"

    def live_keyboard(self, game: dict) -> list | None:
        if game["stage"] == "innings_break":
            label = (
                "▶️ Start the Super Over chase" if game["innings_number"] == 3
                else "▶️ Start second innings"
            )
            return [[self.button(label, "second-innings")]]
        if game["stage"] != "live":
            return None
        if game["phase"] == "drs":
            return self.drs_keyboard(game)
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
            final_result = self.final_result_text(game) if stage == "complete" else None
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
            ("scorecard", "🖼 PNG scorecard of the match"),
            ("profile", "👤 Your captain profile"),
            ("stats", "🏆 Leaderboards"),
            ("myid", "🆔 Show your Telegram ID"),
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
