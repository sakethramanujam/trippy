"""Exact-cents money math for shared expenses.

Everything here works on integer cents. Floats only appear at the API edge
(`to_cents` on the way in, `cents / 100` on the way out).

A ledger is a list of edges: `Edge(debtor, creditor, cents, source)` means
"debtor owes creditor `cents`". Expense splits produce edges from each
participant to the payer; a recorded settlement (F paid T) produces the
reverse edge T -> F, which cancels the debt without deleting history.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Iterable, Optional

SPLIT_MODES = ("equal", "exact", "percent", "shares")


class SplitError(ValueError):
    """The requested split can't be built (bad mode, totals don't add up, ...)."""


def to_cents(amount) -> int:
    return int((Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100).to_integral_value())


def from_cents(cents: int) -> float:
    return float(Decimal(cents) / 100)


def allocate(total_cents: int, weights: list[tuple[int, Fraction]]) -> dict[int, int]:
    """Largest-remainder apportionment: the parts always sum to exactly `total_cents`.

    Leftover cents go to the largest fractional remainders; ties go to whoever is
    earlier in `weights`, so callers control who absorbs an odd cent.
    """
    total_w = sum(w for _, w in weights)
    if total_w <= 0:
        raise SplitError("Split weights must add up to more than zero")
    exact = [(uid, Fraction(total_cents) * w / total_w) for uid, w in weights]
    parts = {uid: int(q) for uid, q in exact}  # q >= 0, so int() floors
    leftover = total_cents - sum(parts.values())
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i][1] - int(exact[i][1])), i))
    for i in order[:leftover]:
        parts[exact[i][0]] += 1
    return parts


def build_splits(total_cents: int, mode: str, people: list[int], values: Optional[dict[int, float]] = None,
                 payer_id: Optional[int] = None) -> list[tuple[int, int, Optional[float]]]:
    """Return [(user_id, cents, share_value)] for an expense.

    - equal:   everyone in `people` pays the same; odd cents go to the payer first.
    - exact:   `values` are amounts per person and must add up to the total.
    - percent: `values` are percentages and must add up to 100.
    - shares:  `values` are relative weights (e.g. 2 nights vs 1 night).
    """
    if mode not in SPLIT_MODES:
        raise SplitError(f"split_mode must be one of {', '.join(SPLIT_MODES)}")
    if total_cents <= 0:
        raise SplitError("Amount must be greater than zero")
    seen: set[int] = set()
    people = [p for p in people if not (p in seen or seen.add(p))]
    if not people:
        raise SplitError("Pick at least one person to split with")
    values = values or {}

    if mode == "equal":
        ordered = sorted(people, key=lambda p: (p != payer_id,))  # stable: payer first, rest keep order
        parts = allocate(total_cents, [(p, Fraction(1)) for p in ordered])
        return [(p, parts[p], None) for p in people]

    missing = [p for p in people if p not in values]
    if missing:
        raise SplitError(f"Missing a value for users {missing}")
    if any(values[p] < 0 for p in people):
        raise SplitError("Split values can't be negative")

    if mode == "exact":
        parts = {p: to_cents(values[p]) for p in people}
        diff = total_cents - sum(parts.values())
        if diff != 0:
            word = "short" if diff > 0 else "over"
            raise SplitError(f"Exact amounts are {word} by ${abs(diff) / 100:.2f}")
        return [(p, parts[p], float(values[p])) for p in people]

    payer_first = sorted(people, key=lambda p: (p != payer_id,))
    weights = [(p, Fraction(str(values[p]))) for p in payer_first]
    if mode == "percent":
        total_pct = sum(w for _, w in weights)
        if abs(total_pct - 100) > Fraction(1, 1000):
            raise SplitError(f"Percentages add up to {float(total_pct):g}%, not 100%")
    parts = allocate(total_cents, weights)
    return [(p, parts[p], float(values[p])) for p in people]


@dataclass(frozen=True)
class Edge:
    debtor: int
    creditor: int
    cents: int
    source: str = ""


def net_balances(edges: Iterable[Edge]) -> dict[int, int]:
    """Positive = is owed money, negative = owes money. Always sums to zero."""
    net: dict[int, int] = defaultdict(int)
    for e in edges:
        if e.debtor == e.creditor or e.cents == 0:
            continue
        net[e.creditor] += e.cents
        net[e.debtor] -= e.cents
    return dict(net)


def pairwise(edges: Iterable[Edge]) -> list[dict]:
    """Raw who-owes-whom per pair (netted within the pair only), with a per-source breakdown."""
    by_pair: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in edges:
        if e.debtor == e.creditor or e.cents == 0:
            continue
        a, b = sorted((e.debtor, e.creditor))
        sign = 1 if e.debtor == a else -1  # + means a owes b
        by_pair[(a, b)][e.source] += sign * e.cents
    out = []
    for (a, b), sources in by_pair.items():
        total = sum(sources.values())
        if total == 0:
            continue
        debtor, creditor, sign = (a, b, 1) if total > 0 else (b, a, -1)
        breakdown = [{"source": s, "amount_cents": sign * c} for s, c in sources.items() if c != 0]
        out.append({"from_user_id": debtor, "to_user_id": creditor, "amount_cents": abs(total),
                    "breakdown": sorted(breakdown, key=lambda x: -x["amount_cents"])})
    return sorted(out, key=lambda x: (-x["amount_cents"], x["from_user_id"], x["to_user_id"]))


def simplify(net: dict[int, int]) -> list[dict]:
    """Minimal-ish payment plan: repeatedly match the largest creditor with the largest debtor.

    Integer cents, ties broken by user id so results are deterministic. Produces at
    most n-1 payments and settles every balance exactly.
    """
    if sum(net.values()) != 0:
        raise ValueError("Net balances must sum to zero")
    creditors = {u: c for u, c in net.items() if c > 0}
    debtors = {u: -c for u, c in net.items() if c < 0}
    payments = []
    while creditors and debtors:
        c = max(creditors, key=lambda u: (creditors[u], -u))
        d = max(debtors, key=lambda u: (debtors[u], -u))
        amt = min(creditors[c], debtors[d])
        payments.append({"from_user_id": d, "to_user_id": c, "amount_cents": amt})
        creditors[c] -= amt
        debtors[d] -= amt
        if creditors[c] == 0:
            del creditors[c]
        if debtors[d] == 0:
            del debtors[d]
    return payments
