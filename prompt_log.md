# Prompt Log

## Tools used
- Claude (chat app): wrote the code. Because it cannot access my files, I copy its output into files and run everything myself.

## Prompt 1: project spec and working rules (verbatim)

You are my coding assistant for a university web-app project. I am a CS student on macOS (zsh). You are a chat window and cannot see or run my files, so I will copy your output into files by hand, run the code myself, and paste back any errors. I must be able to explain every part of the code in a technical interview without notes, so write simple, readable, well-structured code. No heavy abstractions, no unnecessary libraries.

# PROJECT: "Market Maker", an interactive market-making game

The player is a market maker. Each game has a hidden true value V of an asset. Each round the player posts a bid and an ask; one random trader arrives and buys at the ask, sells at the bid, or does nothing. The player manages cash and inventory over 20 rounds. At the end, inventory is settled at V and final PnL is the score. The lesson is adverse selection: some traders are informed (know V), some are noise, and the player must infer information from order flow.

## Game rules (implement exactly; keep all parameters in one config section)

- V ~ Normal(mean=100, std=10), rounded to 2 decimals, generated server-side. The client must NEVER receive V until the game is finished (server-authoritative, so devtools can't cheat).
- 20 rounds per game. Each round the player submits bid and ask. Validate: both numeric, both > 0, bid < ask, within a sane range (e.g. 1 to 1000).
- One trader per round, trading 1 unit:
  - With probability 0.3 the trader is INFORMED: buys at the ask if V > ask; sells at the bid if V < bid; otherwise does nothing.
  - With probability 0.7 the trader is UNINFORMED: picks buy or sell with equal probability, then trades only if the quote is attractive enough. For a buy: trade if ask <= 100 + noise. For a sell: trade if bid >= 100 - noise. Noise ~ Normal(0, 5), drawn fresh per trader. Put this in ONE isolated function.
- Inventory cap: |inventory| <= 10. If a trade would exceed the cap, it does not happen.
- Player-visible state: round number, cash, inventory, history of rounds (bid, ask, action "buy"/"sell"/"none", trade price). "buy" means the trader bought from the player at the ask. The player never learns whether a trader was informed until the game ends.
- In-game mark-to-market uses the average of past trade prices (100 if no trades), NOT V.
- Final PnL = cash + inventory * V. The end-of-game summary reveals V, the informed/uninformed flag of every round, and a breakdown: total PnL from informed traders vs. from uninformed traders.

# REQUIRED ARCHITECTURE (graded by my course)

- **Backend:** Python 3 + Flask. Game logic lives in `game_logic.py` with NO Flask imports (pure functions, unit-testable). `app.py` only handles HTTP and validation.
- **Database:** SQLite via the built-in `sqlite3` module (no ORM). Store each game (id, full serialized state, status, final score, player name, created_at). Parameterized SQL only. DB path comes from an environment variable with a default. Used for game persistence and a leaderboard.
- **Frontend:** plain HTML/CSS/JS in `static/` (no React, no build step). Uses `fetch()` to call the JSON API. Charts via Chart.js loaded from a CDN: (a) bid/ask per round with trade markers, (b) PnL and inventory over time; after the game ends also overlay V.
- **API (suggested):**
  - `POST /api/games` creates a game; returns game_id and initial state (no V)
  - `POST /api/games/<id>/quote` body `{bid, ask}`; resolves one round; returns updated state and the round outcome
  - `GET /api/games/<id>` current state (no V unless finished)
  - `POST /api/games/<id>/finish` (also auto-finish after round 20); settles, reveals V, accepts optional player name
  - `GET /api/leaderboard` top 10 scores
  - `GET /health` returns `{"status": "ok"}`
- **Error handling:** backend returns JSON errors with correct status codes (400 invalid input, 404 unknown game, 409 game already finished). The UI shows friendly messages and must not crash on bad input, double-clicks, or a backend outage ("Server unavailable, please try again").
- **Responsive:** must work on a phone-sized screen (single column, large tap targets, no horizontal scroll).
- **Secrets/config:** the app needs no API keys. Still, read all config (DB path, SECRET_KEY, debug flag) from environment variables; provide `.env.example`; never hardcode secrets. Escape player names before rendering (prevent XSS).
- **Deployment (Render, free web service):** pinned `requirements.txt`, `gunicorn` as production server, a `Procfile`, app binds to the `PORT` env var. Add a code comment that SQLite on Render's free tier is ephemeral (leaderboard can reset on redeploy). Do NOT implement Postgres.

# PARTS I WILL MODIFY MYSELF

Implement working defaults, but isolate each in its own small, clearly named function (or block) marked with a `# TODO(student): ...` comment:
1. The uninformed-trader decision function.
2. The end-of-game scoring/breakdown function.
3. The CSS theme variables (colors, fonts), in one block at the top of `style.css`.

# MY REPO (already created and cloned)

The folder `market-maker/` already contains a placeholder `README.md` and a Python `.gitignore` from GitHub. Do NOT write or touch `README.md` (I write it myself). Do NOT write the prompt log. For `.gitignore`, only give me the lines to ADD (e.g. `.env`, `*.db`, `venv/`), not a replacement file.

Target structure:market-maker/
app.py game_logic.py db.py config.py
static/index.html static/style.css static/app.js
tests/test_game_logic.py
requirements.txt Procfile .env.example
ARCHITECTURE_NOTES.md (step 8 only)

# HOW TO WORK WITH ME (strict output rules)

1. Work in these steps, ONE step per reply, then stop and wait for me:
   1. Skeleton: Flask app, `/health`, a minimal `static/index.html`, `requirements.txt`, `Procfile`, `.env.example`, `.gitignore` additions. Must be deployable on Render immediately.
   2. `game_logic.py` + pytest tests for every rule above.
   3. `db.py` (SQLite layer).
   4. API routes in `app.py`.
   5. Frontend game UI (`index.html`, `style.css`, `app.js`).
   6. Charts.
   7. Leaderboard and polish (end-of-game summary, error states, mobile layout).
   8. `ARCHITECTURE_NOTES.md`: AI-generated technical documentation containing (a) file structure with one line per file, (b) API endpoints with example requests/responses, (c) step-by-step local run and test instructions, (d) how config and environment variables are handled, (e) a short explanation of the game logic and adverse selection. I will paste it at the bottom of my README under a heading that labels it AI-generated.
2. For EVERY file you create or change, output the COMPLETE file content in its own code block, with the exact file path as a heading directly above it (e.g. `static/app.js`). Never output partial snippets, diffs, or placeholders like "...rest unchanged".
3. After the files, give me: (a) a 3-to-6 line summary of what each new file or function is responsible for, (b) the exact macOS terminal commands to set up (create a venv, install requirements), run, and test this step, including a `curl` example for each new endpoint, and (c) what I should see if it works.
4. Add concise comments explaining WHY, not just what. Keep functions short.
5. Do not add features beyond this spec (no accounts, websockets, or multiplayer). If something in the spec is ambiguous or seems wrong, ask me BEFORE changing it.
6. If you are unsure about something, say so explicitly instead of guessing confidently.
7. When I paste an error, I will include the full traceback and the file involved. Diagnose the root cause, explain it briefly, and return the full corrected file(s).

Start with step 1 only.

## Step 2: game logic and tests

### Prompt 2 (verbatim)
Step 1 works. I created all the files, ran it locally (curl /health returned 200 and the homepage loads), pushed to GitHub, and deployed it on Render successfully. One note: on my Mac port 5000 is taken by AirPlay, so I set PORT=5001 in my local .env. No code change was needed.

Now do step 2 only: game_logic.py plus pytest tests. Follow all the output rules from my first message (full file contents with the path as a heading, summary of what each file/function does, exact macOS commands, expected output, comments that explain WHY).

Requirements for game_logic.py:
- Pure Python, no Flask or database imports.
- All parameters in one config section at the top (true value mean/std, number of rounds, informed probability, noise std, inventory cap, trade size, quote bounds).
- Randomness must be injectable so tests are deterministic: every function that uses randomness takes a `random.Random` instance as an argument (do not call the global random module inside the logic).
- Game state is a plain dict (or a simple dataclass with to_dict/from_dict) that can be serialized to JSON, because step 3 will store it in SQLite. Include: true_value, current_round, cash, inventory, rounds_history, finished flag.
- Functions to include: create_game(rng), validate_quote(bid, ask), resolve_round(state, bid, ask, rng) which advances the game by one round and returns the updated state plus the round outcome, public_state(state) which returns the player-visible view and must NEVER include true_value or the informed flag while the game is unfinished, and finish_game(state) which settles inventory at V.
- Isolate these two as separate small functions marked `# TODO(student): ...` with working defaults: (1) the uninformed-trader decision function, (2) the end-of-game scoring/breakdown function (final PnL, plus PnL attributable to informed vs. uninformed traders).
- Inventory cap and edge cases: a trade that would exceed |inventory| = 10 does not happen; a finished game rejects further quotes; bid >= ask, non-numeric, non-positive, or out-of-range quotes are rejected with a clear error.

Requirements for tests/test_game_logic.py (pytest):
- Cover every rule: V is not exposed by public_state during the game and is exposed after finishing; informed trader buys when V > ask, sells when V < bid, does nothing otherwise; uninformed trader behavior; inventory cap; cash and inventory accounting after buy and sell; final PnL = cash + inventory * V; the informed/uninformed breakdown sums to the total PnL; quote validation; game ends after 20 rounds; a finished game rejects more quotes.
- Use a seeded random.Random so tests are reproducible.

Also tell me what to add to requirements.txt (pytest), and the exact command to run the tests from the market-maker folder with my venv active. Do not touch app.py yet. Do not write README.md or the prompt log. Stop after step 2 and wait for me.

### What I did
- Copied game_logic.py and tests/test_game_logic.py into the repo, added pytest to requirements.txt, and ran pytest.

### One place AI got it wrong
Two of Claude's tests, test_uninformed_always_buys_when_ask_is_very_cheap and test_uninformed_always_sells_when_bid_is_very_high, asserted that the uninformed trader only ever buys (or only ever sells). That contradicts the rule it implemented: the trader first picks buy or sell with 50% probability, then trades only if the quote is attractive, so the opposite side shows up as "none". I read the failure output ({'none', 'sell'} != {'sell'}), figured out why, and rewrote the assertions myself to check that the wrong action never happens and the right action does happen.

## Steps 3 and 4: database layer and API routes

### Prompt 3 (verbatim)
PASTE_STEP_3_4_PROMPT_HERE

### Prompt 4 (verbatim)
PASTE_THE_DECISIONS_PROMPT_HERE

### What I did
- Pasted db.py, app.py and the two new test files, ran pytest (160 passed).
- Claude's first reply listed gaps in my spec. I decided two things myself: keep the name saved at game creation, and only count games played through all 20 rounds on the leaderboard, because a game finished after 0 rounds scores 0 and would beat every player with a negative PnL.

### Where I made a mistake
I pasted a terminal command (open -e tests/test_db.py) into tests/test_db.py instead of Claude's Python code. pytest failed with a SyntaxError on line 1. I used head -3 on the four files to find which one was wrong, then pasted the correct code.
