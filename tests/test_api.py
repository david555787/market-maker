"""API tests using Flask's built-in test client (no real server needed).

Each test gets an empty temporary database and a seeded random generator, so
results are reproducible.
"""
import random
import sqlite3

import pytest

import app as app_module
import config
import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "api_test.db"))
    db.init_db()
    # Routes read app_module.rng at call time, so this swap takes effect.
    monkeypatch.setattr(app_module, "rng", random.Random(1))
    return app_module.app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def new_game(client, **body):
    """Create a game and return its id."""
    response = client.post("/api/games", json=body)
    assert response.status_code == 201
    return response.get_json()["game_id"]


def post_quote(client, game_id, bid=98, ask=102):
    return client.post(f"/api/games/{game_id}/quote", json={"bid": bid, "ask": ask})


def play_full_game(client, game_id):
    """Play all 20 rounds and return the response to the last one."""
    response = None
    for _ in range(20):
        response = post_quote(client, game_id)
        assert response.status_code == 200
    return response


def stored_name(game_id):
    """Read the player_name column directly (it is not part of any API response
    except the leaderboard, which hides early finishes)."""
    conn = sqlite3.connect(config.DB_PATH)
    row = conn.execute(
        "SELECT player_name FROM games WHERE id = ?", (game_id,)
    ).fetchone()
    conn.close()
    return row[0]


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_homepage_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Market Maker" in response.data


def test_unknown_route_returns_json_404(client):
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert "error" in response.get_json()


# ---------------------------------------------------------------------------
# POST /api/games
# ---------------------------------------------------------------------------
def test_create_game_returns_id_and_initial_state_without_true_value(client):
    response = client.post("/api/games")
    assert response.status_code == 201
    data = response.get_json()
    assert isinstance(data["game_id"], str)
    state = data["state"]
    assert state["current_round"] == 0
    assert state["inventory"] == 0
    assert state["finished"] is False
    assert state["rounds_history"] == []
    assert "true_value" not in state


def test_create_game_accepts_a_player_name(client):
    game_id = new_game(client, player_name="Alice")
    assert stored_name(game_id) == "Alice"


def test_create_game_rejects_a_non_string_name(client):
    response = client.post("/api/games", json={"player_name": 123})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_create_game_rejects_a_non_object_body(client):
    response = client.post("/api/games", json=[1, 2, 3])
    assert response.status_code == 400


def test_true_value_is_stored_server_side_but_never_sent(client):
    game_id = new_game(client)
    assert "true_value" in db.load_state(game_id)       # the server knows V
    text = client.get(f"/api/games/{game_id}").get_data(as_text=True)
    assert "true_value" not in text                      # the client does not


# ---------------------------------------------------------------------------
# GET /api/games/<id>
# ---------------------------------------------------------------------------
def test_get_game_returns_public_state(client):
    game_id = new_game(client)
    response = client.get(f"/api/games/{game_id}")
    assert response.status_code == 200
    assert response.get_json()["state"]["current_round"] == 0


def test_get_unknown_game_returns_404(client):
    response = client.get("/api/games/does-not-exist")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Game not found"}


# ---------------------------------------------------------------------------
# POST /api/games/<id>/quote
# ---------------------------------------------------------------------------
def test_quote_returns_outcome_and_updated_state(client):
    game_id = new_game(client)
    response = post_quote(client, game_id, bid=99, ask=101)
    assert response.status_code == 200
    data = response.get_json()
    assert set(data["outcome"]) == {"round", "bid", "ask", "action", "price"}
    assert data["outcome"]["round"] == 1
    assert data["outcome"]["action"] in ("buy", "sell", "none")
    assert data["state"]["current_round"] == 1
    assert len(data["state"]["rounds_history"]) == 1


def test_quote_is_persisted(client):
    game_id = new_game(client)
    post_quote(client, game_id)
    post_quote(client, game_id)
    state = client.get(f"/api/games/{game_id}").get_json()["state"]
    assert state["current_round"] == 2
    assert len(state["rounds_history"]) == 2


