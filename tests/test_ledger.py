"""Pure cents math: splitting and debt simplification."""
from fractions import Fraction

import pytest

from app.ledger import Edge, SplitError, allocate, build_splits, net_balances, pairwise, simplify, to_cents


def test_100_three_ways_is_exact():
    parts = build_splits(10000, "equal", [1, 2, 3], payer_id=1)
    assert sum(c for _, c, _ in parts) == 10000
    assert dict((u, c) for u, c, _ in parts) == {1: 3334, 2: 3333, 3: 3333}  # payer absorbs the odd cent


def test_odd_cent_goes_to_payer_even_when_listed_last():
    parts = dict((u, c) for u, c, _ in build_splits(1000, "equal", [1, 2, 3], payer_id=3))
    assert parts == {1: 333, 2: 333, 3: 334}


@pytest.mark.parametrize("total,n", [(1, 3), (2, 3), (9999, 7), (100001, 6), (12345, 4)])
def test_equal_always_sums(total, n):
    parts = build_splits(total, "equal", list(range(1, n + 1)))
    cents = [c for _, c, _ in parts]
    assert sum(cents) == total and max(cents) - min(cents) <= 1


def test_exact_must_match_total():
    assert [c for _, c, _ in build_splits(5000, "exact", [1, 2], {1: 20, 2: 30})] == [2000, 3000]
    with pytest.raises(SplitError, match="short by \\$0.01"):
        build_splits(5000, "exact", [1, 2], {1: 20, 2: 29.99})
    with pytest.raises(SplitError, match="over"):
        build_splits(5000, "exact", [1, 2], {1: 20, 2: 31})


def test_percent_and_shares():
    parts = [c for _, c, _ in build_splits(10000, "percent", [1, 2, 3], {1: 33.33, 2: 33.33, 3: 33.34})]
    assert parts == [3333, 3333, 3334]
    with pytest.raises(SplitError, match="not 100%"):
        build_splits(10000, "percent", [1, 2], {1: 50, 2: 40})
    parts = [c for _, c, _ in build_splits(10000, "shares", [1, 2, 3], {1: 1, 2: 1, 3: 1})]
    assert sum(parts) == 10000
    assert [c for _, c, _ in build_splits(9000, "shares", [1, 2], {1: 2, 2: 1})] == [6000, 3000]


def test_shares_odd_cent_goes_to_payer():
    parts = dict((u, c) for u, c, _ in build_splits(10000, "shares", [1, 3, 4], {1: 1, 3: 1, 4: 1}, payer_id=3))
    assert parts == {1: 3333, 3: 3334, 4: 3333}


def test_rejects_bad_input():
    with pytest.raises(SplitError):
        build_splits(0, "equal", [1])
    with pytest.raises(SplitError):
        build_splits(-500, "equal", [1])
    with pytest.raises(SplitError):
        build_splits(500, "equal", [])
    with pytest.raises(SplitError):
        build_splits(500, "weird", [1])
    with pytest.raises(SplitError):
        build_splits(500, "shares", [1, 2], {1: 0, 2: 0})


def test_allocate_sums():
    assert sum(allocate(101, [(1, Fraction(1)), (2, Fraction(1))]).values()) == 101


def test_to_cents_rounds_half_up():
    assert to_cents(0.105) == 11 and to_cents(33.333) == 3333 and to_cents("19.99") == 1999


def test_chain_simplifies_to_one_payment():
    # A owes B $10, B owes C $10  =>  A pays C $10
    edges = [Edge(1, 2, 1000), Edge(2, 3, 1000)]
    net = net_balances(edges)
    assert net == {1: -1000, 2: 0, 3: 1000}
    assert simplify(net) == [{"from_user_id": 1, "to_user_id": 3, "amount_cents": 1000}]
    raw = pairwise(edges)
    assert {(r["from_user_id"], r["to_user_id"], r["amount_cents"]) for r in raw} == {(1, 2, 1000), (2, 3, 1000)}


def test_simplify_settles_everything_with_at_most_n_minus_1_payments():
    net = {1: 5000, 2: -1234, 3: -2766, 4: 1, 5: -1001}
    plan = simplify(net)
    left = dict(net)
    for p in plan:
        left[p["from_user_id"]] += p["amount_cents"]
        left[p["to_user_id"]] -= p["amount_cents"]
    assert all(v == 0 for v in left.values())
    assert len(plan) <= len(net) - 1


def test_pairwise_nets_within_pair_and_keeps_sources():
    rows = pairwise([Edge(1, 2, 3000, "Tokyo"), Edge(2, 1, 1000, "Standalone")])
    assert rows == [{"from_user_id": 1, "to_user_id": 2, "amount_cents": 2000,
                     "breakdown": [{"source": "Tokyo", "amount_cents": 3000},
                                   {"source": "Standalone", "amount_cents": -1000}]}]
