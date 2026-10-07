"""SQLite persistence layer (built-in sqlite3 only, no ORM).

NOTE: SQLite on Render's free tier is ephemeral. The disk is wiped on every
redeploy/restart, so games and the leaderboard can reset. That is accepted
for this project (we do not implement Postgres).

Every function opens its own short-lived connection and closes it again.
That is simple, and safe with several gunicorn workers or Flask threads,
because no connection object is ever shared.

All SQL is parameterized (the `?` placeholders). User input is never pasted
into an SQL string, which is what prevents SQL injection.
"""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone

import config
# game_logic is pure Python (no Flask). We import it only to reuse NUM_ROUNDS,
# so the number 20 is defined in exactly one place.
import game_logic

MAX_NAME_LENGTH = 20
DEFAULT_PLAYER_NAME = "Anonymous"

# A game moves from "active" to exactly one of the two final statuses.
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"      # played through all rounds: ranked
STATUS_ENDED_EARLY = "ended_early"  # finished before the last round: not ranked


def _connect():
    # config.DB_PATH is read at call time (not copied at import time), so
    # tests can point it at a temporary file.
    conn = sqlite3.connect(config.DB_PATH)
    # Row lets us read columns by name (row["state_json"]) instead of index.
    conn.row_factory = sqlite3.Row
    return conn


# Pattern used in every function below:
#   with closing(conn):  -> always closes the connection when we are done
#   with conn:           -> commits on success, rolls back if an error occurs
# sqlite3's own `with conn` does NOT close the connection, so we need both.
def init_db():
    """Create the games table if it does not exist. Safe to call repeatedly."""
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id           TEXT PRIMARY KEY,
                    state_json   TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    final_score  REAL,
                    player_name  TEXT,
                    created_at   TEXT NOT NULL
                )
                """
            )


def clean_player_name(player_name):
    """Trim a name to MAX_NAME_LENGTH. Returns None if it is blank or not text."""
    if not isinstance(player_name, str):
        return None
    # Strip again after cutting, in case the cut left a trailing space.
    name = player_name.strip()[:MAX_NAME_LENGTH].strip()
    return name or None


def create_game_record(state, player_name=None):
    """Insert a new active game and return its id (a uuid4 string)."""
    game_id = str(uuid.uuid4())
    # ISO 8601 in UTC sorts correctly as plain text and has no timezone ambiguity.
    created_at = datetime.now(timezone.utc).isoformat()
    name = clean_player_name(player_name) or DEFAULT_PLAYER_NAME
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO games (id, state_json, status, final_score, "
                "player_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (game_id, json.dumps(state), STATUS_ACTIVE, None, name, created_at),
            )
    return game_id


def load_state(game_id):
    """Return the full game state dict (including true_value), or None."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT state_json FROM games WHERE id = ?", (game_id,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["state_json"])


def save_state(game_id, state):
    """Store the state of a game that is still in progress."""
    with closing(_connect()) as conn:
        with conn:
            # "AND status = active" means a finished game (either kind) can
            # never be overwritten by accident: its score is final.
            conn.execute(
                "UPDATE games SET state_json = ? WHERE id = ? AND status = ?",
                (json.dumps(state), game_id, STATUS_ACTIVE),
            )


def _final_status(state):
    """Decide whether a settled game counts for the leaderboard.

    Early finishes must not be ranked: finishing after 0 rounds scores 0,
    which would beat every player who finished with a negative PnL.
    """
    if state["current_round"] >= game_logic.NUM_ROUNDS:
        return STATUS_COMPLETED
    return STATUS_ENDED_EARLY


def finish_game_record(game_id, state, player_name=None):
    """Store the final state, mark the game finished, and record its score.

    The score is stored for every finished game (the player still sees it),
    but only completed games can appear on the leaderboard.
    If player_name is blank or None, the name stored earlier is kept.
    """
    final_score = state["result"]["final_pnl"]
    status = _final_status(state)
    name = clean_player_name(player_name)
    with closing(_connect()) as conn:
        with conn:
            # COALESCE(?, player_name) means: use the new name if one was
            # given (not NULL), otherwise keep the current value.
            conn.execute(
                "UPDATE games SET state_json = ?, status = ?, final_score = ?, "
                "player_name = COALESCE(?, player_name) WHERE id = ?",
                (json.dumps(state), status, final_score, name, game_id),
            )


def get_leaderboard(limit=10):
    """Return the best completed games as a list of dicts, highest score first."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT player_name, final_score, created_at FROM games "
            "WHERE status = ? "
            # On equal scores the earlier game ranks higher.
            "ORDER BY final_score DESC, created_at ASC LIMIT ?",
            (STATUS_COMPLETED, limit),
        ).fetchall()
    # Only these three columns are selected, so state_json (which contains
    # true_value) can never leak through the leaderboard.
    return [dict(row) for row in rows]