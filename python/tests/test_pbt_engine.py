"""Property-based tests (Hypothesis) for the distinguishing-trace engine.

These stress the engine on randomly generated LTL formulas and assert the
invariants that must hold for *every* input, which is where robustness lives:

  Safety      — every emitted pair is two distinct, genuinely distinguishing
                traces, and no trace is ever shown twice in a session.
  Soundness   — a candidate equivalent to the oracle's ground truth is NEVER
                eliminated (it never contradicts a consistent oracle), and the
                engine never converges to a formula inequivalent to the truth.
  Termination — the build -> next_pair -> classify loop always ends.

Soundness is independent of the elimination threshold (the truth candidate
accrues zero contradictions whatever the threshold), so these properties catch
threshold/trace-selection bugs without needing convergence to always succeed.
"""

import pytest

pytest.importorskip("spot")
hypothesis = pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from itertools import combinations

from pick_ltl.ltl import spotutils
from pick_ltl.ltl.ltlnode import parse_ltl_string
from pick_ltl.ltl.spotutils import areEquivalent, is_trace_satisfied
from pick_ltl.services.candidate_builder import (
    DEFAULT_ELIMINATION_THRESHOLD,
    _assign_dynamic_thresholds,
    _count_distinguishing_witnesses,
    build_candidates,
)
from pick_ltl.session.engine import classify_trace, next_pair
from pick_ltl.session.models import (
    AtomSpec,
    CandidateFormulaState,
    CandidateOrigin,
    SeedFormulaResult,
    SessionState,
)

ATOMS = ["a", "b"]
STEP_CAP = 50

# A recursive strategy producing valid ASCII LTL strings over {a, b}.
_ltl = st.recursive(
    st.sampled_from(ATOMS),
    lambda children: st.one_of(
        st.builds(lambda op, x: f"{op}({x})", st.sampled_from(["G", "F", "X", "!"]), children),
        st.builds(
            lambda op, l, r: f"({l} {op} {r})",
            st.sampled_from(["U", "&", "|", "->"]),
            children,
            children,
        ),
    ),
    max_leaves=5,
)

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    # Deterministic example generation so CI can't flake on a random seed; the
    # invariants are exact, so a failure here is always a real bug to reproduce.
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


def _normalize_nontrivial(formula):
    """Parse + normalize; return None if invalid or trivially true/false."""
    try:
        normalized = str(parse_ltl_string(formula))
        if spotutils.is_trivial(normalized):
            return None
        return normalized
    except Exception:
        return None


def _dedupe_semantically(formulas):
    distinct = []
    for f in formulas:
        nf = _normalize_nontrivial(f)
        if nf is None:
            continue
        try:
            if any(areEquivalent(nf, g) for g in distinct):
                continue
        except Exception:
            continue
        distinct.append(nf)
    return distinct


def _drive_and_assert_invariants(candidates, truth):
    """Run the loop with a consistent oracle; assert safety/soundness/termination."""
    session = SessionState(prompt="p", provider={}, candidate_states=candidates, mode="voting")
    seen = set()
    steps = 0
    while steps < STEP_CAP:
        session = next_pair(session)
        pair = session.current_pair
        if pair is None:
            break
        steps += 1
        # Safety: distinct, distinguishing, never-repeated.
        assert pair.trace1 != pair.trace2, "pair showed the same trace twice"
        assert set(pair.matches1) != set(pair.matches2), "pair is not distinguishing"
        for trace in (pair.trace1, pair.trace2):
            assert trace not in seen, f"trace repeated across session: {trace!r}"
            seen.add(trace)
            label = "accept" if is_trace_satisfied(trace, truth) else "reject"
            session = classify_trace(session, trace, label)

    assert steps < STEP_CAP, "loop did not terminate within the step cap"

    # Soundness: the truth-equivalent candidate survives.
    truth_states = [c for c in session.candidate_states if areEquivalent(c.formula, truth)]
    assert truth_states, "truth candidate vanished from the pool"
    assert not any(c.eliminated for c in truth_states), "truth candidate was eliminated"

    # Never converge to the wrong formula.
    if session.final_result and session.final_result.formula:
        assert areEquivalent(session.final_result.formula, truth), (
            f"converged to {session.final_result.formula!r}, not equivalent to truth {truth!r}"
        )


@given(formulas=st.lists(_ltl, min_size=2, max_size=4), truth_pick=st.integers(min_value=0, max_value=99))
@PBT_SETTINGS
def test_pbt_engine_on_arbitrary_candidate_sets(formulas, truth_pick):
    """Engine invariants on diverse hand-built candidate pools (exercises the
    dynamic-threshold assignment + next_pair selection directly)."""
    distinct = _dedupe_semantically(formulas)
    assume(len(distinct) >= 2)
    candidates = [
        CandidateFormulaState(formula=f, explanation="", origin=CandidateOrigin(kind="seed"))
        for f in distinct
    ]
    _assign_dynamic_thresholds(candidates)
    for c in candidates:
        assert c.elimination_threshold >= 1
    truth = distinct[truth_pick % len(distinct)]
    _drive_and_assert_invariants(candidates, truth)


@given(seed=_ltl, truth_pick=st.integers(min_value=0, max_value=99))
@PBT_SETTINGS
def test_pbt_engine_through_build_candidates(seed, truth_pick):
    """Engine invariants on the *real* pipeline: a seed expanded by
    build_candidates (misconception/syntactic mutation + dedup + thresholds)."""
    normalized = _normalize_nontrivial(seed)
    assume(normalized is not None)
    seeds = [SeedFormulaResult(formula=normalized, explanation="", atoms=[AtomSpec(a, a) for a in ATOMS], warnings=[])]
    try:
        candidates = build_candidates(seeds)
    except Exception:
        assume(False)
    assume(len(candidates) >= 2)
    truth = candidates[truth_pick % len(candidates)].formula
    _drive_and_assert_invariants(candidates, truth)


@given(formulas=st.lists(_ltl, min_size=2, max_size=4))
@PBT_SETTINGS
def test_pbt_threshold_is_min_pairwise_distinguishing_words(formulas):
    """For any candidate pool, every candidate's threshold equals
    max(1, min over pairs of the capped distinguishing-word count)."""
    distinct = _dedupe_semantically(formulas)
    assume(len(distinct) >= 2)
    candidates = [
        CandidateFormulaState(formula=f, explanation="", origin=CandidateOrigin(kind="seed"))
        for f in distinct
    ]
    _assign_dynamic_thresholds(candidates)
    counts = [
        _count_distinguishing_witnesses(a, b, limit=DEFAULT_ELIMINATION_THRESHOLD)
        for a, b in combinations(distinct, 2)
    ]
    counts = [c for c in counts if c >= 1]
    expected = max(1, min(counts)) if counts else DEFAULT_ELIMINATION_THRESHOLD
    assert expected >= 1
    for c in candidates:
        assert c.elimination_threshold == expected


@given(f1=_ltl, f2=_ltl)
@PBT_SETTINGS
def test_pbt_distinguishing_words_are_distinct(f1, f2):
    """generate_two_distinguishing_words never returns a duplicated trace."""
    n1, n2 = _normalize_nontrivial(f1), _normalize_nontrivial(f2)
    assume(n1 is not None and n2 is not None)
    try:
        words = spotutils.generate_two_distinguishing_words([n1, n2])
    except Exception:
        assume(False)
    assert 1 <= len(words) <= 2
    assert len(set(words)) == len(words), f"duplicate trace in {words}"
    assert all(words), "empty trace returned"
