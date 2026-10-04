"""HTTP layer only: creates the Flask app and defines routes.

Game rules will live in game_logic.py (no Flask imports there), and
database code in db.py. Keeping them separate makes each testable alone.
"""
from flask import Flask, jsonify

import config

# static_folder="static" is Flask's default, written out for clarity.
# static_url_path="" serves static files from the site root, so
# static/index.html is reachable at "/" via the route below.
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = config.SECRET_KEY


@app.route("/")
def index():
    # Serve the single-page frontend.
    return app.send_static_file("index.html")


@app.route("/health")
def health():
    # Used by Render (and by us) to check that the service is alive.
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Only used for local development (`python app.py`).
    # In production gunicorn imports `app` and this block never runs.
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
