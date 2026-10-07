## Architecture Notes (AI-generated)

### 1. File structure

| File | Responsibility |
|---|---|
| `app.py` | Flask app. HTTP layer only: routes, JSON parsing, error responses. Each route loads the state, calls a pure `game_logic` function, saves the state, and responds. Calls `db.init_db()` at import time so it also works under gunicorn. |
| `game_logic.py` | Pure game rules with no Flask or database imports: parameters, creating a game, validating a quote, resolving one round, the trader behaviours, scoring, and the player-visible view (`public_state`). Randomness is injected (`random.Random`), so tests are deterministic. |
| `db.py` | SQLite layer using the built-in `sqlite3` module, parameterized SQL only, one short-lived connection per call. Functions: `init_db`, `create_game_record`, `load_state`, `save_state`, `finish_game_record`, `get_leaderboard`. |
| `config.py` | Reads configuration (`SECRET_KEY`, `DB_PATH`, `FLASK_DEBUG`, `PORT`) from environment variables, loading a local `.env` file first for development. |
| `static/index.html` | All page sections (start, game, end, charts, history, leaderboard), hidden by default. Loads Chart.js from a CDN and `app.js`. |
| `static/style.css` | Layout and styling, mobile first. Colors and fonts (black and red theme) are CSS variables in one block at the top; a `negative` class shows losing PnL in red. |
| `static/app.js` | Frontend logic in plain JavaScript: one `fetch` wrapper, screen switching, tables, Chart.js charts, error messages, resuming a game after a refresh via `localStorage`. |
| `tests/test_game_logic.py` | pytest tests for every rule in `game_logic.py`. |
| `tests/test_db.py` | pytest tests for `db.py`, using a temporary database (`tmp_path`). |
| `tests/test_api.py` | pytest tests for the HTTP API, using Flask's test client. |
| `requirements.txt` | Pinned Python dependencies (Flask, gunicorn, python-dotenv, pytest). |
| `Procfile` | Tells Render to start the app with gunicorn. |
| `.env.example` | Template listing every environment variable the app reads. |
| `README.md`, `prompt_log.md` | Written by the student (project overview and AI prompt log). |

The request flow is always the same: **load state (db.py) → call a pure function (game_logic.py) → save state (db.py) → respond (app.py)**.

### 2. API endpoints

All endpoints return JSON, including errors, which always have the form `{"error": "message"}`.
Every response that contains game state is built with `game_logic.public_state()`, the single function that decides what the player may see. The true value `V` and each trader's informed flag are therefore **never** sent while a game is running.

| Status | Meaning |
|---|---|
| 200 | Success |
| 201 | Game created |
| 400 | Invalid input (body is not a JSON object, missing `bid`/`ask`, invalid quote, `player_name` not a string) |
| 404 | Unknown game id (`"Game not found"`) or unknown URL (`"Not found"`) |
| 405 | Wrong HTTP method (`"Method not allowed"`) |
| 409 | Game already finished (`"Game is already finished"`) |
| 500 | Unexpected server error (`"Internal server error"`; no internals are leaked) |

#### `GET /health`

```bash
curl http://localhost:5001/health
```
```json
{"status": "ok"}
```

#### `POST /api/games`: create a game

Optional body `player_name` (must be a string). The name is trimmed to 20 characters; a blank name becomes `"Anonymous"`. Game ids are random UUIDs (uuid4). Status `201`.

```bash
curl -X POST http://localhost:5001/api/games \
  -H "Content-Type: application/json" \
  -d '{"player_name": "Alice"}'
```
```json
{
  "game_id": "<game_id>",
  "state": {
    "current_round": 0,
    "total_rounds": 20,
    "cash": 0.0,
    "inventory": 0,
    "mark_price": 100.0,
    "mark_to_market_pnl": 0.0,
    "finished": false,
    "rounds_history": []
  }
}
```

Error `400`: `{"error": "Body must be a JSON object; player_name must be a string"}`.

`current_round` counts **completed** rounds (0 at the start), so the UI shows "Round `current_round + 1` of `total_rounds`".

#### `POST /api/games/<id>/quote`: play one round

Body: `bid` and `ask`, both JSON **numbers** (strings such as `"99"` and booleans are rejected). After the 20th round the server finishes the game automatically, records the final score, and returns the final state.

```bash
curl -X POST http://localhost:5001/api/games/<game_id>/quote \
  -H "Content-Type: application/json" \
  -d '{"bid": 99, "ask": 101}'
```
```json
{
  "outcome": {"round": 1, "bid": 99.0, "ask": 101.0, "action": "buy", "price": 101.0},
  "state": {
    "current_round": 1,
    "total_rounds": 20,
    "cash": 101.0,
    "inventory": -1,
    "mark_price": 101.0,
    "mark_to_market_pnl": 0.0,
    "finished": false,
    "rounds_history": [
      {"round": 1, "bid": 99.0, "ask": 101.0, "action": "buy", "price": 101.0}
    ]
  }
}
```

