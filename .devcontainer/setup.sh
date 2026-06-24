#!/usr/bin/env bash
#
# Codespace setup: build and package the PICK extension from THIS branch's source
# so the Codespace can install it with no marketplace release. The resulting
# .vsix is installed into the editor by the devcontainer's postCreateCommand,
# so PICK appears in the activity bar when the Codespace opens.
#
# The SPOT backend is NOT provisioned here — the installed extension sets it up on
# first use: click "Set Up Backend", which downloads micromamba and builds the
# pick-ltl env (this also exercises the from-scratch bootstrap).
set -euxo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

npm ci
# `vsce package` runs the vscode:prepublish script (npm run compile) itself.
npx --yes @vscode/vsce package -o "$HOME/pick-ltl.vsix"

echo "Packaged $HOME/pick-ltl.vsix"
