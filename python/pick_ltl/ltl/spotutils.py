from itertools import combinations
import random

try:
    import spot
except ImportError:  # pragma: no cover
    spot = None

from .traceprocessor import expandSpotTrace, getFormulaLiterals

DEFAULT_WEIGHT = 5
DEFAULT_WEIGHT_TEMPORAL = 7
DEFAULT_LTL_PRIORITIES = {
    "ap" : DEFAULT_WEIGHT, 
    "F": DEFAULT_WEIGHT_TEMPORAL,
    "G": DEFAULT_WEIGHT_TEMPORAL,
    "X": DEFAULT_WEIGHT_TEMPORAL,

    "U": DEFAULT_WEIGHT_TEMPORAL,
    "and": DEFAULT_WEIGHT,
    "or": DEFAULT_WEIGHT,
    "equiv": DEFAULT_WEIGHT,
    "implies":DEFAULT_WEIGHT,
    "not": DEFAULT_WEIGHT,
    "false": 1,
    "true":1,
    "W":0,
    "M":0,
    "xor":0,
    "R":0,
}


def _require_spot():
    if spot is None:
        raise RuntimeError(
            "The 'spot' package is required. Install it with "
            "'conda install -c conda-forge spot'."
        )


def areEquivalent(formula1, formula2):
    _require_spot()
    return isSufficientFor(formula1, formula2) and isNecessaryFor(formula1, formula2)





'''
Returns true if f => g is a tautology
'''
def isSufficientFor(f, g):
    _require_spot()

    f = spot.parse_formula(str(f))
    g = spot.parse_formula(str(g))


    a_f = f.translate()
    a_ng = spot.formula.Not(g).translate()
    return spot.product(a_f, a_ng).is_empty()


'''
Returns true if g => f is a tautology
'''
def isNecessaryFor(f, g):
    return isSufficientFor(g, f)


def areDisjoint(f, g):
    _require_spot()
    ff = spot.parse_formula(str(f))
    gf = spot.parse_formula(str(g))

    a_ff = ff.translate()
    a_gf = gf.translate()

    return spot.product(a_ff, a_gf).is_empty()





## THis is really the source of truth.
def generate_trace_excluding(formula, excluded_traces=[]):
    _require_spot()
    """
    Generate a trace that satisfies the formula but is not in the excluded_traces list.
    """
    # Step 1: Translate LTL formula to an automaton
    f = spot.formula(formula)
    phi = f.translate()
    
    # Step 2: For each excluded trace, create complement automata
    exclusion_automata = []
    for trace_str in excluded_traces:
        try:
            # Parse the trace as a word
            word = spot.parse_word(trace_str)
            # Build automaton that accepts only this trace
            trace_aut = word.as_automaton()
            # Complement it (now accepts everything EXCEPT this trace)
            not_trace_aut = spot.complement(trace_aut)
            exclusion_automata.append(not_trace_aut)
        except Exception:
            # An excluded trace we cannot parse just isn't enforced as an
            # exclusion; skip it rather than logging on every call.
            continue

    # Step 3: Create the final automaton by taking product
    final_aut = phi

    # Product with each exclusion automaton
    for excl_aut in exclusion_automata:
        final_aut = spot.product(final_aut, excl_aut)

        # No trace satisfies the formula while avoiding all excluded traces.
        # This is expected once exclusions exhaust the language; the caller
        # handles None, so we stay quiet instead of printing on the hot path.
        if final_aut.is_empty():
            return None


    try:
        run = final_aut.accepting_run()
        if run:
            trace = str(spot.twa_word(run))
            # Double-check it's not in excluded list (safety check)
            if trace not in excluded_traces:
                return trace
    except Exception:
        return None

    return None



def generate_accepted_trace(formula, excluded_traces = []):
    _require_spot()




    # Parse the LTL formula
    f = spot.formula(formula)

    formula_literals = getFormulaLiterals(formula)
    

    
    # Retrieve and return the acceptance condition
    run = generate_trace_excluding(f, excluded_traces)
    expanded_run = expandSpotTrace(run, formula_literals)
    return expanded_run

