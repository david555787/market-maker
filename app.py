"""HTTP layer only: routes, JSON parsing and error responses.

Game rules live in game_logic.py (no Flask there) and SQL in db.py. This file
connects them: load state -> call a pure function -> save state -> respond.

SECURITY RULE: every response that contains game state is built with
game_logic.public_state(). That single function decides what the player may
see, so true_value and informed flags cannot leak before the game ends.
"""
import random

from flask import Flask, jsonify, request

import config
import db
import game_logic

# static_folder="static" is Flask's default, written out for clarity.
# static_url_path="" serves static files from the site root.
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = config.SECRET_KEY

# Create the table at startup. This runs at import time so it also runs under
# gunicorn (which imports `app` and never executes the __main__ block below).
db.init_db()

# One random generator for the whole server, seeded from OS entropy.
# Routes pass it into game_logic; tests replace it with a seeded one.
rng = random.Random()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def error(message, status):
    """Every error uses the same JSON shape: {"error": "..."}."""
    return jsonify({"error": message}), status


def read_json_object():
    """Return the request body as a dict.

    Returns {} when there is no (parsable) body, and None when the body is
    valid JSON but not an object (for example a list).
    """
    body = request.get_json(silent=True)  # silent: never raises on bad JSON
    if body is None:
        return {}
    if not isinstance(body, dict):
        return None
    return body


def player_name_is_valid(body):
    """player_name is optional, but if present it must be a string."""
    name = body.get("player_name")
    return name is None or isinstance(name, str)


# ---------------------------------------------------------------------------
# Pages and health check
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Game API
# ---------------------------------------------------------------------------
@app.route("/api/games", methods=["POST"])
def create_game():
    body = read_json_object()
    if body is None or not player_name_is_valid(body):
        return error("Body must be a JSON object; player_name must be a string", 400)

    state = game_logic.create_game(rng)
    game_id = db.create_game_record(state, body.get("player_name"))
    return jsonify({"game_id": game_id, "state": game_logic.public_state(state)}), 201


@app.route("/api/games/<game_id>")
def get_game(game_id):
    state = db.load_state(game_id)
    if state is None:
        return error("Game not found", 404)
    return jsonify({"state": game_logic.public_state(state)})


@app.route("/api/games/<game_id>/quote", methods=["POST"])
def post_quote(game_id):
    state = db.load_state(game_id)
    if state is None:
        return error("Game not found", 404)

    body = read_json_object()
    if body is None or "bid" not in body or "ask" not in body:
        return error("Body must be a JSON object with bid and ask", 400)

    try:
        new_state, outcome = game_logic.resolve_round(
            state, body["bid"], body["ask"], rng
        )
    except game_logic.GameFinishedError:
        return error("Game is already finished", 409)
    except game_logic.InvalidQuoteError as exc:
        return error(str(exc), 400)

    # resolve_round auto-finishes the game after the last round. In that case
    # we also record the final score so it shows up on the leaderboard.
    if new_state["finished"]:
        db.finish_game_record(game_id, new_state)
    else:
        db.save_state(game_id, new_state)

    return jsonify({
        "outcome": outcome,
        "state": game_logic.public_state(new_state),
    })


@app.route("/api/games/<game_id>/finish", methods=["POST"])
def finish_game(game_id):
    state = db.load_state(game_id)
    if state is None:
        return error("Game not found", 404)

    body = read_json_object()
    if body is None or not player_name_is_valid(body):
        return error("Body must be a JSON object; player_name must be a string", 400)

    try:
        new_state = game_logic.finish_game(state)
    except game_logic.GameFinishedError:
        return error("Game is already finished", 409)

    db.finish_game_record(game_id, new_state, body.get("player_name"))
    return jsonify({"state": game_logic.public_state(new_state)})


@app.route("/api/leaderboard")
def leaderboard():
    return jsonify({"leaderboard": db.get_leaderboard(10)})


# ---------------------------------------------------------------------------
# JSON error pages (Flask's defaults are HTML, which the frontend can't parse)
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_exc):
    return error("Not found", 404)


@app.errorhandler(405)
def method_not_allowed(_exc):
    return error("Method not allowed", 405)


@app.errorhandler(500)
def server_error(_exc):
    # Do not leak internals (tracebacks, SQL) to the client.
    return error("Internal server error", 500)


if __name__ == "__main__":
    # Only used for local development (`python app.py`).
    # In production gunicorn imports `app` and this block never runs.
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)