`action` is `"buy"` (a trader bought from you at your ask), `"sell"` (a trader sold to you at your bid) or `"none"` (`price` is then `null`). The `outcome` never contains the informed flag.

Errors:

- `404` `{"error": "Game not found"}`
- `400` `{"error": "Body must be a JSON object with bid and ask"}`
- `400` with one of the quote-validation messages (bid and ask are rounded to 2 decimals first, and `bid`/`ask` below stands for the field that failed):
  - `"bid must be a number"` / `"ask must be a number"`
  - `"bid must be a finite number"` (NaN or infinity)
  - `"bid must be greater than 0"`
  - `"bid must be between 1 and 1000"`
  - `"bid must be lower than ask"`
- `409` `{"error": "Game is already finished"}` (checked before the quote is validated)

#### `GET /api/games/<id>`: current state

```bash
curl http://localhost:5001/api/games/<game_id>
```

Returns `{"state": {...}}` in the same shape as above. Error: `404`.

#### `POST /api/games/<id>/finish`: end the game and reveal V

Optional body `player_name`; if given (and not blank), it replaces the name stored when the game was created. Finishing a game that is already finished returns `409`.

```bash
curl -X POST http://localhost:5001/api/games/<game_id>/finish \
  -H "Content-Type: application/json" \
  -d '{}'
```

Example response for a game ended after one round:

```json
{
  "state": {
    "current_round": 1,
    "total_rounds": 20,
    "cash": 101.0,
    "inventory": -1,
    "mark_price": 101.0,
    "mark_to_market_pnl": 0.0,
    "finished": true,
    "true_value": 103.27,
    "result": {"final_pnl": -2.27, "informed_pnl": -2.27, "uninformed_pnl": 0.0},
    "rounds_history": [
      {"round": 1, "bid": 99.0, "ask": 101.0, "action": "buy", "price": 101.0, "trader_informed": true}
    ]
  }
}
```

Once a game is finished, the same reveal (`true_value`, `result`, and `trader_informed` on every round) is also returned by `GET /api/games/<id>` and by the last `/quote`. The player always gets the final score back, but a game finished before round 20 is **not ranked**. Errors: `404`, `400` (body not a JSON object or `player_name` not a string), `409`.

#### `GET /api/leaderboard`: top 10 ranked games

Only games played through all 20 rounds (status `completed`) are listed. Early-finished games are excluded on purpose: a game ended after 0 rounds scores exactly 0, which would beat every player who finished with a negative PnL. Scores are sorted highest first; on equal scores the earlier game ranks higher. `created_at` is an ISO 8601 UTC timestamp. Only these three columns are selected, so the stored state (which contains `V`) cannot leak through the leaderboard.

```bash
curl http://localhost:5001/api/leaderboard
```
```json
{
  "leaderboard": [
    {"player_name": "Alice", "final_score": 12.34, "created_at": "2026-10-07T12:00:00+00:00"}
  ]
}
```

### 3. Local setup and tests (macOS, zsh)

```bash
# 1. Clone and enter the project
git clone https://github.com/david555787/market-maker.git
cd market-maker

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your local config
cp .env.example .env
# macOS uses port 5000 for AirPlay Receiver, so open .env and change PORT=5000 to PORT=5001

# 5. Run the app (config.py loads .env automatically)
python app.py
```

Open http://localhost:5001 and check that http://localhost:5001/health returns `{"status": "ok"}`.

Run the tests (venv activated, from the `market-maker` folder):

```bash
python -m pytest -v
```

The tests need no running server: the database tests use a temporary file, the API tests use Flask's test client, and the game logic tests use a seeded random generator.

### 4. Configuration and environment variables

- All configuration is read from environment variables in `config.py`. Nothing secret is hardcoded, and the app needs no API keys.
- For local development, `config.py` calls `load_dotenv()` (from the `python-dotenv` package), which copies the values from a `.env` file into the environment. On Render there is no `.env` file, so the values come from the service's Environment tab instead.
- `.env.example` is committed as a template. The real `.env` file is listed in `.gitignore` and is never committed.

| Variable | Purpose | Default in `config.py` |
|---|---|---|
| `PORT` | Port the app binds to. Render sets it automatically; locally use `5001` on macOS. | `5000` |
| `DB_PATH` | Path of the SQLite file | `market_maker.db` |
| `SECRET_KEY` | Flask secret key (the app has no accounts, but the key is still read from the environment); set a long random value in production | `dev-only-change-me` |
| `FLASK_DEBUG` | `"true"` turns on debug mode; any other value means off (environment variables are strings, so the code compares explicitly). Keep it off in production. | `false` |

