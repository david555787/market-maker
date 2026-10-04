"""Pure game logic for the market-making game.

No Flask and no database imports here: every function takes plain data in
and returns plain data out, so it can be unit-tested without a server.

Randomness is injected: every function that needs randomness receives a
random.Random instance. Tests pass a seeded (or fake) one, so results are
reproducible. We never call the global `random` module in this file.
"""
import copy
import math

# ---------------------------------------------------------------------------
# CONFIG: every tunable game parameter lives here
# ---------------------------------------------------------------------------
TRUE_VALUE_MEAN = 100.0           # V ~ Normal(mean, std)
TRUE_VALUE_STD = 10.0
NUM_ROUNDS = 20
INFORMED_PROBABILITY = 0.3        # chance that a trader knows V
UNINFORMED_REFERENCE_PRICE = 100.0  # the "100" in the uninformed trade rule
NOISE_STD = 5.0                   # std of the noise on that reference price
INVENTORY_CAP = 10                # |inventory| may never exceed this
TRADE_SIZE = 1                    # units per trade
MIN_QUOTE = 1.0                   # sane range for bid/ask
MAX_QUOTE = 1000.0
DEFAULT_MARK_PRICE = 100.0        # mark price before any trade has happened


# ---------------------------------------------------------------------------
# Errors: the API layer (step 4) will turn these into HTTP status codes
# ---------------------------------------------------------------------------
class InvalidQuoteError(ValueError):
    """The submitted bid/ask broke a rule (-> HTTP 400)."""


class GameFinishedError(Exception):
    """The game is already finished (-> HTTP 409)."""


# ---------------------------------------------------------------------------
# Creating a game
# ---------------------------------------------------------------------------
def create_game(rng):
    """Return a fresh game state. V is drawn here and stays server-side.

    Note: `current_round` counts COMPLETED rounds (0 at the start), so it
    always equals len(rounds_history). The UI can show "Round current_round+1".
    """
    true_value = round(rng.gauss(TRUE_VALUE_MEAN, TRUE_VALUE_STD), 2)
    return {
        "true_value": true_value,
        "current_round": 0,
        "cash": 0.0,            # start at 0 so cash is just net trading cash flow
        "inventory": 0,
        "rounds_history": [],
        "finished": False,
        "result": None,         # filled in by finish_game
    }


# ---------------------------------------------------------------------------
# Quote validation
# ---------------------------------------------------------------------------
def _check_price(name, value):
    """Validate one price and return it as a float rounded to 2 decimals."""
    # bool is a subclass of int in Python, so True would pass the number
    # check below unless we reject it explicitly (JSON can send true/false).
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidQuoteError(f"{name} must be a number")
    # NaN and infinity are floats too, but they break every comparison.
    if not math.isfinite(value):
        raise InvalidQuoteError(f"{name} must be a finite number")
    if value <= 0:
        raise InvalidQuoteError(f"{name} must be greater than 0")
    if value < MIN_QUOTE or value > MAX_QUOTE:
        raise InvalidQuoteError(
            f"{name} must be between {MIN_QUOTE:g} and {MAX_QUOTE:g}"
        )
    # Rounding keeps cash free of long float tails like 100.30000000000001.
    return round(float(value), 2)


def validate_quote(bid, ask):
    """Return (bid, ask) as clean floats, or raise InvalidQuoteError."""
    bid = _check_price("bid", bid)
    ask = _check_price("ask", ask)
    # Compare AFTER rounding, so 100.001 / 100.004 (both -> 100.0) is rejected.
    if bid >= ask:
        raise InvalidQuoteError("bid must be lower than ask")
    return bid, ask


# ---------------------------------------------------------------------------
# Trader behaviour
# ---------------------------------------------------------------------------
def informed_trader_action(true_value, bid, ask):
    """Informed trader: only trades when the quote is wrong versus V."""
    if true_value > ask:
        return "buy"    # asset is worth more than the ask: buy it cheap
    if true_value < bid:
        return "sell"   # asset is worth less than the bid: sell it dear
    return "none"       # quote is fair enough: no profit to be had


# TODO(student): change how uninformed traders decide. The default below
# follows the project spec: pick buy/sell at random, then trade only if the
# quote is attractive compared with 100 plus fresh noise.
def uninformed_trader_action(bid, ask, rng):
    """Return "buy", "sell" or "none". "buy" = the trader buys at the ask."""
    side = rng.choice(("buy", "sell"))
    # Fresh noise per trader, so different traders have different opinions.
    noise = rng.gauss(0, NOISE_STD)
    if side == "buy" and ask <= UNINFORMED_REFERENCE_PRICE + noise:
        return "buy"
    if side == "sell" and bid >= UNINFORMED_REFERENCE_PRICE - noise:
        return "sell"
    return "none"


# ---------------------------------------------------------------------------
# Small helpers for one round
# ---------------------------------------------------------------------------
def _would_exceed_cap(inventory, action):
    """True if this trade would push |inventory| above the cap."""
    # A trader BUYING means the player SELLS, so player inventory goes down.
    if action == "buy":
        new_inventory = inventory - TRADE_SIZE
    elif action == "sell":
        new_inventory = inventory + TRADE_SIZE
    else:
        return False
    return abs(new_inventory) > INVENTORY_CAP


