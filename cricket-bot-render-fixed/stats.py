"""Career statistics: captain profiles, player leaderboards and spectator points.

Everything is stored in the bot's SQLite database. On hosts with an ephemeral
disk (such as Render's free plan) the file is wiped on every restart or deploy;
set BOT_DATABASE_PATH to a persistent disk to keep the stats.
"""

from __future__ import annotations

import sqlite3
import time

CAPTAIN_COLUMNS = (
    "matches", "wins", "losses", "ties", "runs_for", "runs_against",
    "highest_total", "toss_wins", "potm", "drs_used", "drs_success", "super_overs",
)
PLAYER_COLUMNS = (
    "matches", "innings", "not_outs", "runs", "balls", "fours", "sixes", "highest",
    "fifties", "hundreds", "wickets", "balls_bowled", "runs_conceded", "best_w",
    "best_r", "five_wickets", "potm",
)


class StatsStore:
    def __init__(self, database: sqlite3.Connection):
        self.database = database
        with self.database:
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS captain_stats (user_id INTEGER PRIMARY KEY, name TEXT, "
                + ", ".join(f"{column} INTEGER NOT NULL DEFAULT 0" for column in CAPTAIN_COLUMNS)
                + ")"
            )
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS player_stats (name TEXT PRIMARY KEY, "
                + ", ".join(f"{column} INTEGER NOT NULL DEFAULT 0" for column in PLAYER_COLUMNS)
                + ")"
            )
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS spectator_stats (user_id INTEGER PRIMARY KEY, name TEXT, "
                "predictions INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0, "
                "points INTEGER NOT NULL DEFAULT 0)"
            )
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS match_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "chat_id INTEGER, played_at INTEGER, home_team TEXT, away_team TEXT, result TEXT)"
            )
            self.database.execute(
                "CREATE TABLE IF NOT EXISTS known_chats (chat_id INTEGER PRIMARY KEY, title TEXT, "
                "last_seen INTEGER)"
            )

    # ------------------------------------------------------------------ helpers
    def _row(self, table: str, key_column: str, key, columns: tuple[str, ...]) -> dict:
        cursor = self.database.execute(
            f"SELECT {', '.join(columns)} FROM {table} WHERE {key_column} = ?", (key,)
        )
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else {column: 0 for column in columns}

    def _save(self, table: str, key_column: str, key, values: dict, extra: dict | None = None) -> None:
        fields = {key_column: key, **(extra or {}), **values}
        columns = list(fields)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != key_column)
        self.database.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
            f"ON CONFLICT({key_column}) DO UPDATE SET {updates}",
            [fields[column] for column in columns],
        )

    # ------------------------------------------------------------------ recording
    def record_match(self, summary: dict) -> None:
        """Store a finished match. `summary` is built by the bot (see bot.match_summary)."""
        with self.database:
            winner = summary.get("winner_side")
            for side in ("home", "away"):
                captain = (summary.get("captains") or {}).get(side)
                if not captain or not captain.get("id"):
                    continue
                other = "away" if side == "home" else "home"
                own = next((i for i in summary["innings"] if i["side"] == side), None)
                opposing = next((i for i in summary["innings"] if i["side"] == other), None)
                row = self._row("captain_stats", "user_id", captain["id"], CAPTAIN_COLUMNS)
                row["matches"] += 1
                if winner is None:
                    row["ties"] += 1
                elif winner == side:
                    row["wins"] += 1
                else:
                    row["losses"] += 1
                if own:
                    row["runs_for"] += own["score"]
                    row["highest_total"] = max(row["highest_total"], own["score"])
                if opposing:
                    row["runs_against"] += opposing["score"]
                if summary.get("toss_winner_side") == side:
                    row["toss_wins"] += 1
                if (summary.get("potm") or {}).get("side") == side:
                    row["potm"] += 1
                drs = (summary.get("drs") or {}).get(side, {})
                row["drs_used"] += drs.get("used", 0)
                row["drs_success"] += drs.get("success", 0)
                if summary.get("super_over"):
                    row["super_overs"] += 1
                self._save("captain_stats", "user_id", captain["id"], row, {"name": captain.get("name", "")})

            potm_name = (summary.get("potm") or {}).get("name")
            seen: set[str] = set()
            for innings in summary["innings"]:
                for batter in innings.get("batters", []):
                    row = self._row("player_stats", "name", batter["name"], PLAYER_COLUMNS)
                    if batter["name"] not in seen:
                        row["matches"] += 1
                        seen.add(batter["name"])
                    if batter["balls"] or batter["out"]:
                        row["innings"] += 1
                        if not batter["out"]:
                            row["not_outs"] += 1
                    row["runs"] += batter["runs"]
                    row["balls"] += batter["balls"]
                    row["fours"] += batter["fours"]
                    row["sixes"] += batter["sixes"]
                    row["highest"] = max(row["highest"], batter["runs"])
                    if batter["runs"] >= 100:
                        row["hundreds"] += 1
                    elif batter["runs"] >= 50:
                        row["fifties"] += 1
                    self._save("player_stats", "name", batter["name"], row)
                for name, bowling in (innings.get("bowlers") or {}).items():
                    row = self._row("player_stats", "name", name, PLAYER_COLUMNS)
                    if name not in seen:
                        row["matches"] += 1
                        seen.add(name)
                    row["wickets"] += bowling["wickets"]
                    row["balls_bowled"] += bowling["balls"]
                    row["runs_conceded"] += bowling["runs"]
                    if bowling["wickets"] >= 5:
                        row["five_wickets"] += 1
                    best_w, best_r = row["best_w"], row["best_r"]
                    if bowling["wickets"] > best_w or (
                        bowling["wickets"] == best_w and bowling["wickets"] and bowling["runs"] < best_r
                    ):
                        row["best_w"], row["best_r"] = bowling["wickets"], bowling["runs"]
                    self._save("player_stats", "name", name, row)
            if potm_name:
                row = self._row("player_stats", "name", potm_name, PLAYER_COLUMNS)
                row["potm"] += 1
                self._save("player_stats", "name", potm_name, row)

            self.database.execute(
                "INSERT INTO match_log (chat_id, played_at, home_team, away_team, result) VALUES (?, ?, ?, ?, ?)",
                (
                    summary.get("chat_id"), int(time.time()), summary.get("home_team", ""),
                    summary.get("away_team", ""), summary.get("result", ""),
                ),
            )

    def record_predictions(self, voters: list[dict], winner_side: str | None) -> list[dict]:
        """Award spectator points. Returns each voter with `correct` and `points`."""
        results = []
        with self.database:
            for voter in voters:
                correct = winner_side is not None and voter["pick"] == winner_side
                points = 10 if correct else 2  # a small reward for taking part
                row = self._row(
                    "spectator_stats", "user_id", voter["id"], ("predictions", "correct", "points")
                )
                row["predictions"] += 1
                row["correct"] += 1 if correct else 0
                row["points"] += points
                self._save("spectator_stats", "user_id", voter["id"], row, {"name": voter.get("name", "")})
                results.append({**voter, "correct": correct, "points": points})
        return results

    def touch_chat(self, chat_id: int, title: str = "") -> None:
        with self.database:
            self._save(
                "known_chats", "chat_id", chat_id,
                {"title": title or "", "last_seen": int(time.time())},
            )

    # ------------------------------------------------------------------ queries
    def captain_profile(self, user_id: int) -> dict | None:
        cursor = self.database.execute(
            f"SELECT name, {', '.join(CAPTAIN_COLUMNS)} FROM captain_stats WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        profile = dict(zip(("name", *CAPTAIN_COLUMNS), row))
        profile["user_id"] = user_id
        return profile

    def spectator_profile(self, user_id: int) -> dict | None:
        cursor = self.database.execute(
            "SELECT name, predictions, correct, points FROM spectator_stats WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        return dict(zip(("name", "predictions", "correct", "points"), row)) if row else None

    def top_captains(self, limit: int = 5) -> list[dict]:
        cursor = self.database.execute(
            "SELECT name, matches, wins, losses, ties FROM captain_stats WHERE matches > 0 "
            "ORDER BY wins DESC, matches ASC, name ASC LIMIT ?",
            (limit,),
        )
        return [dict(zip(("name", "matches", "wins", "losses", "ties"), row)) for row in cursor]

    def top_run_scorers(self, limit: int = 5) -> list[dict]:
        cursor = self.database.execute(
            "SELECT name, runs, balls, highest, hundreds, fifties FROM player_stats WHERE runs > 0 "
            "ORDER BY runs DESC, name ASC LIMIT ?",
            (limit,),
        )
        return [
            dict(zip(("name", "runs", "balls", "highest", "hundreds", "fifties"), row))
            for row in cursor
        ]

    def top_wicket_takers(self, limit: int = 5) -> list[dict]:
        cursor = self.database.execute(
            "SELECT name, wickets, balls_bowled, runs_conceded, best_w, best_r FROM player_stats "
            "WHERE wickets > 0 ORDER BY wickets DESC, runs_conceded ASC, name ASC LIMIT ?",
            (limit,),
        )
        return [
            dict(zip(("name", "wickets", "balls_bowled", "runs_conceded", "best_w", "best_r"), row))
            for row in cursor
        ]

    def top_predictors(self, limit: int = 5) -> list[dict]:
        cursor = self.database.execute(
            "SELECT name, predictions, correct, points FROM spectator_stats WHERE predictions > 0 "
            "ORDER BY points DESC, correct DESC, name ASC LIMIT ?",
            (limit,),
        )
        return [dict(zip(("name", "predictions", "correct", "points"), row)) for row in cursor]

    def player(self, name: str) -> dict | None:
        cursor = self.database.execute(
            f"SELECT {', '.join(PLAYER_COLUMNS)} FROM player_stats WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        return dict(zip(PLAYER_COLUMNS, row)) if row else None

    # ------------------------------------------------------------------ admin
    def totals(self) -> dict:
        def count(sql: str) -> int:
            return self.database.execute(sql).fetchone()[0]

        return {
            "matches": count("SELECT COUNT(*) FROM match_log"),
            "captains": count("SELECT COUNT(*) FROM captain_stats"),
            "players": count("SELECT COUNT(*) FROM player_stats"),
            "spectators": count("SELECT COUNT(*) FROM spectator_stats"),
            "chats": count("SELECT COUNT(*) FROM known_chats"),
        }

    def recent_matches(self, limit: int = 5) -> list[dict]:
        cursor = self.database.execute(
            "SELECT chat_id, played_at, home_team, away_team, result FROM match_log "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            dict(zip(("chat_id", "played_at", "home_team", "away_team", "result"), row))
            for row in cursor
        ]

    def known_chat_ids(self) -> list[int]:
        return [row[0] for row in self.database.execute("SELECT chat_id FROM known_chats")]

    def reset(self) -> None:
        with self.database:
            for table in ("captain_stats", "player_stats", "spectator_stats", "match_log"):
                self.database.execute(f"DELETE FROM {table}")