## Generate traces accepted by f_accepted, and rejected by f_rejected
def generate_trace(f_accepted, f_rejected, excluded_traces = []):
    _require_spot()
    # Parse the LTL formula
    f_a = spot.formula(f_accepted)
    f_r = spot.formula.Not(spot.formula(f_rejected))

    f = spot.formula.And([f_a, f_r])
    run = generate_trace_excluding(f, excluded_traces)

    shared_literals = set(list(getFormulaLiterals(f_accepted)) + list(getFormulaLiterals(f_rejected)))
    expanded_run = expandSpotTrace(run, shared_literals)
    return expanded_run


def generate_trace_in_symmetric_difference(f1s, f2s, excluded_traces = []):
    """
    Generate a trace that satisfies f1 but not f2, and vice versa.
    """
    from . import ltlnode

    f1 = str(ltlnode.parse_ltl_string(f1s))
    f2 = str(ltlnode.parse_ltl_string(f2s))

    # Parse the LTL formulas
    f1_parsed = spot.formula(f1)
    f2_parsed = spot.formula(f2)

    # Create the combined formula for symmetric difference
    combined_formula = spot.formula.Or([
        spot.formula.And([f1_parsed, spot.formula.Not(f2_parsed)]),
        spot.formula.And([spot.formula.Not(f1_parsed), f2_parsed])
    ])

    run = generate_trace_excluding(combined_formula, excluded_traces)
    
    shared_literals = set(list(getFormulaLiterals(f1)) + list(getFormulaLiterals(f2)))
    expanded_run = expandSpotTrace(run, shared_literals)
    
    return expanded_run


def is_trace_satisfied(trace, formula):
    _require_spot()


    from . import ltlnode
    formula = str(ltlnode.parse_ltl_string(formula))

    formula = str(formula)
    trace = str(trace)

    # Parse the trace into a word
    word = spot.parse_word(trace)

    # Words can be translated to automata
    # w.as_automaton()

    # Translate the formula into an automaton
    f = spot.formula(formula)
    aut = f.translate()
    wordaut = word.as_automaton()

    # Check if the automaton intersects with the word automaton
    return aut.intersects(wordaut)


def generate_distinguishing_words(formula1_str: str, formula2_str: str, exclude=None) -> tuple[str, str]:
    """
    Generate two distinguishing words for exactly 2 formulas.
    Returns (word1, word2) where words help distinguish between the formulas.
    
    Two cases:
    1. One formula completely subsumes the other: generate one word in both and one only in the containing formula
    2. Else: generate a word in f1 and not f2 and one in f2 and not f1
    """

    if exclude is None:
        exclude = []

    # Parse formulas to check relationships
    from . import ltlnode
    formula1 = ltlnode.parse_ltl_string(formula1_str)
    formula2 = ltlnode.parse_ltl_string(formula2_str)

    formula1_str = str(formula1)
    formula2_str = str(formula2)

    shared_literals = set(list(getFormulaLiterals(formula1_str)) + list(getFormulaLiterals(formula2_str)))


 
    def _maybe_expand(word):
        if not word:
            return ""
        try:
            return expandSpotTrace(word, shared_literals)
        except Exception:
            # If expansion fails, return the original word as a fallback
            return word

    # Case 1: Check if one formula subsumes the other
    if isSufficientFor(formula1, formula2):
        try:
            word_both = generate_accepted_trace(formula1_str, exclude)
            word_containing = generate_trace(formula2_str, formula1_str, exclude + [word_both] if word_both else exclude)
            return (_maybe_expand(word_both), _maybe_expand(word_containing))
        except:
            return ("", "")

    elif isSufficientFor(formula2, formula1):
        try:
            word_both = generate_accepted_trace(formula2_str, exclude)
            word_containing = generate_trace(formula1_str, formula2_str, exclude + [word_both] if word_both else exclude)
            return (_maybe_expand(word_both), _maybe_expand(word_containing))
        except:
            return ("", "")

    # Case 2: Neither subsumes the other
    else:
        try:
            word1 = generate_trace(formula1_str, formula2_str, exclude)
            word2 = generate_trace(formula2_str, formula1_str, exclude + [word1] if word1 else exclude)
            return (_maybe_expand(word1), _maybe_expand(word2))
        except:
            return ("", "")
        


