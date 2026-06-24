# Change Log

All notable changes to the **PICK — LTL Builder** extension are documented here.

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
