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

## Provenance

`pick_ltl/` is **vendored** from the standalone
[`pick-ltl`](https://github.com/sidprasad/pick-ltl) project so the `.vsix` is
self-contained. Re-sync it after upstream changes:

```bash
./util/sync-backend.sh                 # defaults to ../pick-ltl/src/pick_ltl
./util/sync-backend.sh /path/to/pick_ltl
```

`preflight.py` is owned by the extension and is **not** overwritten by the sync.

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
# {"python": "3.12.x", "spot": true, "flask": true, "antlr4": true, "requests": true, "ok": true}
```
