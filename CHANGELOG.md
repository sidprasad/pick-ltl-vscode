# Change Log

All notable changes to the **PICK — LTL Builder** extension are documented here.

## [0.1.0] — Unreleased

- Initial version. PICK methodology for Linear Temporal Logic: an LLM proposes
  candidate LTL formulas; the user converges on one by classifying distinguishing
  traces (upvote/downvote).
- Formal analysis via the pure-TypeScript `@sidprasad/ltl-ts` engine (no Python /
  SPOT dependency).
- SVG trace visualization (ported from LTL Tutor), replacing the prior Mermaid
  renderer — shown in the voting pair, classification history, and final result.
