/**
 * Lifecycle manager for the vendored PICK-LTL Python backend.
 *
 * Responsibilities:
 *  - locate a suitable Python interpreter (one whose env has `spot`),
 *  - run a preflight to give precise "what's missing" diagnostics,
 *  - spawn the Flask app on a free localhost port,
 *  - wait until it answers, stream its logs, and tear it down on dispose.
 *
 * `spot` is not pip-installable, so the backend needs a conda-family
 * environment. When no conda/mamba/micromamba is on PATH the sidecar downloads
 * a private `micromamba` (see ./micromamba) and provisions the `pick-ltl` env
 * itself, so setup works with nothing preinstalled. Users may instead point
 * `pick-ltl.backend.pythonPath` at their own spot-enabled interpreter (or it is
 * auto-detected from a conda env named `pick-ltl`).
 */

import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as net from 'net';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { logger } from './logger';
import { ensureMicromamba } from './micromamba';

export type SidecarFailureKind =
  | 'python-missing'
  | 'deps-missing'
  | 'spot-missing'
  | 'boot-failed'
  | 'timeout';

export class SidecarError extends Error {
  kind: SidecarFailureKind;
  details?: string;
  constructor(kind: SidecarFailureKind, message: string, details?: string) {
    super(message);
    this.name = 'SidecarError';
    this.kind = kind;
    this.details = details;
  }
}

interface PreflightInfo {
  python: string;
  spot: boolean;
  flask: boolean;
  antlr4: boolean;
  requests: boolean;
  ok: boolean;
}

interface ProvisionManager {
  /** Executable path or PATH command name. */
  exe: string;
  /** Environment to invoke it with (carries MAMBA_ROOT_PREFIX when bootstrapped). */
  env: NodeJS.ProcessEnv;
  /** Human-readable label for logs. */
  label: string;
}

const ENV_NAME = 'pick-ltl';

export class PythonSidecar {
  private proc: cp.ChildProcess | null = null;
  private baseUrl: string | null = null;
  private startPromise: Promise<string> | null = null;
  private readonly pythonDir: string;
  private readonly configDir: string;
  private readonly managedDir: string;

  constructor(extensionUri: vscode.Uri, globalStorageUri: vscode.Uri) {
    this.pythonDir = vscode.Uri.joinPath(extensionUri, 'python').fsPath;
    this.configDir = vscode.Uri.joinPath(globalStorageUri, 'backend-config').fsPath;
    this.managedDir = vscode.Uri.joinPath(globalStorageUri, 'micromamba').fsPath;
  }

  getBaseUrl(): string | null {
    return this.baseUrl;
  }

  isRunning(): boolean {
    return this.proc !== null && this.baseUrl !== null;
  }

  /** Idempotent: returns the running base URL, starting the sidecar if needed. */
  async ensureStarted(): Promise<string> {
    if (this.baseUrl) {
      return this.baseUrl;
    }
    if (!this.startPromise) {
      this.startPromise = this.start().finally(() => {
        this.startPromise = null;
      });
    }
    return this.startPromise;
  }

  async restart(): Promise<string> {
    await this.stop();
    return this.ensureStarted();
  }

  /** First conda-family manager on PATH, or null. */
  private detectPathManager(): ProvisionManager | null {
    for (const manager of ['mamba', 'micromamba', 'conda']) {
      try {
        cp.execFileSync(manager, ['--version'], { stdio: 'ignore', timeout: 8000 });
        return { exe: manager, env: process.env, label: manager };
      } catch {
        /* not on PATH */
      }
    }
    return null;
  }

  /**
   * A usable conda-family manager: one from PATH if present, otherwise a private
   * micromamba downloaded into managed storage so setup works with nothing
   * preinstalled. Throws SidecarError('python-missing') only when neither is
   * available (e.g. offline, or an unsupported platform).
   */
  private async resolveProvisionManager(log: (line: string) => void): Promise<ProvisionManager> {
    const onPath = this.detectPathManager();
    if (onPath) {
      return onPath;
    }
    try {
      const mm = await ensureMicromamba(this.managedDir, log);
      return {
        exe: mm.exe,
        env: { ...process.env, MAMBA_ROOT_PREFIX: mm.rootPrefix },
        label: 'micromamba (downloaded)'
      };
    } catch (err) {
      throw new SidecarError(
        'python-missing',
        'No conda/mamba/micromamba found, and PICK could not download micromamba to set one up.',
        `${err instanceof Error ? err.message : String(err)}\n\n` +
          'Check your internet connection and run "PICK LTL: Set Up / Restart Backend" again, ' +
          'or install Miniforge (https://github.com/conda-forge/miniforge) and retry, ' +
          'or set "pick-ltl.backend.pythonPath" to a Python that has spot installed.'
      );
    }
  }

