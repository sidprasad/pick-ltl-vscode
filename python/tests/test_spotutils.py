"""Low-level SPOT helpers: equivalence and non-duplicating trace generation."""

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.spotutils import (
    areEquivalent,
    generate_accepted_trace,
    generate_distinguishing_trace_pool,
    generate_two_distinguishing_words,
    is_degenerate,
    is_trace_satisfied,
    is_trivial,
    validate_trace,
)
from pick_ltl.ltl.traceprocessor import expandSpotTrace


@pytest.mark.parametrize("trace", ["a & b; cycle{!a}", "cycle{a}", "a; cycle{b}", "  cycle{a}  "])
def test_validate_trace_accepts_wellformed_lasso_words(trace):
    assert validate_trace(trace) is None


def test_validate_trace_empty_is_rejected():
    assert "empty" in validate_trace("   ").lower()


def test_validate_trace_without_cycle_explains_cycle_requirement():
    # The single most common user mistake: a finite prefix with no cycle. SPOT's
    # own "twa_word must contain a cycle" jargon is translated to plain language.
    msg = validate_trace("a & b")
    assert msg is not None
    assert "cycle" in msg.lower()
    assert "twa_word" not in msg  # jargon must be translated away


@pytest.mark.parametrize("trace", ["cyckle{a}", "a & b; cycle{!a", "XXX (b))", "a &; cycle{b}"])
def test_validate_trace_rejects_malformed_with_format_hint(trace):
    msg = validate_trace(trace)
    assert msg is not None
    # Every rejection points the user at the expected shape.
    assert "cycle{" in msg


def test_are_equivalent_recognizes_equivalent_formulas():
    assert areEquivalent("F(a)", "F(F(a))")
    assert areEquivalent("G(a)", "G(G(a))")
    assert areEquivalent("a", "!!a")


def test_are_equivalent_rejects_inequivalent_formulas():
    assert not areEquivalent("F(a)", "G(a)")
    assert not areEquivalent("G(r -> F(b))", "G(r -> b)")


def test_two_distinguishing_words_never_duplicates():
    words = generate_two_distinguishing_words(["F(a)", "G(a)"])
    assert 1 <= len(words) <= 2
    assert all(w for w in words)
    assert len(set(words)) == len(words), f"duplicate trace returned: {words}"


def test_two_distinguishing_words_single_formula_is_distinct():
    words = generate_two_distinguishing_words(["F(a)"])
    assert 1 <= len(words) <= 2
    assert len(set(words)) == len(words)


def test_trace_pool_entries_are_all_distinct():
    pool = generate_distinguishing_trace_pool(["G(r -> F(b))", "G(r -> b)", "F(b)"])
    assert pool, "expected a non-empty pool"
    assert len(set(pool)) == len(pool), "pool contained duplicate traces"


def test_trace_pool_respects_exclusions():
    formulas = ["G(r -> F(b))", "G(r -> b)", "F(b)"]
    first = generate_distinguishing_trace_pool(formulas)
    assert first
    excluded = first[:2]
    second = generate_distinguishing_trace_pool(formulas, excluded=excluded)
    assert all(trace not in excluded for trace in second)


def test_distinguishing_words_actually_distinguish():
    words = generate_two_distinguishing_words(["F(a)", "G(a)"])
    # At least one returned trace must separate the two formulas.
    separates = any(
        is_trace_satisfied(w, "F(a)") != is_trace_satisfied(w, "G(a)") for w in words
    )
    assert separates


def test_is_degenerate_catches_semantic_unsat_and_tautology():
    # Unsatisfiable: e must be true (to make e<->F(!e) hold when false fails) yet
    # then F(!e) is false -> contradiction. SPOT's simplify does NOT reduce this
    # to 0, so is_trivial misses it but is_degenerate (emptiness check) catches it.
    unsat = "G((e <-> F(!e)))"
    assert is_degenerate(unsat)
    assert not is_trivial(unsat)
    # Tautology: rejects no trace.
    assert is_degenerate("G(a | !a)")


def test_is_degenerate_accepts_normal_formulas():
    for f in ["G(a <-> X(!a))", "G(r -> F(b))", "F(g)", "a U b", "G((e <-> X(!e)) & !(e & h))"]:
        assert not is_degenerate(f), f


def test_expand_spot_trace_preserves_cycle_period():
    # expandSpotTrace must not lengthen the lasso period. `cycle{!a;a}` denotes
    # the period-2 word a is F,T,F,T,...; expansion only fills in missing
    # literals, so it must remain a 2-state cycle (regression: a stray
    # cycle_states.append(cycle_states[0]) turned `{!a;a}` into `{!a;a;!a}`,
    # i.e. period 3, which no longer satisfies G(a <-> X(!a))).
    expanded = expandSpotTrace("a;cycle{!a;a}", {"a"})
    assert is_trace_satisfied(expanded, "G(a <-> X(!a))"), expanded


# A trace the generator labels "accepted" must actually be accepted by the
# formula it was generated from. This consistency between generation and
# checking is what the whole distinguishing-trace engine relies on; cyclic /
# strict-alternation formulas are the cases the period bug silently broke.
@pytest.mark.parametrize(
    "formula",
    [
        "G(a <-> X(!a))",
        "G(((e <-> X(!e)) & !(e & h)))",
        "G(r -> F(b))",
        "F(g)",
        "G(a -> X(b))",
    ],
)
def test_generated_accepted_trace_is_actually_satisfied(formula):
    trace = generate_accepted_trace(formula, excluded_traces=[])
    assert trace, f"generator produced no accepted trace for {formula!r}"
    assert is_trace_satisfied(trace, formula), (
        f"generator claimed {trace!r} is accepted by {formula!r}, but it is not"
    )


def test_pool_has_informative_split_for_alternation_subsumption():
    # L(G(e<->X!e)) is a proper subset of L(F(G(e<->X!e))): a trace that
    # alternates from the start is in both; one that only alternates eventually
    # is in the weaker formula alone. The pool must surface that distinguishing
    # trace rather than collapsing to "accepted by neither".
    strong = "G(((e <-> X(!e)) & !(e & h)))"
    weak = "G(!(e & h)) & F(G(e <-> X(!e)))"
    pool = generate_distinguishing_trace_pool([strong, weak])
    assert any(
        is_trace_satisfied(t, strong) != is_trace_satisfied(t, weak) for t in pool
    ), "pool has no trace separating the two alternation formulas"