def _trade_price(action, bid, ask):
    """Traders buy at our ask and sell at our bid."""
    if action == "buy":
        return ask
    if action == "sell":
        return bid
    return None


def _apply_trade(state, action, price):
    """Update cash and inventory. Only ever called on our private copy."""
    if action == "buy":       # trader buys from the player
        state["cash"] += price * TRADE_SIZE
        state["inventory"] -= TRADE_SIZE
    elif action == "sell":    # trader sells to the player
        state["cash"] -= price * TRADE_SIZE
        state["inventory"] += TRADE_SIZE
    state["cash"] = round(state["cash"], 2)


def mark_price(rounds_history):
    """Average of all past trade prices (DEFAULT_MARK_PRICE if no trades).

    The player must not see V, so the in-game value of inventory is
    estimated from prices they have actually traded at.
    """
    prices = [r["price"] for r in rounds_history if r["price"] is not None]
    if not prices:
        return DEFAULT_MARK_PRICE
    return sum(prices) / len(prices)


# ---------------------------------------------------------------------------
# Playing a round
# ---------------------------------------------------------------------------
def resolve_round(state, bid, ask, rng):
    """Play one round. Returns (new_state, outcome); `state` is not modified.

    We copy the state first so a caller never sees a half-updated game if
    something fails, and so tests can compare "before" and "after".
    """
    if state["finished"]:
        raise GameFinishedError("This game is already finished")
    bid, ask = validate_quote(bid, ask)

    new_state = copy.deepcopy(state)

    # Draw who arrives: informed with probability INFORMED_PROBABILITY.
    informed = rng.random() < INFORMED_PROBABILITY
    if informed:
        action = informed_trader_action(new_state["true_value"], bid, ask)
    else:
        action = uninformed_trader_action(bid, ask, rng)

    # The cap applies to every trader. A blocked trade simply does not happen.
    if _would_exceed_cap(new_state["inventory"], action):
        action = "none"

    price = _trade_price(action, bid, ask)
    _apply_trade(new_state, action, price)

    new_state["current_round"] += 1
    new_state["rounds_history"].append({
        "round": new_state["current_round"],
        "bid": bid,
        "ask": ask,
        "action": action,
        "price": price,
        "trader_informed": informed,   # private until the game is finished
    })

    # The outcome goes back to the player, so it must NOT contain the flag.
    outcome = {
        "round": new_state["current_round"],
        "bid": bid,
        "ask": ask,
        "action": action,
        "price": price,
    }

    if new_state["current_round"] >= NUM_ROUNDS:
        new_state = finish_game(new_state)
    return new_state, outcome


# ---------------------------------------------------------------------------
# Finishing and scoring
# ---------------------------------------------------------------------------
# TODO(student): change the scoring. The default computes final PnL and splits
# it by trader type. Every trade is "settled" against V on its own:
#   trader bought from us at p -> we sold at p, a unit now worth V: p - V
#   trader sold to us at p     -> we bought at p, a unit now worth V: V - p
# These per-trade amounts add up to exactly cash + inventory * V.
def score_game(state):
    """Return final PnL and the informed/uninformed breakdown."""
    v = state["true_value"]
    informed_pnl = 0.0
    uninformed_pnl = 0.0
    for r in state["rounds_history"]:
        if r["action"] == "buy":
            trade_pnl = (r["price"] - v) * TRADE_SIZE
        elif r["action"] == "sell":
            trade_pnl = (v - r["price"]) * TRADE_SIZE
        else:
            continue    # no trade, no PnL
        if r["trader_informed"]:
            informed_pnl += trade_pnl
        else:
            uninformed_pnl += trade_pnl

    final_pnl = state["cash"] + state["inventory"] * v
    return {
        "final_pnl": round(final_pnl, 2),
        "informed_pnl": round(informed_pnl, 2),
        "uninformed_pnl": round(uninformed_pnl, 2),
    }


def finish_game(state):
    """Settle inventory at V and mark the game finished. Returns a new state."""
    if state["finished"]:
        raise GameFinishedError("This game is already finished")
    new_state = copy.deepcopy(state)
    new_state["finished"] = True
    new_state["result"] = score_game(new_state)
    return new_state


# ---------------------------------------------------------------------------
# What the player is allowed to see
# ---------------------------------------------------------------------------
def _strip_private(round_record):
    """Remove the informed flag from one history entry."""
    return {k: v for k, v in round_record.items() if k != "trader_informed"}


def public_state(state):
    """Player-visible view. Hides V and informed flags until the game ends.

    This is the ONLY function the API should use to build responses. Keeping
    one gatekeeper means a leak can only happen in one place.
    """
    history = state["rounds_history"]
    mark = mark_price(history)
    view = {
        "current_round": state["current_round"],
        "total_rounds": NUM_ROUNDS,
        "cash": state["cash"],
        "inventory": state["inventory"],
        "mark_price": round(mark, 2),
        "mark_to_market_pnl": round(state["cash"] + state["inventory"] * mark, 2),
        "finished": state["finished"],
    }
    if state["finished"]:
        view["true_value"] = state["true_value"]
        view["result"] = copy.deepcopy(state["result"])
        view["rounds_history"] = copy.deepcopy(history)   # flags revealed
    else:
        view["rounds_history"] = [_strip_private(r) for r in history]
    return view