"""Dynamic elimination-threshold behavior.

The elimination threshold is the **minimum number of distinguishing words
between any two candidates** (capped at the default, floored at 1), shared by
all candidates. PICK lowers it so the *closest* candidate pair stays resolvable
— a pair separable by a single witness can still be decided (mirrors
pick-regex). These tests pin that on canonical shapes.
"""

from itertools import combinations

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.spotutils import areEquivalent, is_trace_satisfied
from pick_ltl.services.candidate_builder import (
    DEFAULT_ELIMINATION_THRESHOLD,
    _assign_dynamic_thresholds,
    _count_distinguishing_witnesses,
)
from pick_ltl.session.engine import classify_trace, next_pair
from pick_ltl.session.models import CandidateFormulaState, CandidateOrigin, SessionState


def _candidates(*formulas):
    cands = [
        CandidateFormulaState(formula=f, explanation="", origin=CandidateOrigin(kind="seed"))
        for f in formulas
    ]
    _assign_dynamic_thresholds(cands)
    return cands


def _expected_threshold(*formulas):
    counts = [
        _count_distinguishing_witnesses(a, b, limit=DEFAULT_ELIMINATION_THRESHOLD)
        for a, b in combinations(formulas, 2)
    ]
    counts = [c for c in counts if c >= 1]
    return max(1, min(counts)) if counts else DEFAULT_ELIMINATION_THRESHOLD


def _converges_to(formulas, target, max_steps=20):
    cands = _candidates(*formulas)
    session = SessionState(prompt="p", provider={}, candidate_states=cands, mode="voting")
    for _ in range(max_steps):
        session = next_pair(session)
        pair = session.current_pair
        if pair is None:
            break
        for trace in (pair.trace1, pair.trace2):
            label = "accept" if is_trace_satisfied(trace, target) else "reject"
            session = classify_trace(session, trace, label)
    final = session.final_result.formula if session.final_result else None
    return final is not None and areEquivalent(final, target)


# Exactly one trace separates these (subsumption: f1 => f2, f2 \ f1 is a singleton).
SINGLETON_PAIR = ("G a", "(G a) | (!a & X G a)")
# Two traces separate these (disjoint singleton languages; neither subsumes).
TWO_TRACE_PAIR = ("!a & X G a", "G a")


def test_threshold_equals_min_pairwise_distinguishing_count():
    """The defining property, checked against an independent recomputation."""
    for formulas in (SINGLETON_PAIR, TWO_TRACE_PAIR, ("G a", "(G a) | (!a & X G a)", "F b")):
        cands = _candidates(*formulas)
        expected = _expected_threshold(*formulas)
        assert all(c.elimination_threshold == expected for c in cands), formulas


def test_singleton_difference_counts_one_witness():
    assert _count_distinguishing_witnesses(*SINGLETON_PAIR, limit=2) == 1


def test_singleton_difference_drops_threshold_to_one():
    cands = _candidates(*SINGLETON_PAIR)
    assert all(c.elimination_threshold == 1 for c in cands)


def test_closest_pair_pulls_all_thresholds_down():
    """A single close pair lowers the threshold for EVERY candidate (global min),
    not just the two that are close."""
    formulas = ("G a", "(G a) | (!a & X G a)", "F b")  # first two differ by one word
    cands = _candidates(*formulas)
    assert all(c.elimination_threshold == 1 for c in cands), (
        [(c.formula, c.elimination_threshold) for c in cands]
    )


def test_well_separated_candidates_keep_default_threshold():
    formulas = ("G a", "G b", "G c")  # every pair separable by >= 2 words
    cands = _candidates(*formulas)
    assert _expected_threshold(*formulas) == DEFAULT_ELIMINATION_THRESHOLD
    assert all(c.elimination_threshold == DEFAULT_ELIMINATION_THRESHOLD for c in cands)


@pytest.mark.parametrize("target", SINGLETON_PAIR)
def test_singleton_difference_converges(target):
    assert _converges_to(SINGLETON_PAIR, target)


def test_two_trace_pair_counts_two_witnesses():
    assert _count_distinguishing_witnesses(*TWO_TRACE_PAIR, limit=2) == 2


@pytest.mark.parametrize("target", TWO_TRACE_PAIR)
def test_two_trace_pair_converges_at_default_threshold(target):
    assert _converges_to(TWO_TRACE_PAIR, target)