def test_no_secrets_leak_while_the_game_is_running(client):
    game_id = new_game(client)
    for _ in range(5):
        text = post_quote(client, game_id).get_data(as_text=True)
        assert "true_value" not in text
        assert "informed" not in text
    text = client.get(f"/api/games/{game_id}").get_data(as_text=True)
    assert "true_value" not in text
    assert "informed" not in text


@pytest.mark.parametrize("body", [
    {"bid": "abc", "ask": 101},
    {"bid": 99, "ask": None},
    {"bid": True, "ask": 101},
    {"bid": 0, "ask": 5},
    {"bid": -3, "ask": 5},
    {"bid": 101, "ask": 99},
    {"bid": 100, "ask": 100},
    {"bid": 1, "ask": 5000},
])
def test_invalid_quotes_return_400_and_do_not_advance_the_game(client, body):
    game_id = new_game(client)
    response = client.post(f"/api/games/{game_id}/quote", json=body)
    assert response.status_code == 400
    assert "error" in response.get_json()
    state = client.get(f"/api/games/{game_id}").get_json()["state"]
    assert state["current_round"] == 0


@pytest.mark.parametrize("body", [{}, {"bid": 99}, {"ask": 101}, [1, 2]])
def test_missing_fields_or_wrong_body_shape_return_400(client, body):
    game_id = new_game(client)
    response = client.post(f"/api/games/{game_id}/quote", json=body)
    assert response.status_code == 400


def test_non_json_body_returns_400(client):
    game_id = new_game(client)
    response = client.post(
        f"/api/games/{game_id}/quote", data="not json", content_type="text/plain"
    )
    assert response.status_code == 400


def test_quote_for_unknown_game_returns_404(client):
    response = post_quote(client, "does-not-exist")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Full game: auto-finish after round 20
# ---------------------------------------------------------------------------
def test_game_auto_finishes_after_round_20_and_reveals_the_value(client):
    game_id = new_game(client)
    for _ in range(19):
        response = post_quote(client, game_id)
        assert response.get_json()["state"]["finished"] is False
    response = post_quote(client, game_id)

    state = response.get_json()["state"]
    assert state["finished"] is True
    assert state["current_round"] == 20
    assert state["true_value"] == db.load_state(game_id)["true_value"]
    assert set(state["result"]) == {"final_pnl", "informed_pnl", "uninformed_pnl"}
    assert all("trader_informed" in r for r in state["rounds_history"])


def test_quote_after_the_game_is_finished_returns_409(client):
    game_id = new_game(client)
    play_full_game(client, game_id)
    response = post_quote(client, game_id)
    assert response.status_code == 409
    assert "error" in response.get_json()


def test_finished_game_stays_revealed_on_get(client):
    game_id = new_game(client)
    play_full_game(client, game_id)
    state = client.get(f"/api/games/{game_id}").get_json()["state"]
    assert state["finished"] is True
    assert "true_value" in state


def test_even_an_invalid_quote_on_a_finished_game_returns_409(client):
    game_id = new_game(client)
    play_full_game(client, game_id)
    response = client.post(f"/api/games/{game_id}/quote", json={"bid": 5, "ask": 1})
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/games/<id>/finish
# ---------------------------------------------------------------------------
def test_finish_early_reveals_the_value_and_settles(client):
    game_id = new_game(client)
    post_quote(client, game_id)
    response = client.post(f"/api/games/{game_id}/finish")
    assert response.status_code == 200
    state = response.get_json()["state"]
    assert state["finished"] is True
    assert state["current_round"] == 1
    assert "true_value" in state
    assert "final_pnl" in state["result"]


def test_finish_twice_returns_409(client):
    game_id = new_game(client)
    client.post(f"/api/games/{game_id}/finish")
    response = client.post(f"/api/games/{game_id}/finish")
    assert response.status_code == 409


def test_finish_after_auto_finish_returns_409(client):
    game_id = new_game(client)
    play_full_game(client, game_id)
    response = client.post(f"/api/games/{game_id}/finish")
    assert response.status_code == 409


