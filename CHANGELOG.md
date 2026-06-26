# Change Log

All notable changes to the **PICK — LTL Builder** extension are documented here.

## [Unreleased]

### Honest messaging when the model returns unusable LTL
- When the model replies but its answer can't be turned into usable LTL — no
  JSON, malformed JSON, no formula-bearing candidates, or every formula skipped
  by the backend because it failed to parse — the extension now surfaces a single
  **dismissable warning** that names the model and quotes what was wrong, then
  returns to a retryable state. Previously this showed either a generic "Could
  not generate any candidate formulas" error or a warning **misattributed** as
  "this task may not be suited for LTL" (a formula failing to parse is a model
  syntax failure, not evidence the task is inexpressible). The skip warning now
  reports counts ("N of M interpretations … were not valid LTL and were
  skipped"). Model-syntax problems and genuine expressibility concerns are now
  framed separately.

### Backend is now standalone and minimal
- The Python backend under `python/pick_ltl` is now **owned by this repo** (no
  longer mirrored from another project) and trimmed to exactly what the sidecar
  uses. Removed ~2,400 lines of unreachable code: the Python LLM provider stack
  (`llm/`), Python seed generation, provider settings/config, the standalone
  Flask web UI (`templates/`, `static/`), dead `ltl_formula.py`, and the unused
  routes. The sidecar probe is now `GET /api/health`. Retired
  `util/sync-backend.sh`.

### Candidates
- Seed the backend with **all** of the model's candidate interpretations
  (previously capped at the top 2 by confidence). The backend already
  deduplicates seeds semantically (SPOT equivalence), so more seeds only enrich
  the pool. Hardened that dedup so an undecidable equivalence check can no longer
  crash the whole build.

### Distinguishing traces — no more repeated/duplicate/useless instances
- `next_pair` is now partition-aware. Every emitted pair has two **distinct**
  traces with two distinct acceptance signatures, so a pair never shows the same
  trace twice and is always genuinely distinguishing. It prefers
  not-yet-asked partitions and never pads a pair by cloning a trace (which used
  to yield `trace1 == trace2`).
- When the candidates form a subsumption chain (only one informative split), the
  lone discriminating trace is shown alongside a trace **accepted by none** of
  the candidates (a clean negative example) instead of a redundant one.
- A sole surviving candidate is now finalized as the result (it is the one
  consistent with every answer), rather than stalling when it never landed on
  the accept side of a shown trace.
- **Traces are never requested from the LLM.** The model is asked only for
  candidate formulas; all traces are generated formally by SPOT.

### Tests
- Added a `python/tests` pytest suite covering semantic candidate deduplication
  and trace uniqueness/distinguishing/convergence, wired into CI via a
  micromamba + SPOT job. Tests `skip` when SPOT is unavailable.

## [0.3.0] — 2026-06-24

- Backend setup now works with **nothing preinstalled**. When no
  `conda`/`mamba`/`micromamba` is on `PATH`, **PICK LTL: Set Up / Restart
  Backend** downloads a verified (SHA-256-checked) private `micromamba` into the
  extension's storage and uses it to create the `pick-ltl` environment (SPOT +
  deps). Previously this dead-ended asking the user to install Miniforge by hand.

## [0.2.0] — 2026-06-23

- Re-architected as a frontend over a vendored Python backend (SPOT +
  misconception mutation) run as a managed localhost sidecar. The extension
  spawns and supervises the backend and owns session state; all formal analysis
  (candidate mutation, distinguishing-trace generation, equivalence checking)
  runs in Python via SPOT. Replaces the pure-TypeScript engine from 0.1.0.

## [0.1.0] — 2026-06-08

- Initial version. PICK methodology for Linear Temporal Logic: an LLM proposes
  candidate LTL formulas; the user converges on one by classifying distinguishing
  traces (upvote/downvote).
- Formal analysis via the pure-TypeScript `@sidprasad/ltl-ts` engine (no Python /
  SPOT dependency).
- SVG trace visualization (ported from LTL Tutor), replacing the prior Mermaid
  renderer — shown in the voting pair, classification history, and final result.
