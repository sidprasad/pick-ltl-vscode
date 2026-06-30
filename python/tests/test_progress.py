"""No-progress safety valve.

SPOT can almost always produce *another* distinguishing pair, so a session can
keep asking forever without converging. The engine therefore tracks how many
completed pairs in a row failed to narrow the live candidate set (no
elimination), and after `max_pairs_without_progress` of them it stops and
surfaces the best match so far instead of looping. These tests pin that
behavior — both the pure counter/selection helpers and the end-to-end flow.
"""

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.spotutils import is_trace_satisfied
from pick_ltl.services.candidate_builder import _assign_dynamic_thresholds, create_initial_session
from pick_ltl.session.engine import (
    _note_pair_progress,
    _select_best_candidate,
    classify_trace,
    next_pair,
)
from pick_ltl.session.models import (
    DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS,
    CandidateFormulaState,
    CandidateOrigin,
    SeedFormulaResult,
    SessionState,
)


def _candidate(formula, *, positive=0, negative=0, eliminated=False):
    return CandidateFormulaState(
        formula=formula,
        explanation="",
        origin=CandidateOrigin(kind="seed"),
        positive_votes=positive,
        negative_votes=negative,
        eliminated=eliminated,
    )


def _session(*formulas, **kwargs):
    cands = [
        CandidateFormulaState(formula=f, explanation="", origin=CandidateOrigin(kind="seed"))
        for f in formulas
    ]
    _assign_dynamic_thresholds(cands)
    return SessionState(prompt="p", provider={}, candidate_states=cands, mode="voting", **kwargs)


# --------------------------------------------------------------------------- #
# Pure counter logic: _note_pair_progress                                     #
# --------------------------------------------------------------------------- #

def test_first_pair_seeds_baseline_without_counting():
    session = _session("G a", "G b")
    _note_pair_progress(session, 2)
    assert session.last_active_count == 2
    assert session.pairs_without_progress == 0


def test_counter_increments_when_active_set_unchanged():
    session = _session("G a", "G b", "G c")
    _note_pair_progress(session, 3)  # seed
    _note_pair_progress(session, 3)  # no change
    _note_pair_progress(session, 3)  # no change
    assert session.pairs_without_progress == 2


def test_counter_resets_when_a_candidate_is_eliminated():
    session = _session("G a", "G b", "G c")
    _note_pair_progress(session, 3)  # seed
    _note_pair_progress(session, 3)  # stall -> 1
    _note_pair_progress(session, 3)  # stall -> 2
    assert session.pairs_without_progress == 2
    _note_pair_progress(session, 2)  # one eliminated -> progress
    assert session.pairs_without_progress == 0
    assert session.last_active_count == 2


# --------------------------------------------------------------------------- #
# Pure selection logic: _select_best_candidate                                #
# --------------------------------------------------------------------------- #

def test_best_candidate_prefers_most_upvotes_then_fewest_downvotes():
    session = SessionState(
        candidate_states=[
            _candidate("G a", positive=2, negative=1),
            _candidate("G b", positive=2, negative=0),  # same upvotes, fewer downvotes
            _candidate("G c", positive=1, negative=0),
        ]
    )
    assert _select_best_candidate(session).formula == "G b"


def test_best_candidate_is_none_without_any_upvote():
    session = SessionState(
        candidate_states=[_candidate("G a", negative=1), _candidate("G b")]
    )
    assert _select_best_candidate(session) is None


def test_best_candidate_ignores_eliminated_while_any_survive():
    session = SessionState(
        candidate_states=[
            _candidate("G a", positive=5, eliminated=True),  # most upvotes but dead
            _candidate("G b", positive=1),
        ]
    )
    assert _select_best_candidate(session).formula == "G b"


def test_best_candidate_falls_back_to_pool_when_all_eliminated():
    session = SessionState(
        candidate_states=[
            _candidate("G a", positive=5, eliminated=True),
            _candidate("G b", positive=2, eliminated=True),
        ]
    )
    # Defensive fallback: if everything is eliminated we still surface the most
    # confirmed one rather than nothing.
    assert _select_best_candidate(session).formula == "G a"


# --------------------------------------------------------------------------- #
# End-to-end: next_pair stops after enough no-progress pairs                   #
# --------------------------------------------------------------------------- #