def generate_two_distinguishing_words(candidates_in_play, excluded_words=None):
    """
    Produce two non-empty trace witnesses that help distinguish among the provided candidate LTL formulas.

    Algorithm Overview:
    
    1. SINGLE-FORMULA PATH (n=1):
       - Generate accepted trace for the formula
       - Generate rejected trace (satisfies ¬formula) 
       - If rejected unavailable, try second distinct accepted trace
       - Fallback to synthetic single-state cycles from formula literals
       - If still insufficient, duplicate single valid trace to meet requirement
    
    2. MULTI-FORMULA PATH (n≥2):
       - Phase 1: Pairwise analysis using generate_distinguishing_words for all formula pairs
       - Phase 2: Collect partial results from pairwise attempts
       - Phase 3: Generate symmetric difference traces between formula pairs
       - Phase 4: Lightweight synthesis using single-state cycles from each formula's literals
       - Phase 5: GUARANTEED FALLBACK - randomly select one candidate and apply single-formula strategy
    
    3. FALLBACK GUARANTEE:
       - If multi-formula phases fail, randomly choose one candidate from candidates_in_play
       - Apply single-formula logic to ensure two non-empty traces are always returned
       - This eliminates ValueError exceptions in favor of guaranteed results

    Contract:
      - If candidates_in_play is empty -> raise ValueError("No Candidates in Play")
      - Returns ONE or TWO *distinct* non-empty trace strings. It never clones a
        single trace to pad the result to two (that produced trace1 == trace2).
      - Raises ValueError only when it cannot produce even one trace.
      - Respects excluded_words (avoids returning previously seen traces)
      - Traces are expanded via expandSpotTrace when possible

    Args:
        candidates_in_play (list): List of LTL formula strings to distinguish between
        excluded_words (list, optional): Previously generated traces to avoid duplicating

    Returns:
        list: Exactly two non-empty trace strings that help distinguish the formulas

    Raises:
        ValueError: Only if candidates_in_play is empty
    """
    _require_spot()

    if excluded_words is None:
        excluded_words = []

    seen = set(excluded_words)
    picks = []
    n = len(candidates_in_play)

    def add_pick(w):
        """Add non-empty, unseen w to picks. Return True if we've reached 2 picks."""
        if not w:
            return False
        if w in seen:
            return False
        seen.add(w)
        picks.append(w)
        return len(picks) >= 2

    if n == 0:
        raise ValueError("No Candidates in Play")

    # Single-formula strict path: must return two non-empty strings or raise
    if n == 1:
        f = candidates_in_play[0]

        # 1) accepted trace
        w_accept = None
        try:
            w_accept = generate_accepted_trace(f, excluded_traces=list(seen))
        except Exception:
            w_accept = None

        if w_accept:
            seen.add(w_accept)

        # 2) rejected trace (accepted by ¬f)
        w_reject = None
        try:
            neg_formula = spot.formula.Not(spot.formula(f))
            run_not = generate_trace_excluding(neg_formula, excluded_traces=list(seen))
            if run_not:
                try:
                    shared_literals = set(list(getFormulaLiterals(f)))
                except Exception:
                    shared_literals = set()
                try:
                    w_reject = expandSpotTrace(run_not, shared_literals)
                except Exception:
                    w_reject = run_not
        except Exception:
            w_reject = None

        if w_accept and w_reject:
            return [w_accept, w_reject]

        # 3) try a second accepted trace distinct from first
        w_accept2 = None
        try:
            w_accept2 = generate_accepted_trace(f, excluded_traces=list(seen))
        except Exception:
            w_accept2 = None

        if w_accept and w_accept2 and w_accept != w_accept2:
            return [w_accept, w_accept2]

        # 4) Synthetic single-state cycles from literals (best-effort)
        try:
            literals = list(getFormulaLiterals(f))
        except Exception:
            literals = []

        synthetic_picks = []
        if literals:
            for lit in literals:
                others = [l for l in literals if l != lit]
                state = " & ".join([lit] + [f"!{o}" for o in others]) if others else lit
                synthetic = f"{state};cycle{{{state}}}"
                if synthetic in seen:
                    continue
                try:
                    expanded = expandSpotTrace(synthetic, set(literals))
                except Exception:
                    expanded = synthetic
                if expanded and expanded not in seen:
                    synthetic_picks.append(expanded)
                    seen.add(expanded)
                if len(synthetic_picks) >= 2:
                    break

        # Assemble results from available pieces
        results = []
        if w_accept:
            results.append(w_accept)
        if w_reject:
            results.append(w_reject)
        # fill with second accepted if distinct
        if len(results) < 2 and w_accept2 and w_accept2 != results[0]:
            results.append(w_accept2)
        # fill with synthetic
        for s in synthetic_picks:
            if len(results) >= 2:
                break
            if s not in results:
                results.append(s)

        # Return the distinct, non-empty traces we found. Never duplicate a
        # trace to pad to two — that produced identical (trace1 == trace2) pairs.
        distinct = []
        for w in results:
            if w and w not in distinct:
                distinct.append(w)
        if not distinct:
            raise ValueError("Could not produce a distinguishing word")
        return distinct[:2]

    # Multi-formula path: try pairwise helpers, partials, Δ, synthesis
    partials = []

    for i, j in combinations(range(n), 2):
        f1, f2 = candidates_in_play[i], candidates_in_play[j]
        try:
            w_ij, w_ji = generate_distinguishing_words(f1, f2, exclude=list(seen))
        except Exception:
            w_ij, w_ji = "", ""

        if w_ij and w_ji and w_ij not in seen and w_ji not in seen:
            add_pick(w_ij)
            add_pick(w_ji)
            if len(picks) == 2:
                return picks[:2]

        if w_ij and w_ij not in seen:
            partials.append(w_ij)
        if w_ji and w_ji not in seen:
            partials.append(w_ji)

    for w in partials:
        if add_pick(w):
            return picks[:2]

    for i, j in combinations(range(n), 2):
        f1, f2 = candidates_in_play[i], candidates_in_play[j]
        try:
            w_delta = generate_trace_in_symmetric_difference(f1, f2, excluded_traces=list(seen))
        except Exception:
            w_delta = None
        if add_pick(w_delta):
            return picks[:2]

    # Lightweight synthetic fallback (single-state cycles)
    for f in candidates_in_play:
        try:
            literals = list(getFormulaLiterals(f))
        except Exception:
            literals = []
        if not literals:
            continue
        for lit in literals:
            others = [l for l in literals if l != lit]
            state = " & ".join([lit] + [f"!{o}" for o in others]) if others else lit
            synthetic = f"{state};cycle{{{state}}}"
            if synthetic in seen:
                continue
            try:
                expanded = expandSpotTrace(synthetic, set(literals))
            except Exception:
                expanded = synthetic
            if add_pick(expanded):
                return picks[:2]

    # Final fallback: choose a random candidate and apply single-formula strategy
    # This guarantees we return two non-empty traces (may duplicate) instead of raising
    candidate = random.choice(candidates_in_play)
    
    # Apply single-formula logic to the randomly chosen candidate
    # 1) accepted trace
    w_accept = None
    try:
        w_accept = generate_accepted_trace(candidate, excluded_traces=list(seen))
    except Exception:
        w_accept = None

    if w_accept:
        seen.add(w_accept)

    # 2) rejected trace (accepted by ¬candidate)
    w_reject = None
    try:
        neg_formula = spot.formula.Not(spot.formula(candidate))
        run_not = generate_trace_excluding(neg_formula, excluded_traces=list(seen))
        if run_not:
            try:
                shared_literals = set(list(getFormulaLiterals(candidate)))
            except Exception:
                shared_literals = set()
            try:
                w_reject = expandSpotTrace(run_not, shared_literals)
            except Exception:
                w_reject = run_not
    except Exception:
        w_reject = None

    # 3) try a second accepted trace distinct from first
    w_accept2 = None
    if not w_reject:
        try:
            w_accept2 = generate_accepted_trace(candidate, excluded_traces=list(seen))
        except Exception:
            w_accept2 = None

    # 4) Synthetic single-state cycles from this candidate's literals
    synthetic_picks = []
    if (not w_accept or not w_reject) and (not w_accept2 or w_accept2 == w_accept):
        try:
            literals = list(getFormulaLiterals(candidate))
        except Exception:
            literals = []
        if literals:
            for lit in literals:
                others = [l for l in literals if l != lit]
                state = " & ".join([lit] + [f"!{o}" for o in others]) if others else lit
                synthetic = f"{state};cycle{{{state}}}"
                if synthetic in seen:
                    continue
                try:
                    expanded = expandSpotTrace(synthetic, set(literals))
                except Exception:
                    expanded = synthetic
                if expanded and expanded not in seen:
                    synthetic_picks.append(expanded)
                    seen.add(expanded)
                if len(synthetic_picks) >= 2:
                    break

    # Assemble final results from available pieces
    results = []
    if w_accept:
        results.append(w_accept)
    if w_reject:
        results.append(w_reject)
    # fill with second accepted if distinct
    if len(results) < 2 and w_accept2 and w_accept2 != results[0]:
        results.append(w_accept2)
    # fill with synthetic
    for s in synthetic_picks:
        if len(results) >= 2:
            break
        if s not in results:
            results.append(s)

    # Return the distinct, non-empty traces we found. Never duplicate a trace to
    # pad to two — that produced identical (trace1 == trace2) pairs.
    distinct = []
    for w in results:
        if w and w not in distinct:
            distinct.append(w)
    if not distinct:
        raise ValueError("Could not produce a distinguishing word")
    return distinct[:2]