  /**
   * Create the `pick-ltl` conda env (spot from conda-forge + pip deps) and return
   * the new interpreter's absolute path. Uses a PATH manager when present,
   * otherwise a downloaded micromamba.
   */
  async provisionEnvironment(log: (line: string) => void): Promise<string> {
    const manager = await this.resolveProvisionManager(log);

    const requirements = path.join(this.pythonDir, 'requirements.txt');
    const run = (file: string, args: string[]): Promise<void> =>
      new Promise((resolve, reject) => {
        log(`$ ${file} ${args.join(' ')}`);
        const proc = cp.spawn(file, args, { env: manager.env });
        const pipe = (chunk: unknown) => {
          const text = String(chunk).replace(/\s+$/, '');
          if (text) {
            log(text);
          }
        };
        proc.stdout?.on('data', pipe);
        proc.stderr?.on('data', pipe);
        proc.on('error', reject);
        proc.on('exit', code =>
          code === 0 ? resolve() : reject(new Error(`\`${file} ${args[0]}\` exited with code ${code}`))
        );
      });

    log(`Creating conda environment "${ENV_NAME}" with ${manager.label} (this can take a few minutes)…`);
    await run(manager.exe, ['create', '-y', '-n', ENV_NAME, '-c', 'conda-forge', 'spot', 'python=3.12']);
    await run(manager.exe, ['run', '-n', ENV_NAME, 'python', '-m', 'pip', 'install', '-r', requirements]);

    const out = cp.execFileSync(
      manager.exe,
      ['run', '-n', ENV_NAME, 'python', '-c', 'import sys; print(sys.executable)'],
      { encoding: 'utf8', timeout: 20000, env: manager.env }
    );
    const pythonPath = out.trim().split('\n').filter(Boolean).pop() ?? '';
    if (!pythonPath) {
      throw new SidecarError('boot-failed', 'Created the environment but could not resolve its Python path.');
    }
    log(`Environment ready: ${pythonPath}`);
    return pythonPath;
  }

  private cfg<T>(key: string, dflt: T): T {
    return vscode.workspace.getConfiguration('pick-ltl').get<T>(key, dflt);
  }

  /** Candidate interpreters, most-specific first. */
  private resolvePythonCandidates(): string[] {
    const configured = this.cfg<string>('backend.pythonPath', '').trim();
    if (configured) {
      return [configured];
    }

    const home = os.homedir();
    const isWin = process.platform === 'win32';
    const condaRoots = ['miniconda3', 'anaconda3', 'miniforge3', 'mambaforge'];
    const candidates: string[] = [];

    const envPython = (root: string): string =>
      isWin
        ? path.join(root, 'envs', ENV_NAME, 'python.exe')
        : path.join(root, 'envs', ENV_NAME, 'bin', 'python');

    // A private micromamba env bootstrapped by provisionEnvironment, if present.
    candidates.push(envPython(path.join(this.managedDir, 'root')));

    // Active conda env (and its sibling `pick-ltl` env), if any.
    const condaPrefix = process.env.CONDA_PREFIX;
    if (condaPrefix) {
      const condaRoot = path.dirname(path.dirname(condaPrefix));
      candidates.push(envPython(condaRoot));
      candidates.push(isWin ? path.join(condaPrefix, 'python.exe') : path.join(condaPrefix, 'bin', 'python'));
    }

    for (const root of condaRoots) {
      candidates.push(envPython(path.join(home, root)));
    }

    candidates.push('python3', 'python');
    // De-dup while preserving order.
    return Array.from(new Set(candidates));
  }

  private runPreflight(pythonPath: string): PreflightInfo | null {
    const preflight = path.join(this.pythonDir, 'preflight.py');
    try {
      const out = cp.execFileSync(pythonPath, [preflight], {
        timeout: 20000,
        encoding: 'utf8',
        env: { ...process.env, PYTHONPATH: this.pythonDir, PYTHONDONTWRITEBYTECODE: '1' }
      });
      const line = out.trim().split('\n').filter(Boolean).pop() ?? '';
      return JSON.parse(line) as PreflightInfo;
    } catch (err) {
      logger.warn(
        `PICK LTL backend preflight failed for "${pythonPath}": ${err instanceof Error ? err.message : String(err)}`
      );
      return null;
    }
  }

  /** Pick a runnable interpreter, preferring one whose env has spot+deps. */
  private selectPython(): { python: string; info: PreflightInfo } {
    const candidates = this.resolvePythonCandidates();
    let firstRunnable: { python: string; info: PreflightInfo } | null = null;

    for (const candidate of candidates) {
      const info = this.runPreflight(candidate);
      if (!info) {
        continue;
      }
      if (info.ok) {
        return { python: candidate, info };
      }
      if (!firstRunnable) {
        firstRunnable = { python: candidate, info };
      }
    }

    if (firstRunnable) {
      return firstRunnable; // runnable, but missing deps — caller raises a precise error
    }

    throw new SidecarError(
      'python-missing',
      'Could not find a Python interpreter for the PICK LTL backend.',
      `Tried: ${candidates.join(', ')}. Set "pick-ltl.backend.pythonPath" to a Python that has spot installed ` +
        `(conda create -n ${ENV_NAME} python=3.12 && conda install -n ${ENV_NAME} -c conda-forge spot).`
    );
  }

