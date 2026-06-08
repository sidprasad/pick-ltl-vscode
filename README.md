# PICK — LTL Builder

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

# What it is

PICK (Pairwise Iterative-Choice Knockout) helps you make smart use of generative AI to author **Linear Temporal Logic (LTL)** formulas. You describe a temporal property in natural language; PICK proposes several candidate formulas and helps you converge on the one you actually mean by classifying concrete example **traces**.

This is the LTL counterpart of PICK-Regex. The formal analysis runs entirely in TypeScript via the [`@sidprasad/ltl-ts`](https://github.com/sidprasad/ltl-ts) engine — **no Python and no SPOT dependency** — so it runs anywhere VS Code does.

---

# How it works

1. Asks a language model to generate a handful of candidate LTL formulas, corresponding to different ways your description might be interpreted (safety vs. liveness, scope of `G`/`F`, strict vs. non-strict, …).
2. Generates **distinguishing traces** — ultimately-periodic (lasso) words that the candidates disagree on — and renders each as an **SVG diagram** (state boxes, cycle arc, positive/negated literals).
3. Asks you to upvote/downvote whether each trace *should* satisfy your intended property. Each vote is really a decision about the candidate formulas.
4. Eliminates candidates that disagree with your classifications. You can **revise** your description at any time; PICK retains all your classifications.
5. Terminates when one formula remains, or when none do (so you can revise). Stop whenever you're satisfied.

The LTL operators understood are `!`, `X`, `F`, `G`, `&`, `|`, `U`, `->`, `<->` (atoms match `[a-z0-9]+`). Traces use Spot's lasso syntax, e.g. `a&!b;cycle{a&b}`.

---

# Prerequisites

PICK requires a language model extension enabled in VS Code. We recommend **GitHub Copilot** (GitHub Copilot Free, included with any GitHub account, is sufficient). When you first use PICK, VS Code prompts you to grant the extension access to Language Models — **click "Allow"**.

---

# Settings

All settings appear under the `pick-ltl` section in VS Code Settings, including:

- `pick-ltl.eliminationThreshold` (number, default 2) — negative votes required to eliminate a candidate formula.
- `pick-ltl.maxCandidates` (number, default 4) — how many candidate formulas to consider.
- `pick-ltl.searchTimeoutMs` (number, default 8000) — budget for engine trace-generation calls.
- `pick-ltl.surveyPromptEnabled` (boolean, default true).

---

# Development

This extension depends on the LTL engine [`@sidprasad/ltl-ts`](https://github.com/sidprasad/ltl-ts) as a **GitHub dependency** (`"@sidprasad/ltl-ts": "github:sidprasad/ltl-ts#v0.1.0"`), so a plain `npm install` pulls it — no sibling checkout required. The engine repo ships its built `dist/`, so no build step runs at install time.

> The engine repo is currently **private**, so `npm install` (and any CI) must have GitHub credentials to clone it. On a machine signed in with the GitHub CLI / git over HTTPS this works automatically.

```bash
npm install        # pulls @sidprasad/ltl-ts from GitHub
npm run compile    # copies the SVG renderer into media/vendor + tsc -> out/
npm run watch      # incremental builds
npm test           # clean + compile + lint + run the VS Code integration tests
```

Then press **F5** (or pick "Run Extension") to launch an Extension Development Host, or "Extension Tests" to debug the test suite.

The webview trace renderer (`media/vendor/tracerenderer.js`) is copied from the engine's `viz/` by the `vendor:copy` step of `compile`; do not edit it by hand.

---

# Packaging

`npm run package:vsix` (i.e. `vsce package`) produces a working `.vsix` (~2.5 MB). Because the engine is a normal GitHub dependency installed into `node_modules` (not a local symlink), `vsce` bundles `@sidprasad/ltl-ts/dist`, its runtime dependency `antlr4ng`, and the SVG renderer correctly. Do **not** exclude `antlr4ng` from `.vscodeignore` — it is a runtime dependency of the engine. (Marketplace publishing would additionally require making the engine repo public or pre-bundling it, since the Marketplace pipeline cannot clone a private dependency.)

---

# Logs

1. Open View → Output (Ctrl/Cmd + Shift + U).
2. Select **"PICK LTL Builder"** in the Output dropdown.

---

# Privacy and Data

PICK sends your description to the configured LLM provider solely for candidate generation. All formal analysis (trace generation, membership, equivalence) happens locally in the engine. The extension stores no prompts or results. LLM providers may log requests per their own policies — avoid placing sensitive information in prompts if this is a concern.

---

# Disclaimers

PICK is new, research-grade software, offered as-is without warranty; use at your own risk. Its correctness depends on your prompt, your classification choices, and the LLM. Review all outputs before relying on them.

---

# Credits

PICK is a collaboration between Siddhartha Prasad, Skyler Austen, Kathi Fisler, and Shriram Krishnamurthi. Siddhartha Prasad is the primary author of this version of the tool.

---

# License

MIT — see [LICENSE](LICENSE).