def generate_distinguishing_trace_pool(formulas, excluded=None, target=12):
    """Produce a pool of DISTINCT, non-empty, expanded trace strings drawn from
    several distinguishing strategies, so a caller can pick the most informative
    pair (rather than blindly taking the first two words).

    Unlike generate_two_distinguishing_words this never duplicates a trace and
    makes no guarantee about count — it returns as many distinct traces as it
    can find (0..target). Sources, in order: pairwise distinguishing words,
    symmetric-difference traces, then per-formula accepted/rejected traces.
    """
    _require_spot()

    if excluded is None:
        excluded = []
    seen = set(excluded)
    pool: list[str] = []

    def add(word):
        if word and word not in seen:
            seen.add(word)
            pool.append(word)

    formulas = list(formulas)
    n = len(formulas)

    for i, j in combinations(range(n), 2):
        if len(pool) >= target:
            break
        f1, f2 = formulas[i], formulas[j]
        try:
            w_ij, w_ji = generate_distinguishing_words(f1, f2, exclude=list(seen))
        except Exception:
            w_ij, w_ji = "", ""
        add(w_ij)
        add(w_ji)
        try:
            w_delta = generate_trace_in_symmetric_difference(f1, f2, excluded_traces=list(seen))
        except Exception:
            w_delta = None
        add(w_delta)

    for f in formulas:
        if len(pool) >= target:
            break
        try:
            add(generate_accepted_trace(f, excluded_traces=list(seen)))
        except Exception:
            pass
        try:
            neg_formula = spot.formula.Not(spot.formula(f))
            run_not = generate_trace_excluding(neg_formula, excluded_traces=list(seen))
            if run_not:
                try:
                    literals = set(getFormulaLiterals(f))
                except Exception:
                    literals = set()
                try:
                    add(expandSpotTrace(run_not, literals))
                except Exception:
                    add(run_not)
        except Exception:
            pass

    # A trace accepted by NONE of the candidates (rejected by all). This is the
    # clean "obviously-out" example used to partner a lone discriminating trace
    # when the candidates form a subsumption chain (only one informative split).
    if n >= 1:
        try:
            neg_all = spot.formula.And([spot.formula.Not(spot.formula(f)) for f in formulas])
            run = generate_trace_excluding(neg_all, excluded_traces=list(seen))
            if run:
                literals = set()
                for f in formulas:
                    try:
                        literals |= set(getFormulaLiterals(f))
                    except Exception:
                        continue
                try:
                    add(expandSpotTrace(run, literals))
                except Exception:
                    add(run)
        except Exception:
            pass

    return pool