- **`DB_PATH` is read at call time.** `db.py` reads `config.DB_PATH` every time it opens a connection, so tests can point it at a temporary file.
- **Game parameters are not environment variables.** They are constants in one config section at the top of `game_logic.py` (see section 5), so every game follows the same rules.
- **Frontend copies.** The API does not send the inventory cap, trade size and default mark price, so `app.js` repeats them as three named constants (`INVENTORY_CAP`, `TRADE_SIZE`, `DEFAULT_MARK_PRICE`). If they change in `game_logic.py`, they must be changed in `app.js` too.
- **Production.** `app.py` only runs its `app.run(...)` block for local development. On Render, gunicorn (started by the `Procfile`) imports `app` directly, and `db.init_db()` runs at import time, so the table is created in both cases.
- **Ephemeral database.** SQLite on Render's free tier uses an ephemeral disk, so the database (and the leaderboard) can reset on every redeploy or restart. This is accepted for this project; Postgres is deliberately not used.
- **Database design.** One `games` table: `id` (uuid4 text), `state_json` (the full serialized state including `true_value`), `status` (`active`, `completed` or `ended_early`), `final_score`, `player_name`, `created_at` (UTC). All SQL uses `?` placeholders, so user input is never pasted into a query. A finished game can never be overwritten, because `save_state` only updates rows whose status is `active`.
- **XSS.** Player names are put on the page with `textContent` (never `innerHTML`), so a name like `<b>x</b>` is displayed as plain text and cannot inject HTML or scripts.

### 5. Game logic and adverse selection

**Parameters** (the config section at the top of `game_logic.py`):

| Constant | Value | Meaning |
|---|---|---|
| `TRUE_VALUE_MEAN`, `TRUE_VALUE_STD` | 100.0, 10.0 | `V ~ Normal(100, 10)`, rounded to 2 decimals |
| `NUM_ROUNDS` | 20 | Rounds per game |
| `INFORMED_PROBABILITY` | 0.4 | Chance that the arriving trader knows `V` |
| `UNINFORMED_REFERENCE_PRICE` | 100.0 | The "100" in the uninformed trade rule |
| `NOISE_STD` | 5.0 | Std of the noise added to that reference price |
| `INVENTORY_CAP` | 10 | `\|inventory\|` may never exceed this |
| `TRADE_SIZE` | 1 | Units per trade |
| `MIN_QUOTE`, `MAX_QUOTE` | 1.0, 1000.0 | Allowed range for bid and ask |
| `DEFAULT_MARK_PRICE` | 100.0 | Mark price before any trade has happened |

**Setup.** `create_game` draws `V` on the server. The full state, including `V`, is stored as JSON in SQLite, but the browser only receives `V` after the game is finished, so it cannot be read from the developer tools during play. A game starts with 0 cash and 0 inventory.

**One round** (`resolve_round`). The player posts a bid (price at which they buy) and an ask (price at which they sell). The quote is validated, then one random trader arrives and trades 1 unit:

- **Informed trader, probability 0.4** (`informed_trader_action`). Knows `V`. Buys at the ask if `V > ask`, sells at the bid if `V < bid`, otherwise does nothing.
- **Uninformed trader, probability 0.6** (`uninformed_trader_action`). Picks buy or sell with equal probability, then draws fresh noise `~ Normal(0, 5)`. A buyer trades if `ask <= 100 + noise`; a seller trades if `bid >= 100 - noise`. Because the side is picked first, a trader who picked the unattractive side simply does nothing. This function is marked `TODO(student)` so the behaviour can be changed.
- **Inventory cap.** Applies to every trader. A trade that would push `|inventory|` above 10 does not happen and the round counts as `"none"`.

`buy` in the history means a trader bought from the player at the ask. `resolve_round` works on a deep copy of the state, so the original is never half-updated.

**What the player sees** (`public_state`, the only function the API uses to build responses). Round number, cash, inventory, the mark price, the mark-to-market PnL, and the history of (bid, ask, action, trade price). The player is never told whether a trader was informed until the game ends. The mark price is the average of all past trade prices (100 if there were no trades), not `V`. The frontend recomputes the same definition from the history to draw the charts.

**Settlement** (`finish_game`, `score_game`). The game ends automatically after round 20 or when the player ends it early. Final PnL = `cash + inventory * V`. The summary reveals `V`, the informed flag of every round, and the PnL split by trader type. `score_game` (marked `TODO(student)`) settles every trade on its own against `V`: `price - V` when a trader bought from the player, `V - price` when a trader sold to the player. Because the player starts with 0 cash and 0 inventory, these per-trade amounts add up exactly to `cash + inventory * V`, so the informed and uninformed parts always sum to the final PnL.

**Adverse selection.** An informed trader only trades when your quote is on the wrong side of `V`: they buy from you when your ask is below `V` and sell to you when your bid is above `V`. So against the true value, **every trade with an informed trader loses money for the player by construction**. An uninformed trader decides without knowing `V`, so those trades can earn you the spread. You cannot tell the two types apart while playing, but the order flow carries information: a run of buys at your ask suggests `V` is above it, and a run of sells at your bid suggests it is below. A good market maker therefore moves the quotes in the direction of the order flow, and widens the spread when informed traders are likely. With a higher informed probability (0.4 here), the spread needed to stay profitable is wider.