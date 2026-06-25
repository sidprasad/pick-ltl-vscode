"""Distinguishing-trace behavior: no repeated, duplicate, or useless traces.

Drives the full build -> next_pair -> classify loop with a *consistent* oracle
(accept a trace iff a fixed target formula satisfies it) and asserts the
properties the engine must guarantee every step, plus convergence to the target.
"""

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.ltlnode import LTLNode
from pick_ltl.ltl.spotutils import is_trace_satisfied
from pick_ltl.services.candidate_builder import build_candidates
from pick_ltl.session.engine import classify_trace, next_pair
from pick_ltl.session.models import AtomSpec, SeedFormulaResult, SessionState


def seed(formula, atoms):
    return SeedFormulaResult(
        formula=formula,
        explanation="",
        atoms=[AtomSpec(name=a, meaning=a) for a in atoms],
        warnings=[],
    )


def _new_session(seeds):
    candidates = build_candidates(seeds)
    return SessionState(
        prompt="p", provider={}, seeds=seeds, seed=seeds[0],
        candidate_states=candidates, mode="voting",
    )


def _drive(target, seeds, max_steps=40):
    """Run the loop with a consistent oracle. Returns (session, seen_traces, issues)."""
    session = _new_session(seeds)
    seen = []
    issues = []
    for step in range(max_steps):
        session = next_pair(session)
        pair = session.current_pair
        if pair is None:
            break
        active = session.active_candidates()
        if pair.trace1 == pair.trace2:
            issues.append(f"duplicate trace within pair at step {step}")
        if set(pair.matches1) == set(pair.matches2):
            issues.append(f"non-distinguishing pair at step {step}")
        for trace in (pair.trace1, pair.trace2):
            if trace in seen:
                issues.append(f"repeated trace across session at step {step}: {trace}")
            seen.append(trace)
            label = "accept" if is_trace_satisfied(trace, target) else "reject"
            session = classify_trace(session, trace, label)
    return session, seen, issues


CASES = [
    ("G(r -> F(b))", [seed("G(r -> F(b))", ["r", "b"])]),
    ("G(r -> b)", [seed("G(r -> F(b))", ["r", "b"])]),
    ("F(g)", [seed("F(g)", ["g"]), seed("G(g)", ["g"])]),
    ("X(p)", [seed("X(p)", ["p"]), seed("F(p)", ["p"]), seed("G(p)", ["p"])]),
    ("G(a -> X(b))", [seed("G(a -> X(b))", ["a", "b"])]),
]


@pytest.mark.parametrize("target,seeds", CASES)
def test_no_duplicate_repeated_or_useless_traces(target, seeds):
    _session, _seen, issues = _drive(target, seeds)
    assert not issues, issues


@pytest.mark.parametrize("target,seeds", CASES)
def test_converges_to_target(target, seeds):
    session, _seen, _issues = _drive(target, seeds)
    final = session.final_result.formula if session.final_result else None
    assert final is not None, f"did not converge (mode={session.mode})"
    assert LTLNode.equiv(final, target), f"converged to {final!r}, expected {target!r}"


def test_next_pair_emits_distinct_traces_on_first_step():
    session = _new_session([seed("G(r -> F(b))", ["r", "b"])])
    session = next_pair(session)
    assert session.current_pair is not None
    assert session.current_pair.trace1 != session.current_pair.trace2


def test_lone_discriminator_is_paired_with_accepted_by_none():
    # F(a) is subsumed by... a trace can satisfy F(a) but not G(a), never the
    # reverse, so the {F(a), G(a)} pair has exactly ONE informative split. The
    # selector should show that discriminator alongside a trace accepted by none.
    from pick_ltl.ltl.spotutils import generate_distinguishing_trace_pool
    from pick_ltl.session.engine import _is_informative, _select_distinguishing_pair, _trace_signature
    from pick_ltl.session.models import CandidateFormulaState, CandidateOrigin

    cands = [
        CandidateFormulaState(formula="F(a)", explanation="", origin=CandidateOrigin(kind="seed")),
        CandidateFormulaState(formula="G(a)", explanation="", origin=CandidateOrigin(kind="seed")),
    ]
    pool = generate_distinguishing_trace_pool([c.formula for c in cands])
    pair = _select_distinguishing_pair(pool, cands, set())
    assert pair is not None
    trace1, trace2 = pair
    assert trace1 != trace2
    sig1, sig2 = _trace_signature(trace1, cands), _trace_signature(trace2, cands)
    assert _is_informative(sig1) and not _is_informative(sig2)
    assert not any(sig2), "partner trace should be accepted by none of the candidates"


def test_exhaustion_is_clean_when_no_question_remains():
    # A single trivial candidate cannot be split further; the loop must end in a
    # terminal state, never by emitting a duplicate/degenerate pair.
    session = _new_session([seed("G(a)", ["a"])])
    for _ in range(10):
        session = next_pair(session)
        if session.current_pair is None:
            break
        pair = session.current_pair
        assert pair.trace1 != pair.trace2
        session = classify_trace(session, pair.trace1, "accept")
        session = classify_trace(session, pair.trace2, "reject")
    assert session.current_pair is None
