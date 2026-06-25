"""Low-level SPOT helpers: equivalence and non-duplicating trace generation."""

import pytest

pytest.importorskip("spot")

from pick_ltl.ltl.spotutils import (
    areEquivalent,
    generate_distinguishing_trace_pool,
    generate_two_distinguishing_words,
    is_trace_satisfied,
)


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
