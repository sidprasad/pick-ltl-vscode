# No-progress safety valve — manual verification

The engine logic is covered by `python/tests/test_progress.py`. The webview
rendering of the two stop states cannot be unit-tested, so it is verified
manually here.

## Setup
1. Start the backend and open the PICK LTL view.
2. Set `pick-ltl.maxPairsWithoutProgress` to `2` (Settings) to trigger the valve
   quickly.

## Case A — best match surfaced (a candidate was upvoted)
1. Build candidates from any prompt that yields ≥3 interpretations.
2. Accept one trace that matches your intent, then answer the next few pairs
   without ruling anything new out (e.g. classify both words the same way the
   surviving candidates already agree on).
3. **Expected:** after 2 stale pairs the view shows the *"Best match so far"*
   result with the most-upvoted formula and the message "We stopped narrowing:
   the last N comparisons ruled nothing out…". The candidate is highlighted.

## Case B — standstill, nothing confirmed (regression for the ignored message)
1. Build candidates, then answer every pair **Unsure** (never accept anything).
2. **Expected:** after 2 stale pairs the view shows the *"No more comparisons to
   show"* panel whose body is the backend message: "We stopped narrowing: the
   last N comparisons ruled nothing out, and no candidate has an accepted example
   yet. Add a trace that should match, or pick a candidate below." Surviving
   candidates remain listed and copyable.
   - Before the fix this panel always read "The system ran out of distinguishing
     words to generate" regardless of the real reason.

## Case C — reclassify revival does not trip the valve
1. Reach a state with a couple of stale pairs counted (Case A, before it fires).
2. Reclassify an earlier answer so a previously eliminated candidate becomes
   active again.
3. **Expected:** the next pair is a normal comparison, not an early "Best match
   so far" — the stale streak resets when the live set changes.
