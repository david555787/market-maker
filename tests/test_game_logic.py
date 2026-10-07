"""Unit tests for game_logic.py. Run from the project root with:
    python -m pytest -v
"""
import json
import random

import pytest

from game_logic import (
    INFORMED_PROBABILITY,
    INVENTORY_CAP,
    NUM_ROUNDS,
    GameFinishedError,
    InvalidQuoteError,
    create_game,
    finish_game,
    informed_trader_action,
    mark_price,
    public_state,
    resolve_round,
    score_game,
    uninformed_trader_action,
    validate_quote,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class StubRng:
    """Fake random generator that returns fixed values.

    Some tests need to control EXACTLY who arrives and what noise they get
    (for example to test the boundary ask == 100 + noise). A seeded
    random.Random cannot give that precision, so we use this stub there.
    """

    def __init__(self, roll=0.99, side="buy", noise=0.0):
        self.roll = roll      # < 0.3 means "informed trader arrives"
        self.side = side      # the side an uninformed trader picks
        self.noise = noise    # the noise an uninformed trader draws

    def random(self):
        return self.roll

    def choice(self, options):
        return self.side

    def gauss(self, mu, sigma):
        return self.noise


def informed_rng():
    return StubRng(roll=0.0)


def uninformed_rng(side, noise):
    return StubRng(roll=0.99, side=side, noise=noise)


def make_state(true_value=100.0, inventory=0):
    """A fresh game with V and inventory set to known values."""
    state = create_game(random.Random(0))
    state["true_value"] = true_value
    state["inventory"] = inventory
    return state


def play_rounds(state, rng, n, bid=98, ask=102):
    """Play n rounds with the same quote and return the final state."""
    for _ in range(n):
        state, _outcome = resolve_round(state, bid, ask, rng)
    return state


# ---------------------------------------------------------------------------
# Creating a game
# ---------------------------------------------------------------------------
def test_create_game_initial_state():
    state = create_game(random.Random(1))
    assert state["current_round"] == 0
    assert state["cash"] == 0
    assert state["inventory"] == 0
    assert state["rounds_history"] == []
    assert state["finished"] is False
    assert round(state["true_value"], 2) == state["true_value"]


def test_same_seed_gives_same_game():
    a = create_game(random.Random(42))
    b = create_game(random.Random(42))
    assert a == b


def test_true_value_is_roughly_normal_100_10():
    rng = random.Random(7)
    values = [create_game(rng)["true_value"] for _ in range(2000)]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    assert 98 < mean < 102
    assert 9 < variance ** 0.5 < 11


# ---------------------------------------------------------------------------
# Quote validation
# ---------------------------------------------------------------------------
def test_valid_quote_is_accepted():
    assert validate_quote(99, 101) == (99.0, 101.0)


def test_quote_is_rounded_to_two_decimals():
    assert validate_quote(99.123, 101.456) == (99.12, 101.46)


def test_quote_that_rounds_to_equal_prices_is_rejected():
    with pytest.raises(InvalidQuoteError):
        validate_quote(100.001, 100.004)


@pytest.mark.parametrize("bid, ask, message", [
    ("abc", 101, "bid must be a number"),
    (99, "xyz", "ask must be a number"),
    (None, 101, "bid must be a number"),
    (True, 101, "bid must be a number"),
    (float("nan"), 101, "finite"),
    (0, 101, "greater than 0"),
    (-5, 101, "greater than 0"),
    (0.5, 101, "between"),
    (99, 1001, "between"),
    (101, 99, "lower than ask"),
    (100, 100, "lower than ask"),
])
def test_invalid_quotes_are_rejected_with_clear_message(bid, ask, message):
    with pytest.raises(InvalidQuoteError, match=message):
        validate_quote(bid, ask)


# ---------------------------------------------------------------------------
# Informed trader
# ---------------------------------------------------------------------------
def test_informed_buys_when_value_above_ask():
    assert informed_trader_action(105, 99, 101) == "buy"


def test_informed_sells_when_value_below_bid():
    assert informed_trader_action(95, 99, 101) == "sell"


def test_informed_does_nothing_inside_the_spread():
    assert informed_trader_action(100, 99, 101) == "none"


def test_informed_does_nothing_exactly_at_the_quotes():
    # The rules use strict inequalities (V > ask, V < bid).
    assert informed_trader_action(101, 99, 101) == "none"
    assert informed_trader_action(99, 99, 101) == "none"


# ---------------------------------------------------------------------------
# Uninformed trader
# ---------------------------------------------------------------------------
def test_uninformed_buy_threshold_is_ask_less_or_equal_100_plus_noise():
    rng = StubRng(side="buy", noise=2.0)   # threshold is 102
    assert uninformed_trader_action(90, 102.0, rng) == "buy"
    assert uninformed_trader_action(90, 102.01, rng) == "none"


def test_uninformed_sell_threshold_is_bid_at_least_100_minus_noise():
    rng = StubRng(side="sell", noise=2.0)  # threshold is 98
    assert uninformed_trader_action(98.0, 110, rng) == "sell"
    assert uninformed_trader_action(97.99, 110, rng) == "none"


def test_uninformed_negative_noise_makes_trader_pickier():
    rng = StubRng(side="buy", noise=-3.0)  # threshold is 97
    assert uninformed_trader_action(90, 97.0, rng) == "buy"
    assert uninformed_trader_action(90, 97.5, rng) == "none"


def test_uninformed_always_buys_when_ask_is_very_cheap():
    rng = random.Random(1)
    actions = {uninformed_trader_action(1, 2, rng) for _ in range(100)}
    assert "sell" not in actions   # a cheap ask never triggers a sell
    assert "buy" in actions        # but it does trigger buys


def test_uninformed_always_sells_when_bid_is_very_high():
    rng = random.Random(1)
    actions = {uninformed_trader_action(500, 501, rng) for _ in range(100)}
    assert "buy" not in actions    # a very high bid never triggers a buy
    assert "sell" in actions       # but it does trigger sells


def test_uninformed_never_trades_on_terrible_quotes():
    rng = random.Random(1)
    actions = {uninformed_trader_action(1, 1000, rng) for _ in range(100)}
    assert actions == {"none"}


def test_uninformed_picks_buy_and_sell_about_equally():
    rng = random.Random(3)
    # An artificial quote that BOTH sides always accept, so the action
    # shows which side the trader picked.
    actions = [uninformed_trader_action(500, 1, rng) for _ in range(200)]
    buys = actions.count("buy")
    assert 70 <= buys <= 130
    assert buys + actions.count("sell") == 200


# ---------------------------------------------------------------------------
# Mark price
# ---------------------------------------------------------------------------
def test_mark_price_defaults_to_100_without_trades():
    assert mark_price([]) == 100.0
    assert mark_price([{"price": None}]) == 100.0


def test_mark_price_is_average_of_trade_prices():
    history = [{"price": 101.0}, {"price": None}, {"price": 99.0}, {"price": 103.0}]
    assert mark_price(history) == pytest.approx(101.0)


# ---------------------------------------------------------------------------
# Resolving a round: cash and inventory accounting
# ---------------------------------------------------------------------------
def test_trader_buys_from_player_at_the_ask():
    state, outcome = resolve_round(make_state(), 99, 101, uninformed_rng("buy", 10.0))
    assert outcome["action"] == "buy"
    assert outcome["price"] == 101.0
    assert state["cash"] == 101.0
    assert state["inventory"] == -1


def test_trader_sells_to_player_at_the_bid():
    state, outcome = resolve_round(make_state(), 99, 101, uninformed_rng("sell", 10.0))
    assert outcome["action"] == "sell"
    assert outcome["price"] == 99.0
    assert state["cash"] == -99.0
    assert state["inventory"] == 1


def test_no_trade_leaves_cash_and_inventory_unchanged():
    # Buy side with noise -10 means the trader wants ask <= 90.
    state, outcome = resolve_round(make_state(), 99, 101, uninformed_rng("buy", -10.0))
    assert outcome["action"] == "none"
    assert outcome["price"] is None
    assert state["cash"] == 0
    assert state["inventory"] == 0


def test_informed_trader_buys_when_value_above_ask_in_a_round():
    state, outcome = resolve_round(make_state(true_value=110), 99, 101, informed_rng())
    assert outcome["action"] == "buy"
    assert state["rounds_history"][0]["trader_informed"] is True


def test_informed_trader_sells_when_value_below_bid_in_a_round():
    state, outcome = resolve_round(make_state(true_value=90), 99, 101, informed_rng())
    assert outcome["action"] == "sell"
    assert state["cash"] == -99.0
    assert state["inventory"] == 1


def test_informed_trader_does_nothing_inside_the_spread_in_a_round():
    state, outcome = resolve_round(make_state(true_value=100), 99, 101, informed_rng())
    assert outcome["action"] == "none"
    assert state["rounds_history"][0]["trader_informed"] is True


def test_resolve_round_does_not_modify_the_input_state():
    original = make_state()
    resolve_round(original, 99, 101, uninformed_rng("buy", 10.0))
    assert original["current_round"] == 0
    assert original["rounds_history"] == []
    assert original["cash"] == 0


def test_round_outcome_contains_no_informed_flag():
    _state, outcome = resolve_round(make_state(), 99, 101, uninformed_rng("buy", 10.0))
    assert set(outcome) == {"round", "bid", "ask", "action", "price"}


def test_round_counter_and_history_grow_each_round():
    state = play_rounds(make_state(), random.Random(5), 3)
    assert state["current_round"] == 3
    assert [r["round"] for r in state["rounds_history"]] == [1, 2, 3]


def test_invalid_quote_is_rejected_by_resolve_round():
    with pytest.raises(InvalidQuoteError):
        resolve_round(make_state(), 101, 99, random.Random(1))


# ---------------------------------------------------------------------------
# Inventory cap
# ---------------------------------------------------------------------------
def test_trade_that_would_push_inventory_above_cap_does_not_happen():
    state = make_state(inventory=INVENTORY_CAP)
    # Trader SELLS to us, which would make our inventory 11.
    state, outcome = resolve_round(state, 99, 101, uninformed_rng("sell", 10.0))
    assert outcome["action"] == "none"
    assert state["inventory"] == INVENTORY_CAP
    assert state["cash"] == 0


def test_trade_that_reduces_inventory_is_allowed_at_the_cap():
    state = make_state(inventory=INVENTORY_CAP)
    state, outcome = resolve_round(state, 99, 101, uninformed_rng("buy", 10.0))
    assert outcome["action"] == "buy"
    assert state["inventory"] == INVENTORY_CAP - 1


def test_trade_that_would_push_inventory_below_negative_cap_does_not_happen():
    state = make_state(inventory=-INVENTORY_CAP)
    state, outcome = resolve_round(state, 99, 101, uninformed_rng("buy", 10.0))
    assert outcome["action"] == "none"
    assert state["inventory"] == -INVENTORY_CAP


def test_trade_that_reduces_short_position_is_allowed_at_negative_cap():
    state = make_state(inventory=-INVENTORY_CAP)
    state, outcome = resolve_round(state, 99, 101, uninformed_rng("sell", 10.0))
    assert outcome["action"] == "sell"
    assert state["inventory"] == -INVENTORY_CAP + 1


def test_reaching_exactly_the_cap_is_allowed():
    state = make_state(inventory=INVENTORY_CAP - 1)
    state, outcome = resolve_round(state, 99, 101, uninformed_rng("sell", 10.0))
    assert outcome["action"] == "sell"
    assert state["inventory"] == INVENTORY_CAP


def test_cap_also_blocks_informed_traders():
    state = make_state(true_value=110, inventory=-INVENTORY_CAP)
    state, outcome = resolve_round(state, 99, 101, informed_rng())
    assert outcome["action"] == "none"
    assert state["inventory"] == -INVENTORY_CAP


# ---------------------------------------------------------------------------
# Game length and finishing
# ---------------------------------------------------------------------------
def test_game_ends_after_num_rounds():
    rng = random.Random(11)
    state = play_rounds(make_state(), rng, NUM_ROUNDS - 1)
    assert state["finished"] is False
    state, _outcome = resolve_round(state, 98, 102, rng)
    assert state["finished"] is True
    assert state["current_round"] == NUM_ROUNDS
    assert len(state["rounds_history"]) == NUM_ROUNDS
    assert state["result"] is not None


def test_finished_game_rejects_further_quotes():
    rng = random.Random(11)
    state = play_rounds(make_state(), rng, NUM_ROUNDS)
    with pytest.raises(GameFinishedError):
        resolve_round(state, 98, 102, rng)


def test_game_can_be_finished_early_but_only_once():
    state = play_rounds(make_state(), random.Random(2), 3)
    state = finish_game(state)
    assert state["finished"] is True
    assert state["current_round"] == 3
    with pytest.raises(GameFinishedError):
        finish_game(state)


# ---------------------------------------------------------------------------
# What the player may see
# ---------------------------------------------------------------------------
def test_public_state_hides_secrets_during_the_game():
    state = play_rounds(make_state(), random.Random(4), 5)
    # Sanity check: the secrets really are in the private state.
    assert "trader_informed" in state["rounds_history"][0]

    view = public_state(state)
    assert "true_value" not in view
    assert "result" not in view
    assert "informed" not in json.dumps(view)
    assert view["finished"] is False
    assert view["current_round"] == 5
    assert len(view["rounds_history"]) == 5


def test_public_state_reveals_value_and_flags_after_finishing():
    state = finish_game(play_rounds(make_state(true_value=103.5), random.Random(4), 3))
    view = public_state(state)
    assert view["true_value"] == 103.5
    assert view["finished"] is True
    assert "final_pnl" in view["result"]
    assert all("trader_informed" in r for r in view["rounds_history"])


def test_public_state_mark_to_market_uses_trade_prices_not_value():
    # Player sold one unit at 101. Marked at the average trade price (101),
    # that position is worth exactly what it was sold for, so PnL is 0.
    state, _ = resolve_round(make_state(true_value=150), 99, 101, uninformed_rng("buy", 10.0))
    view = public_state(state)
    assert view["mark_price"] == 101.0
    assert view["mark_to_market_pnl"] == 0.0


# ---------------------------------------------------------------------------
# Final PnL and breakdown
# ---------------------------------------------------------------------------
def test_final_pnl_is_cash_plus_inventory_times_value():
    # Sold one unit at 101; it turns out to be worth 107.5: 101 - 107.5.
    state, _ = resolve_round(make_state(true_value=107.5), 99, 101, uninformed_rng("buy", 10.0))
    state = finish_game(state)
    assert state["result"]["final_pnl"] == pytest.approx(-6.5)
    assert state["result"]["uninformed_pnl"] == pytest.approx(-6.5)
    assert state["result"]["informed_pnl"] == 0


def test_informed_trader_costs_the_player_money():
    # Informed trader buys at 101 because V is 110: the player loses 9.
    state, _ = resolve_round(make_state(true_value=110), 99, 101, informed_rng())
    state = finish_game(state)
    assert state["result"]["final_pnl"] == pytest.approx(-9.0)
    assert state["result"]["informed_pnl"] == pytest.approx(-9.0)
    assert state["result"]["uninformed_pnl"] == 0


def test_breakdown_on_a_hand_built_game():
    state = {
        "true_value": 105.0,
        "cash": 104.0,        # +101 - 99 + 102
        "inventory": -1,      # -1 +1 -1
        "rounds_history": [
            {"action": "buy", "price": 101.0, "trader_informed": True},    # -4
            {"action": "sell", "price": 99.0, "trader_informed": False},   # +6
            {"action": "buy", "price": 102.0, "trader_informed": False},   # -3
            {"action": "none", "price": None, "trader_informed": True},
        ],
    }
    result = score_game(state)
    assert result["final_pnl"] == pytest.approx(-1.0)
    assert result["informed_pnl"] == pytest.approx(-4.0)
    assert result["uninformed_pnl"] == pytest.approx(3.0)


@pytest.mark.parametrize("seed", range(20))
def test_breakdown_sums_to_total_pnl(seed):
    rng = random.Random(seed)
    state = play_rounds(create_game(rng), rng, NUM_ROUNDS)
    result = state["result"]
    expected = state["cash"] + state["inventory"] * state["true_value"]
    assert result["final_pnl"] == pytest.approx(expected, abs=0.01)
    total = result["informed_pnl"] + result["uninformed_pnl"]
    assert total == pytest.approx(result["final_pnl"], abs=0.01)


# ---------------------------------------------------------------------------
# Other properties
# ---------------------------------------------------------------------------
def test_informed_share_matches_the_constant():
    rng = random.Random(123)
    flags = []
    for _ in range(50):
        state = play_rounds(create_game(rng), rng, NUM_ROUNDS)
        flags += [r["trader_informed"] for r in state["rounds_history"]]
    share = sum(flags) / len(flags)
    assert abs(share - INFORMED_PROBABILITY) < 0.08


def test_state_survives_a_json_round_trip():
    # Step 3 stores the state in SQLite as JSON, so this must work.
    rng = random.Random(9)
    state = play_rounds(make_state(), rng, 5)
    restored = json.loads(json.dumps(state))
    assert restored == state
    next_state, _outcome = resolve_round(restored, 98, 102, rng)
    assert next_state["current_round"] == 6