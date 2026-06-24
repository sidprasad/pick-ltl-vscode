/**
 * Self-contained micromamba bootstrap.
 *
 * `spot` — the LTL backend's core dependency — is a compiled C++ library
 * published on conda-forge with no PyPI wheel, so a conda-family package manager
 * is the only realistic way to provision the backend. To make the extension work
 * out of the box for users who have no conda/mamba/micromamba on PATH, we
 * download a single static `micromamba` binary into the extension's managed
 * storage and use it to create the `pick-ltl` environment.
 *
 * micromamba is distributed as a directly-executable binary (no installer, no
 * archive to unpack) from the `mamba-org/micromamba-releases` GitHub releases,
 * each accompanied by a published SHA-256 checksum that we verify before use.
 */

import * as cp from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';

// Pinned release. Bump deliberately (and re-test) rather than tracking "latest",
// so a remote release can never silently change the binary we execute.
export const MICROMAMBA_VERSION = '2.8.1-0';

const RELEASE_BASE =
  `https://github.com/mamba-org/micromamba-releases/releases/download/${MICROMAMBA_VERSION}`;

export interface MicromambaInstall {
  /** Absolute path to the micromamba executable. */
  exe: string;
  /** Root prefix to pass as MAMBA_ROOT_PREFIX; envs live under `<rootPrefix>/envs`. */
  rootPrefix: string;
}

/**
 * Map Node's `process.platform`/`process.arch` to the micromamba release asset
 * name, or null if no prebuilt binary exists for this platform.
 */
export function micromambaAssetName(platform: NodeJS.Platform, arch: string): string | null {
  if (platform === 'darwin') {
    if (arch === 'arm64') { return 'micromamba-osx-arm64'; }
    if (arch === 'x64') { return 'micromamba-osx-64'; }
  } else if (platform === 'linux') {
    if (arch === 'x64') { return 'micromamba-linux-64'; }
    if (arch === 'arm64') { return 'micromamba-linux-aarch64'; }
    if (arch === 'ppc64') { return 'micromamba-linux-ppc64le'; }
  } else if (platform === 'win32') {
    if (arch === 'x64') { return 'micromamba-win-64.exe'; }
  }
  return null;
}

async function download(url: string): Promise<Buffer> {
  const resp = await fetch(url, { redirect: 'follow' });
  if (!resp.ok) {
    throw new Error(`GET ${url} → HTTP ${resp.status} ${resp.statusText}`);
  }
  return Buffer.from(await resp.arrayBuffer());
}

/** True if `exe` exists and answers `--version` (cheap sanity check). */
function isRunnable(exe: string): boolean {
  if (!fs.existsSync(exe)) {
    return false;
  }
  try {
    cp.execFileSync(exe, ['--version'], { stdio: 'ignore', timeout: 8000 });
    return true;
  } catch {
    return false;
  }
}

/**
 * Ensure a verified micromamba binary exists under `managedDir` and return its
 * location. Idempotent: a previously-downloaded, runnable binary is reused
 * without re-downloading.
 *
 * Throws on an unsupported platform, a network failure, or a checksum mismatch —
 * callers should fall back to manual setup instructions in that case.
 */
export async function ensureMicromamba(
  managedDir: string,
  log: (line: string) => void
): Promise<MicromambaInstall> {
  const asset = micromambaAssetName(process.platform, process.arch);
  if (!asset) {
    throw new Error(
      `No prebuilt micromamba is available for ${process.platform}/${process.arch}. ` +
        'Install conda/mamba/micromamba manually, or set "pick-ltl.backend.pythonPath".'
    );
  }

  const binDir = path.join(managedDir, 'bin');
  const exe = path.join(binDir, process.platform === 'win32' ? 'micromamba.exe' : 'micromamba');
  const rootPrefix = path.join(managedDir, 'root');

  if (isRunnable(exe)) {
    log(`Reusing micromamba at ${exe}.`);
    return { exe, rootPrefix };
  }

  fs.mkdirSync(binDir, { recursive: true });

  const binUrl = `${RELEASE_BASE}/${asset}`;
  log(`Downloading micromamba ${MICROMAMBA_VERSION} (${asset})…`);
  const [binary, checksumText] = await Promise.all([
    download(binUrl),
    download(`${binUrl}.sha256`).then((b) => b.toString('utf8'))
  ]);

  const expected = checksumText.trim().split(/\s+/)[0]?.toLowerCase();
  const actual = crypto.createHash('sha256').update(binary).digest('hex');
  if (!expected || expected !== actual) {
    throw new Error(
      `micromamba checksum mismatch (expected ${expected ?? 'none'}, got ${actual}). ` +
        'Refusing to use the download.'
    );
  }
  log(`Verified micromamba SHA-256 ${actual}.`);

  // Write to a temp path, mark executable, then rename into place so a partial
  // or interrupted download never leaves a "runnable-looking" binary behind.
  const tmp = `${exe}.download`;
  fs.writeFileSync(tmp, binary);
  fs.chmodSync(tmp, 0o755);
  fs.renameSync(tmp, exe);

  if (!isRunnable(exe)) {
    throw new Error(`Downloaded micromamba but "${exe} --version" did not run.`);
  }
  log(`micromamba ready at ${exe}.`);
  return { exe, rootPrefix };
}
