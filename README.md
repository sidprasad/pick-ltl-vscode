# PICK — LTL Builder

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Open in GitHub Codespaces](https://img.shields.io/badge/Open_in-Codespaces-181717?logo=github)](https://codespaces.new/sidprasad/pick-ltl-vscode)

# What it is

PICK (Pairwise Iterative-Choice Knockout) helps you make smart use of generative AI to author **Linear Temporal Logic (LTL)** formulas. You describe a temporal property in natural language; PICK proposes several candidate formulas and helps you converge on the one you actually mean by classifying concrete example **traces**.

This is the LTL counterpart of PICK-Formula. The formal analysis — **misconception-based candidate mutation** and **SPOT**-backed distinguishing-trace generation — runs in a local Python sidecar that the extension launches and supervises for you.

---

# How it works

1. Asks a language model for one or two **seed** LTL formulas capturing how your description might be interpreted, then expands them in the Python backend with **misconception mutations** (8 common LTL misunderstandings — e.g. dropping an eventually/always, swapping `G`/`F`, weak/exclusive until) to build a pool of plausible-but-distinct candidates.
2. Uses **SPOT** to generate **distinguishing traces** — ultimately-periodic (lasso) words the candidates disagree on — and renders each as an **SVG diagram** (state boxes, cycle arc, positive/negated literals).
3. Asks you to upvote/downvote whether each trace *should* satisfy your intended property. Each vote is really a decision about the candidate formulas.
4. Eliminates candidates that disagree with your classifications. You can **revise** your description at any time; PICK retains all your classifications.
5. Terminates when one formula remains, or when none do (so you can revise). Stop whenever you're satisfied.

The LTL operators understood are `!`, `X`, `F`, `G`, `&`, `|`, `U`, `->`, `<->` (atoms match `[a-z0-9]+`). Traces use Spot's lasso syntax, e.g. `a&!b;cycle{a&b}`.

---

# Try it in a Codespace

No local setup required — open this repo in a [GitHub Codespace](https://codespaces.new/sidprasad/pick-ltl-vscode) (or click the badge at the top). The dev container installs PICK from the Marketplace, so it's already in the activity bar when the Codespace opens.

1. Open the **PICK LTL Builder** view in the activity bar.
2. First time only: click **Set Up Backend** when prompted (or run **PICK LTL: Set Up / Restart Backend** → **Set up automatically**). The container has no conda, so PICK downloads `micromamba` and builds the `pick-ltl` env (SPOT + deps) — a few minutes, once.
3. When prompted, grant **Language Model** access (Copilot is preinstalled) and start authoring.

---

# Prerequisites

PICK needs two things:

1. **A language model extension** enabled in VS Code (for seed generation). We recommend **GitHub Copilot** (GitHub Copilot Free, included with any GitHub account, is sufficient). When you first use PICK, VS Code prompts you to grant the extension access to Language Models — **click "Allow"**.

2. **A Python backend with SPOT** (for misconception mutation + trace generation). `spot` ships on conda-forge (not PyPI), so the backend lives in a conda environment. The simplest path:

   - Run **PICK LTL: Set Up / Restart Backend** from the Command Palette and choose **Set up automatically**. PICK creates a `pick-ltl` environment (`spot` + deps) for you in one click — using `conda`/`mamba`/`micromamba` if you already have one, otherwise downloading a small private `micromamba` first. No prior conda install is required.
   - Or create it yourself and let PICK auto-detect it:
     ```bash
     conda create -n pick-ltl python=3.12
     conda activate pick-ltl
     conda install -c conda-forge spot
     pip install -r python/requirements.txt
     ```
   - To use a specific interpreter, set `pick-ltl.backend.pythonPath` to its absolute path.

   The extension starts the backend automatically on a private localhost port and shuts it down when VS Code closes. Your description still goes to the LLM for seed generation, but **all formal analysis stays on your machine.**

---

# Settings

All settings appear under the `pick-ltl` section in VS Code Settings, including:

- `pick-ltl.backend.pythonPath` (string) — absolute path to a Python interpreter whose environment has `spot`. Empty auto-detects a conda env named `pick-ltl`.
- `pick-ltl.backend.autoStart` (boolean, default true) — start the backend sidecar on activation.
- `pick-ltl.backend.port` (number, default 0) — localhost port for the sidecar; 0 picks a free one.
- `pick-ltl.surveyPromptEnabled` (boolean, default true).

Candidate count and elimination thresholds are determined by the backend (misconception expansion + SPOT), so the older TS-era vote/threshold/candidate knobs have been removed.

---

# Development

The extension bundles **no LTL engine**: all formal analysis runs in the Python backend (SPOT). Trace SVGs are produced by a small committed renderer ([`media/vendor/tracerenderer.js`](media/vendor/tracerenderer.js)) fed render data parsed from SPOT's lasso strings by [`src/traceRender.ts`](src/traceRender.ts).

The Python backend under [`python/pick_ltl`](python/pick_ltl) is **self-contained and owned by this repo** — it is the canonical PICK engine, not a mirror of another project, and it ships inside the `.vsix`. It is trimmed to exactly what the sidecar needs (candidate building, misconception/syntactic mutation, SPOT trace generation/equivalence, and the session engine); the seeds come from the extension's `vscode.lm` integration, so the backend does no LLM work itself. See [`python/README.md`](python/README.md) for the API surface and tests.

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

`npm run package:vsix` (i.e. `@vscode/vsce package`) produces a working `.vsix` (~2.5 MB). Because the engine is a normal GitHub dependency installed into `node_modules` (not a local symlink), it bundles `@sidprasad/ltl-ts/dist`, its runtime dependency `antlr4ng`, and the SVG renderer correctly. Do **not** exclude `antlr4ng` from `.vscodeignore` — it is a runtime dependency of the engine.

---

# Releasing

Releases are automated by [`.github/workflows/release.yml`](.github/workflows/release.yml). To cut one, push a version tag:

```bash
npm version patch        # bumps package.json version and creates a git tag
git push --follow-tags   # pushes the commit + tag
# or manually: git tag v0.1.0 && git push origin v0.1.0
```

On a `v*` tag the workflow installs deps, compiles, lints, runs the engine-bridge tests, packages the `.vsix`, and **creates a GitHub Release with the `.vsix` attached**. (`workflow_dispatch` builds + uploads the `.vsix` as an artifact without creating a release.)

To also publish to the registries, add repository **secrets** (Settings → Secrets and variables → Actions); the corresponding step runs only when its secret is present:

- `VSCE_PAT` — a Visual Studio Marketplace Personal Access Token (publisher `SiddharthaPrasad`) → publishes to the VS Code Marketplace.
- `OVSX_PAT` — an [Open VSX](https://open-vsx.org) access token → publishes to Open VSX.

`ci.yml` runs compile + lint + the full VS Code integration tests (under `xvfb`) on every push/PR to `main`.

---

# Logs

1. Open View → Output (Ctrl/Cmd + Shift + U).
2. Select **"PICK LTL Builder"** in the Output dropdown.

---

# Privacy and Data

PICK sends your description to the configured LLM provider solely for seed generation. All formal analysis (misconception mutation, trace generation, membership, equivalence) happens locally in the Python sidecar over a private localhost port; nothing leaves your machine for that step. The extension stores no prompts or results. LLM providers may log requests per their own policies — avoid placing sensitive information in prompts if this is a concern.

---

# Disclaimers

PICK is new, research-grade software, offered as-is without warranty; use at your own risk. Its correctness depends on your prompt, your classification choices, and the LLM. Review all outputs before relying on them.

---

# Credits

PICK is a collaboration between Siddhartha Prasad, Skyler Austen, Kathi Fisler, and Shriram Krishnamurthi. Siddhartha Prasad is the primary author of this version of the tool.

---

# License

MIT — see [LICENSE](LICENSE).