def generate_accepting_words(automaton, max_runs=5):
    _require_spot()

    words = []
    current_aut = automaton
    for _ in range(max_runs):
        if current_aut.is_empty():
            break
        run = current_aut.accepting_run()
        if not run:
            break
        word = spot.twa_word(run)
        word_str = str(word)
        if word_str not in words:
            words.append(word_str)
        try:
            trace_aut = word.as_automaton()
            current_aut = spot.product(current_aut, spot.complement(trace_aut))
        except Exception:
            break
    return words


def generate_accepted_traces(formula, max_traces=5):
    _require_spot()
    return generate_accepting_words(spot.formula(formula).translate(), max_runs=max_traces)


def generate_traces(f_accepted, f_rejected, max_traces=5):
    _require_spot()
    f_a = spot.formula(f_accepted)
    f_r = spot.formula.Not(spot.formula(f_rejected))
    return generate_accepting_words(spot.formula.And([f_a, f_r]).translate(), max_runs=max_traces)


def is_trivial(formula_str):
    _require_spot()
    try:
        simplified = spot.simplify(spot.formula(formula_str))
    except Exception:
        return False
    return str(simplified) in {"1", "0", "true", "false"}


def is_degenerate(formula_str):
    """True if the formula's language is empty (unsatisfiable) or universal
    (a tautology) — i.e. it accepts no trace or every trace.

    Such a candidate is useless for distinguishing: it rejects everything or
    accepts everything, so no classification ever contradicts it. An empty
    candidate in particular survives every "reject" answer as a phantom
    "perfect" formula. `is_trivial` only catches *syntactic* trivialities
    (simplify -> 1/0); this catches *semantic* ones like
    `G((a <-> F(!a)))`, which is unsatisfiable but does not simplify to 0.
    """
    _require_spot()
    try:
        f = spot.formula(formula_str)
    except Exception:
        return False
    try:
        if f.translate().is_empty():  # unsatisfiable: accepts no trace
            return True
        return spot.formula.Not(f).translate().is_empty()  # tautology: rejects no trace
    except Exception:
        return False


def gen_rand_ltl(atoms, tree_size, ltl_priorities, num_formulae=5):
    _require_spot()
    priorities = ",".join(f"{k}={v}" for k, v in ltl_priorities.items())
    generator = spot.randltl(atoms, tree_size=tree_size, ltl_priorities=priorities)
    return [str(next(generator)) for _ in range(num_formulae)]


def gen_small_rand_ltl(atoms, tree_size=3, max_attempts=10):
    priorities = {
        "ap": 5,
        "G": 2,
        "F": 2,
        "X": 2,
        "U": 3,
        "and": 4,
        "or": 4,
        "implies": 3,
        "not": 3,
        "equiv": 1,
        "xor": 0,
        "R": 0,
        "W": 0,
        "M": 0,
        "true": 0,
        "false": 0,
    }
    for _ in range(max_attempts):
        try:
            formula = gen_rand_ltl(atoms, tree_size, priorities, num_formulae=1)[0]
        except Exception:
            continue
        if not is_trivial(formula):
            return formula
    return random.choice(atoms)