def _accept_one_then_stall(session, target, stalls):
    """Give the session one confirming upvote for `target`, then answer every
    subsequent pair 'unsure' (which never changes votes -> guaranteed no
    progress). Returns the session after `stalls`+ no-progress next_pair calls."""
    session = next_pair(session)
    pair = session.current_pair
    for trace in (pair.trace1, pair.trace2):
        label = "accept" if is_trace_satisfied(trace, target) else "unsure"
        session = classify_trace(session, trace, label)
    for _ in range(stalls + 2):
        session = next_pair(session)
        if session.mode != "voting" or session.current_pair is None:
            break
        for trace in (session.current_pair.trace1, session.current_pair.trace2):
            session = classify_trace(session, trace, "unsure")
    return session


def test_stall_finalizes_to_best_confirmed_candidate():
    session = _session("G a", "G b", "G c", max_pairs_without_progress=3)
    session = _accept_one_then_stall(session, "G a", stalls=3)
    assert session.mode == "final_result"
    assert session.final_result is not None
    assert session.final_result.formula == "G a"  # the only upvoted candidate
    assert session.final_result.title == "Best match so far"
    assert "stopped narrowing" in session.final_result.message


def test_stall_threshold_is_settable():
    session = _session("G a", "G b", "G c", max_pairs_without_progress=1)
    session = _accept_one_then_stall(session, "G a", stalls=1)
    assert session.mode == "final_result"
    assert session.final_result.formula == "G a"


def test_stall_without_any_upvote_surfaces_standstill_not_a_formula():
    session = _session("G a", "G b", "G c", max_pairs_without_progress=2)
    # Never accept anything: answer every pair 'unsure'.
    for _ in range(6):
        session = next_pair(session)
        if session.mode != "voting" or session.current_pair is None:
            break
        for trace in (session.current_pair.trace1, session.current_pair.trace2):
            session = classify_trace(session, trace, "unsure")
    assert session.exhausted is True
    assert session.current_pair is None
    assert session.final_result is None  # we won't crown an unconfirmed formula
    assert "no candidate has an accepted example" in session.message


def test_normal_convergence_does_not_trip_the_safety_valve():
    """A session answered consistently converges to the real answer via the
    ordinary path — it must not be short-circuited into 'Best match so far'."""
    target = "G a"
    session = _session("G a", "G b", max_pairs_without_progress=3)
    for _ in range(20):
        session = next_pair(session)
        if session.mode != "voting" or session.current_pair is None:
            break
        for trace in (session.current_pair.trace1, session.current_pair.trace2):
            label = "accept" if is_trace_satisfied(trace, target) else "reject"
            session = classify_trace(session, trace, label)
    assert session.final_result is not None
    assert session.final_result.title != "Best match so far"
    assert is_trace_satisfied  # sanity: spot present


# --------------------------------------------------------------------------- #
# Plumbing: settable threshold + serialization round-trip                      #
# --------------------------------------------------------------------------- #

def test_create_initial_session_defaults_and_override():
    seeds = [SeedFormulaResult(formula="G a", explanation="")]
    default = create_initial_session("p", {}, seeds)
    assert default.max_pairs_without_progress == DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS
    override = create_initial_session("p", {}, seeds, max_pairs_without_progress=7)
    assert override.max_pairs_without_progress == 7
    # Out-of-range values are clamped to a sane minimum.
    clamped = create_initial_session("p", {}, seeds, max_pairs_without_progress=0)
    assert clamped.max_pairs_without_progress == 1


def test_progress_fields_survive_serialization_round_trip():
    session = _session("G a", "G b")
    session.pairs_without_progress = 2
    session.max_pairs_without_progress = 5
    session.last_active_count = 2
    restored = SessionState.from_dict(session.to_dict())
    assert restored.pairs_without_progress == 2
    assert restored.max_pairs_without_progress == 5
    assert restored.last_active_count == 2


def test_legacy_session_without_progress_fields_gets_defaults():
    # A session JSON from before this feature has none of the new keys.
    legacy = {"prompt": "p", "candidate_states": [], "mode": "voting"}
    restored = SessionState.from_dict(legacy)
    assert restored.pairs_without_progress == 0
    assert restored.max_pairs_without_progress == DEFAULT_MAX_PAIRS_WITHOUT_PROGRESS
    assert restored.last_active_count == -1
