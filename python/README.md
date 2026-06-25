# PICK LTL backend (sidecar)

This directory contains the Python backend that the VS Code extension runs as a
local sidecar. It is the formal engine behind PICK:

- **misconception mutation** — expands LLM seed formulas into a candidate pool
  using the 8 LTL misconception types (`pick_ltl/mutation/`),
- **SPOT** — generates distinguishing traces, checks trace membership, and tests
  equivalence (`pick_ltl/ltl/spotutils.py`).

The extension spawns it (`flask --app pick_ltl.app run`) on a random localhost
port and talks to its `/api/*` endpoints. The server is stateless — the
extension passes the session JSON in each request.

The seed formulas come from the extension's own language model integration
(VS Code's `vscode.lm` / Copilot), which POSTs them to `/api/candidates/build`.
The backend does **no** LLM work itself: it only expands seeds, deduplicates,
generates distinguishing traces, and runs the voting loop.

## Scope & provenance

This directory is the **canonical, self-contained** PICK engine for the
extension — it is no longer a mirror synced from another repo. It contains only
what the sidecar needs: candidate building + misconception/syntactic mutation
(`pick_ltl/mutation/`), SPOT trace generation/equivalence
(`pick_ltl/ltl/spotutils.py`), the LTL parser/printer/English renderer
(`pick_ltl/ltl/`), and the session engine + HTTP routes
(`pick_ltl/session/`, `pick_ltl/api/`). The standalone Flask web UI and the
Python LLM providers were removed because the extension drives those concerns.

## Endpoints

`GET /api/health` (liveness), and stateless `POST` engine endpoints:
`/api/candidates/build`, `/api/session/next-pair`, `/api/session/classify`,
`/api/session/reclassify`, `/api/session/examples`, `/api/session/finalize`,
`/api/session/import`.

## Tests

```bash
PYTHONPATH=python python -m pytest python/tests -q   # requires spot (+ hypothesis for PBT)
```

The suite covers semantic candidate deduplication, trace uniqueness (no
duplicate or non-distinguishing trace pairs), and the dynamic elimination
threshold. It also includes **property-based tests** (Hypothesis) that generate
random LTL formulas and assert the engine invariants for every input: every
shown pair is distinct and distinguishing, no trace repeats, the loop always
terminates, and a candidate equivalent to the (consistent) ground truth is never
eliminated nor mis-converged away from. Tests `skip` automatically when `spot`
(or, for the PBT, `hypothesis`) is not importable.

## One-time environment setup

End users don't need to do this by hand: **PICK LTL: Set Up / Restart Backend**
provisions the `pick-ltl` env automatically, downloading a private `micromamba`
(see [`../src/micromamba.ts`](../src/micromamba.ts)) first when no conda tool is
on PATH. The manual steps below are for development or when you want to manage
the env yourself.

`spot` is a compiled C++ library distributed via conda-forge (not PyPI), so the
backend needs a conda environment:

```bash
conda create -n pick-ltl python=3.12
conda activate pick-ltl
conda install -c conda-forge spot
pip install -r python/requirements.txt
```

The extension auto-detects a conda env named `pick-ltl`. To use a different
interpreter, set `pick-ltl.backend.pythonPath` in VS Code settings to its
absolute path, then run **PICK LTL: Set Up / Restart Backend**.

## Verifying the environment

```bash
PYTHONPATH=python python python/preflight.py
# {"python": "3.12.x", "spot": true, "flask": true, "antlr4": true, "ok": true}
```
