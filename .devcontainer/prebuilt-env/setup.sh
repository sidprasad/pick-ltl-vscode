#!/usr/bin/env bash
#
# Prebuild-time provisioning for the "prebuilt env (fast)" Codespace variant.
#
# Installs Miniforge to ~/miniforge3 and creates the `pick-ltl` env (SPOT + deps)
# there. The extension's resolvePythonCandidates() scans ~/miniforge3/envs, so it
# auto-detects ~/miniforge3/envs/pick-ltl with no settings — the backend starts
# immediately, with no first-run download. Heavy, but cached by Codespaces
# prebuilds when enabled (run from onCreateCommand).
#
# This is the opposite of the default (clean) config: it pre-bakes the env, so it
# does NOT exercise the from-scratch micromamba bootstrap. Use the clean config
# for that.
set -euxo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# --- Miniforge (conda-forge defaults) into an auto-detected location ----------
case "$(uname -m)" in
  x86_64) MF_ARCH="x86_64" ;;
  aarch64 | arm64) MF_ARCH="aarch64" ;;
  *) echo "Unsupported arch $(uname -m) for the prebuilt env; use the clean config." >&2; exit 1 ;;
esac

if [ ! -x "$HOME/miniforge3/bin/conda" ]; then
  curl -fsSL -o /tmp/miniforge.sh \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${MF_ARCH}.sh"
  bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
  rm -f /tmp/miniforge.sh
fi
CONDA="$HOME/miniforge3/bin/conda"

# --- The pick-ltl env: SPOT from conda-forge + pip deps -----------------------
if ! "$CONDA" env list | grep -qE '/envs/pick-ltl$'; then
  "$CONDA" create -y -n pick-ltl -c conda-forge spot python=3.12
fi
"$CONDA" run -n pick-ltl python -m pip install -r python/requirements.txt

# --- Build the extension so it's ready to F5 ----------------------------------
npm ci
npm run compile

echo "Prebuilt env ready: $HOME/miniforge3/envs/pick-ltl (auto-detected by the extension)."