def test_quote_after_early_finish_returns_409(client):
    game_id = new_game(client)
    client.post(f"/api/games/{game_id}/finish")
    assert post_quote(client, game_id).status_code == 409


def test_finish_unknown_game_returns_404(client):
    assert client.post("/api/games/does-not-exist/finish").status_code == 404


def test_finish_rejects_a_non_string_name(client):
    game_id = new_game(client)
    response = client.post(f"/api/games/{game_id}/finish", json={"player_name": 5})
    assert response.status_code == 400
    # The failed request must not have finished the game.
    state = client.get(f"/api/games/{game_id}").get_json()["state"]
    assert state["finished"] is False


def test_finish_can_replace_the_stored_name_for_an_early_finish(client):
    game_id = new_game(client, player_name="Alice")
    client.post(f"/api/games/{game_id}/finish", json={"player_name": "Bob"})
    assert stored_name(game_id) == "Bob"


# ---------------------------------------------------------------------------
# GET /api/leaderboard
# ---------------------------------------------------------------------------
def test_leaderboard_is_empty_at_first(client):
    response = client.get("/api/leaderboard")
    assert response.status_code == 200
    assert response.get_json() == {"leaderboard": []}


def test_leaderboard_lists_completed_games_best_first(client):
    for name in ("A", "B", "C"):
        game_id = new_game(client, player_name=name)
        play_full_game(client, game_id)
    new_game(client, player_name="unfinished")

    entries = client.get("/api/leaderboard").get_json()["leaderboard"]
    assert len(entries) == 3
    assert "unfinished" not in [e["player_name"] for e in entries]
    scores = [e["final_score"] for e in entries]
    assert scores == sorted(scores, reverse=True)


def test_completed_game_is_on_the_leaderboard_with_its_score(client):
    game_id = new_game(client, player_name="Alice")
    play_full_game(client, game_id)

    entries = client.get("/api/leaderboard").get_json()["leaderboard"]
    assert len(entries) == 1
    assert entries[0]["player_name"] == "Alice"
    final_pnl = client.get(f"/api/games/{game_id}").get_json()["state"]["result"]["final_pnl"]
    assert entries[0]["final_score"] == final_pnl


def test_early_finish_is_not_on_the_leaderboard_but_the_player_gets_the_score(client):
    game_id = new_game(client, player_name="Early")
    for _ in range(3):
        post_quote(client, game_id)
    response = client.post(f"/api/games/{game_id}/finish")

    assert response.status_code == 200
    assert "final_pnl" in response.get_json()["state"]["result"]
    assert client.get("/api/leaderboard").get_json() == {"leaderboard": []}


def test_zero_round_early_finish_is_not_ranked_next_to_a_completed_game(client):
    full_id = new_game(client, player_name="Full")
    play_full_game(client, full_id)
    early_id = new_game(client, player_name="Early")
    client.post(f"/api/games/{early_id}/finish")

    entries = client.get("/api/leaderboard").get_json()["leaderboard"]
    assert [e["player_name"] for e in entries] == ["Full"]


def test_leaderboard_uses_the_name_given_at_creation_after_auto_finish(client):
    game_id = new_game(client, player_name="Alice")
    play_full_game(client, game_id)
    entries = client.get("/api/leaderboard").get_json()["leaderboard"]
    assert entries[0]["player_name"] == "Alice"


def test_long_names_are_trimmed_and_missing_names_become_anonymous(client):
    long_id = new_game(client, player_name="y" * 40)
    play_full_game(client, long_id)
    anon_id = new_game(client)
    play_full_game(client, anon_id)
    names = {e["player_name"] for e in client.get("/api/leaderboard").get_json()["leaderboard"]}
    assert names == {"y" * 20, "Anonymous"}


def test_leaderboard_never_contains_true_value(client):
    game_id = new_game(client, player_name="Alice")
    play_full_game(client, game_id)
    text = client.get("/api/leaderboard").get_data(as_text=True)
    assert "true_value" not in text
    assert "state_json" not in text