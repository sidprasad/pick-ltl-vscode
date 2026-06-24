#!/usr/bin/env node
/**
 * End-to-end smoke test for the out-of-the-box backend bootstrap.
 *
 * Simulates a machine with NO conda: it downloads a fresh micromamba and uses it
 * to provision the `pick-ltl` environment into an ISOLATED root prefix, so it
 * never touches any conda/env you already have. Mirrors the real flow in
 * src/sidecar.ts (PythonSidecar.provisionEnvironment + start):
 *
 *   download micromamba -> create env (spot from conda-forge) -> pip install
 *   -> preflight (import spot + deps) -> boot Flask -> GET /api/settings
 *
 * Usage:
 *   npm run compile                       # produces out/micromamba.js
 *   node util/smoke-backend.cjs           # ephemeral prefix, cleaned on success
 *   node util/smoke-backend.cjs --dir .tmp/oob   # reuse a prefix (fast re-runs)
 *   node util/smoke-backend.cjs --keep    # leave the temp prefix for inspection
 *
 * First run downloads ~500 MB (spot + python + deps) and takes a few minutes.
 */
'use strict';
const path = require('path');
const os = require('os');
const fs = require('fs');
const cp = require('child_process');
const net = require('net');

const repoRoot = path.resolve(__dirname, '..');
const pythonDir = path.join(repoRoot, 'python');
const mmModule = path.join(repoRoot, 'out', 'micromamba.js');
if (!fs.existsSync(mmModule)) {
  console.error('Missing out/micromamba.js — run `npm run compile` first.');
  process.exit(1);
}
const { ensureMicromamba } = require(mmModule);

const argv = process.argv.slice(2);
const keep = argv.includes('--keep');
const dirArg = argv.includes('--dir') ? argv[argv.indexOf('--dir') + 1] : null;

const freePort = () =>
  new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });

const run = (file, args, env) => {
  console.log(`$ ${path.basename(file)} ${args.join(' ')}`);
  const r = cp.spawnSync(file, args, { stdio: 'inherit', env });
  if (r.status !== 0) {
    throw new Error(`\`${path.basename(file)} ${args[0]}\` exited with ${r.status}`);
  }
};

(async () => {
  const dir = dirArg || fs.mkdtempSync(path.join(os.tmpdir(), 'pickltl-oob-'));
  fs.mkdirSync(dir, { recursive: true });
  console.log(`Isolated prefix: ${dir}\n`);

  // 1) Download + verify micromamba (the part the OOB user hits first).
  const { exe, rootPrefix } = await ensureMicromamba(path.join(dir, 'micromamba'), (l) =>
    console.log('  ' + l)
  );
  const env = { ...process.env, MAMBA_ROOT_PREFIX: rootPrefix, PYTHONDONTWRITEBYTECODE: '1' };

  // 2) Create the env with spot (slow), then 3) install pip deps.
  run(exe, ['create', '-y', '-n', 'pick-ltl', '-c', 'conda-forge', 'spot', 'python=3.12'], env);
  run(
    exe,
    ['run', '-n', 'pick-ltl', 'python', '-m', 'pip', 'install', '-r', path.join(pythonDir, 'requirements.txt')],
    env
  );

  // 4) Preflight: confirms spot + flask + antlr4 + requests all import.
  run(exe, ['run', '-n', 'pick-ltl', 'python', path.join(pythonDir, 'preflight.py')], {
    ...env,
    PYTHONPATH: pythonDir
  });

  // 5) Boot Flask and probe /api/settings (mirrors PythonSidecar.start/waitForReady).
  const port = await freePort();
  console.log(`\nBooting backend on 127.0.0.1:${port} …`);
  const proc = cp.spawn(
    exe,
    // prettier-ignore
    ['run', '-n', 'pick-ltl', 'python', '-m', 'flask', '--app', 'pick_ltl.app',
     'run', '--host', '127.0.0.1', '--port', String(port), '--no-reload'],
    { cwd: pythonDir, env: { ...env, PYTHONPATH: pythonDir, PYTHONUNBUFFERED: '1' } }
  );
  proc.stdout.on('data', (d) => process.stdout.write('[backend] ' + d));
  proc.stderr.on('data', (d) => process.stdout.write('[backend] ' + d));

  let ok = false;
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline && proc.exitCode === null) {
    try {
      const resp = await fetch(`http://127.0.0.1:${port}/api/settings`);
      if (resp.ok) {
        ok = true;
        break;
      }
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  proc.kill('SIGTERM');

  if (!ok) {
    throw new Error('backend did not answer GET /api/settings within 30s');
  }
  console.log('\nPASS: micromamba bootstrap → spot env → Flask /api/settings all OK.');

  if (keep || dirArg) {
    console.log(`Left prefix in place: ${dir}`);
  } else {
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(`Cleaned ${dir}`);
  }
})().catch((e) => {
  console.error(`\nFAIL: ${e && e.message ? e.message : e}`);
  process.exit(1);
});