  private findFreePort(preferred: number): Promise<number> {
    if (preferred && preferred > 0) {
      return Promise.resolve(preferred);
    }
    return new Promise<number>((resolve, reject) => {
      const srv = net.createServer();
      srv.on('error', reject);
      srv.listen(0, '127.0.0.1', () => {
        const addr = srv.address();
        const port = typeof addr === 'object' && addr ? addr.port : 0;
        srv.close(() => (port ? resolve(port) : reject(new Error('Could not allocate a port'))));
      });
    });
  }

  private async start(): Promise<string> {
    fs.mkdirSync(this.configDir, { recursive: true });

    const { python, info } = this.selectPython();
    logger.info(`PICK LTL backend: Python ${info.python} at "${python}" (spot=${info.spot}).`);

    if (!info.ok) {
      const missing: string[] = [];
      if (!info.flask) {
        missing.push('flask');
      }
      if (!info.antlr4) {
        missing.push('antlr4-python3-runtime');
      }
      if (!info.requests) {
        missing.push('requests');
      }
      if (!info.spot) {
        missing.push('spot (conda install -c conda-forge spot)');
      }
      throw new SidecarError(
        info.spot ? 'deps-missing' : 'spot-missing',
        `The PICK LTL backend environment is missing: ${missing.join(', ')}.`,
        `Interpreter: ${python}. Install the missing packages, then run "PICK LTL: Set Up / Restart Backend".`
      );
    }

    const host = '127.0.0.1';
    const port = await this.findFreePort(this.cfg<number>('backend.port', 0));

    const args = [
      '-m',
      'flask',
      '--app',
      'pick_ltl.app',
      'run',
      '--host',
      host,
      '--port',
      String(port),
      '--no-reload'
    ];
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      PYTHONPATH: this.pythonDir,
      PYTHONUNBUFFERED: '1',
      PYTHONDONTWRITEBYTECODE: '1',
      PICK_LTL_CONFIG_DIR: this.configDir,
      FLASK_RUN_PORT: String(port)
    };

    logger.info(`Spawning PICK LTL backend: "${python}" ${args.join(' ')} (cwd=${this.pythonDir}).`);
    const proc = cp.spawn(python, args, { cwd: this.pythonDir, env });
    this.proc = proc;

    const pipe = (chunk: unknown) => {
      const text = String(chunk).replace(/\s+$/, '');
      if (text) {
        logger.info(`[backend] ${text}`);
      }
    };
    proc.stdout?.on('data', pipe);
    proc.stderr?.on('data', pipe);
    proc.on('error', (err) => logger.error(err, 'PICK LTL backend process error'));
    proc.on('exit', (code, signal) => {
      logger.warn(`PICK LTL backend exited (code=${code}, signal=${signal}).`);
      if (this.proc === proc) {
        this.proc = null;
        this.baseUrl = null;
      }
    });

    const baseUrl = `http://${host}:${port}`;
    await this.waitForReady(baseUrl, proc);
    this.baseUrl = baseUrl;
    logger.info(`PICK LTL backend ready at ${baseUrl}.`);
    return baseUrl;
  }

  private async waitForReady(baseUrl: string, proc: cp.ChildProcess, timeoutMs = 30000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (proc.exitCode !== null || proc.signalCode !== null) {
        throw new SidecarError(
          'boot-failed',
          'The PICK LTL backend exited during startup. Check the "PICK LTL Builder" output log.'
        );
      }
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 1500);
        const resp = await fetch(`${baseUrl}/api/settings`, { signal: controller.signal });
        clearTimeout(timer);
        if (resp.ok) {
          return;
        }
      } catch {
        /* not up yet */
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    throw new SidecarError('timeout', 'Timed out waiting for the PICK LTL backend to start.');
  }

  async stop(): Promise<void> {
    const proc = this.proc;
    this.proc = null;
    this.baseUrl = null;
    this.startPromise = null;
    if (!proc || proc.exitCode !== null) {
      return;
    }
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      proc.once('exit', finish);
      try {
        proc.kill('SIGTERM');
      } catch {
        /* already gone */
      }
      setTimeout(() => {
        try {
          if (proc.exitCode === null) {
            proc.kill('SIGKILL');
          }
        } catch {
          /* ignore */
        }
        finish();
      }, 3000);
    });
  }

  dispose(): void {
    void this.stop();
  }
}
