"""All configuration lives here and is read from environment variables.

Why: secrets and deployment settings must never be hardcoded, and Render
sets them through its dashboard as environment variables.
"""
import os

# python-dotenv loads a local .env file into os.environ for development.
# On Render there is no .env file, so this call does nothing there.
from dotenv import load_dotenv

load_dotenv()

# Used by Flask to sign cookies/sessions. This app has no accounts, but we
# still read it from the environment so no secret is ever in the code.
# The default is for local development only; set a real value on Render.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

# Path of the SQLite file (used from step 3 onward).
# NOTE: on Render's free tier the disk is ephemeral, so this file (and the
# leaderboard in it) can be wiped whenever the service redeploys or restarts.
DB_PATH = os.environ.get("DB_PATH", "market_maker.db")

# Environment variables are always strings, so "false" would be truthy if we
# did not compare explicitly.
DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

# Render tells the app which port to bind to through PORT.
PORT = int(os.environ.get("PORT", "5000"))
