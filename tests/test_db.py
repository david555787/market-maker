"""Tests for db.py. Each test gets its own empty temporary database."""
import random
import sqlite3
import uuid
from datetime import datetime, timedelta

import pytest

import config
import db
import game_logic


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point db.py at a fresh file for every test (autouse = no need to request it)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def new_state():
    return game_logic.create_game(random.Random(0))


def played_state(rounds, score):
    """A settled game state after `rounds` rounds, with an exact final score.

    rounds=20 goes through resolve_round's own auto-finish; fewer rounds are
    settled early with finish_game, like the /finish endpoint does.
    """
    rng = random.Random(0)
    state = game_logic.create_game(rng)
    for _ in range(rounds):
        state, _outcome = game_logic.resolve_round(state, 98, 102, rng)
    if not state["finished"]:
        state = game_logic.finish_game(state)
    state["result"]["final_pnl"] = score
    return state


def fetch_row(game_id):
    """Read a raw row, bypassing db.py, to check what was really stored."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    conn.close()
    return row


def add_finished_game(name, score, rounds=game_logic.NUM_ROUNDS):
    """Create a game and finish it after `rounds` rounds with an exact score.

    By default the game is played through all rounds (a ranked game).
    """
    game_id = db.create_game_record(new_state(), name)
    db.finish_game_record(game_id, played_state(rounds, score))
    return game_id


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------
def test_init_db_is_safe_to_call_twice_and_keeps_data():
    state = new_state()
    game_id = db.create_game_record(state)
    db.init_db()
    db.init_db()
    assert db.load_state(game_id) == state


# ---------------------------------------------------------------------------
# create_game_record / load_state
# ---------------------------------------------------------------------------
def test_create_game_record_returns_a_uuid4_string():
    game_id = db.create_game_record(new_state())
    assert isinstance(game_id, str)
    assert uuid.UUID(game_id).version == 4


def test_each_game_gets_a_different_id():
    assert db.create_game_record(new_state()) != db.create_game_record(new_state())


def test_new_record_has_expected_columns():
    game_id = db.create_game_record(new_state())
    row = fetch_row(game_id)
    assert row["status"] == "active"
    assert row["final_score"] is None
    assert row["player_name"] == "Anonymous"


def test_created_at_is_a_utc_timestamp():
    row = fetch_row(db.create_game_record(new_state()))
    created = datetime.fromisoformat(row["created_at"])
    assert created.utcoffset() == timedelta(0)


def test_load_state_round_trips_the_full_state_including_true_value():
    state = new_state()
    game_id = db.create_game_record(state)
    loaded = db.load_state(game_id)
    assert loaded == state
    assert loaded["true_value"] == state["true_value"]


def test_load_state_returns_none_for_unknown_id():
    assert db.load_state("does-not-exist") is None


# ---------------------------------------------------------------------------
# Player names
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("Alice", "Alice"),
    ("  Alice  ", "Alice"),
    ("x" * 25, "x" * 20),
    ("", None),
    ("   ", None),
    (None, None),
    (123, None),
])
def test_clean_player_name(raw, expected):
    assert db.clean_player_name(raw) == expected


def test_name_is_trimmed_to_20_characters_when_stored():
    game_id = db.create_game_record(new_state(), "x" * 30)
    assert fetch_row(game_id)["player_name"] == "x" * 20


@pytest.mark.parametrize("bad_name", [None, "", "   ", 42])
def test_missing_or_blank_name_becomes_anonymous(bad_name):
    game_id = db.create_game_record(new_state(), bad_name)
    assert fetch_row(game_id)["player_name"] == "Anonymous"


def test_sql_in_a_name_is_stored_as_plain_text():
    # Parameterized SQL: the hostile text is just data, the table survives.
    evil = "'); DROP TABLE games; --"
    game_id = db.create_game_record(new_state(), evil)
    assert fetch_row(game_id)["player_name"] == evil[:20]
    assert db.load_state(game_id) is not None


# ---------------------------------------------------------------------------
# save_state
# ---------------------------------------------------------------------------
def test_save_state_updates_the_stored_state_and_keeps_status_active():
    state = new_state()
    game_id = db.create_game_record(state)
    state["cash"] = 123.45
    db.save_state(game_id, state)
    assert db.load_state(game_id)["cash"] == 123.45
    assert fetch_row(game_id)["status"] == "active"


def test_save_state_cannot_overwrite_a_completed_game():
    game_id = add_finished_game("Alice", 5.0)
    stale = new_state()
    stale["cash"] = 999.0
    db.save_state(game_id, stale)
    assert db.load_state(game_id)["finished"] is True


def test_save_state_cannot_overwrite_an_early_finished_game():
    game_id = add_finished_game("Alice", 5.0, rounds=3)
    stale = new_state()
    stale["cash"] = 999.0
    db.save_state(game_id, stale)
    assert db.load_state(game_id)["finished"] is True


# ---------------------------------------------------------------------------
# finish_game_record
# ---------------------------------------------------------------------------
def test_full_game_is_marked_completed_and_its_score_is_stored():
    game_id = add_finished_game("Alice", 12.5)
    row = fetch_row(game_id)
    assert row["status"] == "completed"
    assert row["final_score"] == 12.5
    assert db.load_state(game_id)["finished"] is True


def test_early_finish_is_marked_ended_early_but_its_score_is_still_stored():
    game_id = add_finished_game("Alice", 3.5, rounds=5)
    row = fetch_row(game_id)
    assert row["status"] == "ended_early"
    assert row["final_score"] == 3.5
    assert db.load_state(game_id)["finished"] is True


def test_finish_keeps_the_existing_name_when_none_is_given():
    game_id = db.create_game_record(new_state(), "Alice")
    db.finish_game_record(game_id, game_logic.finish_game(new_state()))
    assert fetch_row(game_id)["player_name"] == "Alice"


def test_finish_with_a_name_replaces_the_old_name():
    game_id = db.create_game_record(new_state(), "Alice")
    db.finish_game_record(game_id, game_logic.finish_game(new_state()), "  Bob  ")
    assert fetch_row(game_id)["player_name"] == "Bob"


def test_finish_with_a_blank_name_keeps_the_old_name():
    game_id = db.create_game_record(new_state(), "Alice")
    db.finish_game_record(game_id, game_logic.finish_game(new_state()), "   ")
    assert fetch_row(game_id)["player_name"] == "Alice"


# ---------------------------------------------------------------------------
# get_leaderboard
# ---------------------------------------------------------------------------
def test_leaderboard_is_empty_at_first():
    assert db.get_leaderboard() == []


def test_leaderboard_is_sorted_by_score_descending():
    add_finished_game("low", -5.0)
    add_finished_game("high", 20.0)
    add_finished_game("mid", 3.0)
    names = [entry["player_name"] for entry in db.get_leaderboard()]
    assert names == ["high", "mid", "low"]


def test_leaderboard_ignores_unfinished_games():
    db.create_game_record(new_state(), "still playing")
    add_finished_game("done", 1.0)
    names = [entry["player_name"] for entry in db.get_leaderboard()]
    assert names == ["done"]


def test_completed_game_is_included_on_the_leaderboard():
    add_finished_game("full", 8.0)
    entries = db.get_leaderboard()
    assert [(e["player_name"], e["final_score"]) for e in entries] == [("full", 8.0)]


def test_early_finished_game_is_excluded_from_the_leaderboard():
    # A 0-round finish scores 0.0, which would beat the negative score below
    # if early finishes were ranked.
    add_finished_game("early", 0.0, rounds=0)
    add_finished_game("full", -5.0)
    names = [entry["player_name"] for entry in db.get_leaderboard()]
    assert names == ["full"]


def test_finishing_one_round_early_is_still_excluded():
    add_finished_game("almost", 50.0, rounds=game_logic.NUM_ROUNDS - 1)
    assert db.get_leaderboard() == []


def test_leaderboard_ties_go_to_the_earlier_game():
    add_finished_game("first", 7.0)
    add_finished_game("second", 7.0)
    names = [entry["player_name"] for entry in db.get_leaderboard()]
    assert names == ["first", "second"]


def test_leaderboard_default_limit_is_10_and_limit_can_be_changed():
    for i in range(12):
        add_finished_game(f"p{i}", float(i))
    assert len(db.get_leaderboard()) == 10
    assert len(db.get_leaderboard(limit=3)) == 3


def test_leaderboard_entries_expose_only_name_score_and_date():
    add_finished_game("Alice", 4.0)
    entry = db.get_leaderboard()[0]
    assert set(entry) == {"player_name", "final_score", "created_at"}
    assert entry["final_score"] == 4.0