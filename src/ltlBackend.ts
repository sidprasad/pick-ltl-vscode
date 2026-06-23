/**
 * Typed HTTP client for the vendored PICK-LTL Python backend (Flask app in
 * `python/pick_ltl`). The backend is *stateless*: every endpoint takes the
 * session JSON in the request body and returns the full, updated SessionState.
 * The extension owns the session object and threads it through each call.
 *
 * Mirrors the dataclasses in python/pick_ltl/session/models.py.
 */

export interface AtomSpec {
  name: string;
  meaning: string;
}

export interface SeedFormulaResult {
  formula: string;
  explanation: string;
  atoms: AtomSpec[];
  warnings: string[];
}

/** Response shape of POST /api/seed/generate (primary seed + all seeds). */
export interface SeedGenerationResult extends SeedFormulaResult {
  seeds: SeedFormulaResult[];
}

export interface CandidateOrigin {
  /** "seed" | "semantic_mutation" | "syntactic_mutation" | ... */
  kind: string;
  /** Misconception code when kind === "semantic_mutation". */
  misconception_code: string | null;
}

export interface CandidateFormulaState {
  formula: string;
  explanation: string;
  origin: CandidateOrigin;
  confidence: number | null;
  equivalents: string[];
  positive_votes: number;
  negative_votes: number;
  elimination_threshold: number;
  eliminated: boolean;
}

export interface TracePair {
  trace1: string;
  trace2: string;
  matches1: string[];
  matches2: string[];
}

export interface TraceClassification {
  trace: string;
  classification: string;
  matching_candidates: string[];
  source: string;
  timestamp: number;
}

export interface FinalResult {
  title: string;
  formula: string | null;
  explanation: string;
  english: string;
  examples_in: string[];
  examples_out: string[];
  message: string;
}

export type SessionMode =
  | 'prompt'
  | 'voting'
  | 'single_candidate'
  | 'final_result'
  | 'no_result'
  | string;

export interface SessionState {
  version: number;
  prompt: string;
  provider: Record<string, unknown>;
  seed: SeedFormulaResult | null;
  seeds: SeedFormulaResult[];
  candidate_states: CandidateFormulaState[];
  history: TraceClassification[];
  mode: SessionMode;
  warnings: string[];
  current_pair: TracePair | null;
  final_result: FinalResult | null;
  exhausted: boolean;
  message: string;
}

export interface ProviderConfig {
  kind: string;
  base_url: string;
  model: string;
  api_key?: string;
  timeout_seconds?: number;
}

/** Thrown when the sidecar is not reachable (not started / crashed / wrong URL). */
export class BackendUnavailableError extends Error {
  constructor(message = 'The PICK LTL backend is not running.') {
    super(message);
    this.name = 'BackendUnavailableError';
  }
}

/** Thrown when the backend responds with a non-2xx status. */
export class BackendRequestError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'BackendRequestError';
    this.status = status;
  }
}

export class LtlBackend {
  /** baseUrl is resolved lazily so the client survives sidecar restarts. */
  constructor(private readonly getBaseUrl: () => string | null) {}

  private async request<T>(
    path: string,
    body?: unknown,
    method: 'GET' | 'POST' = 'POST',
    timeoutMs = 120000
  ): Promise<T> {
    const base = this.getBaseUrl();
    if (!base) {
      throw new BackendUnavailableError();
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let resp: Response;
    try {
      resp = await fetch(`${base}${path}`, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
        signal: controller.signal
      });
    } catch (err) {
      throw new BackendUnavailableError(
        `Could not reach the PICK LTL backend at ${base}: ${err instanceof Error ? err.message : String(err)}`
      );
    } finally {
      clearTimeout(timer);
    }

    const text = await resp.text();
    let data: unknown = undefined;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        /* leave data undefined for non-JSON bodies */
      }
    }

    if (!resp.ok) {
      const message =
        data && typeof (data as { error?: unknown }).error === 'string'
          ? (data as { error: string }).error
          : `Backend error (HTTP ${resp.status}).`;
      throw new BackendRequestError(message, resp.status);
    }

    return data as T;
  }

  /** Fast readiness probe: GET /api/settings returns JSON and needs no spot. */
  async ping(timeoutMs = 1500): Promise<boolean> {
    try {
      await this.request('/api/settings', undefined, 'GET', timeoutMs);
      return true;
    } catch {
      return false;
    }
  }

  generateSeed(prompt: string, provider?: ProviderConfig): Promise<SeedGenerationResult> {
    return this.request('/api/seed/generate', { prompt, provider });
  }

  /**
   * Expand seeds into the candidate pool via misconception + syntactic mutation
   * (this is where the SPOT-backed work begins). Returns the initial session,
   * including the first distinguishing pair when one exists.
   */
  buildCandidates(args: {
    prompt: string;
    provider?: ProviderConfig;
    seeds?: SeedFormulaResult[];
    seed?: SeedFormulaResult;
    regenerate_seed?: boolean;
  }): Promise<SessionState> {
    return this.request('/api/candidates/build', args);
  }

  nextPair(session: SessionState): Promise<SessionState> {
    return this.request('/api/session/next-pair', { session });
  }

  classify(
    session: SessionState,
    trace: string,
    classification: 'accept' | 'reject' | 'unsure' | string,
    source: 'pair' | 'direct' = 'pair'
  ): Promise<SessionState> {
    return this.request('/api/session/classify', { session, trace, classification, source });
  }

  reclassify(session: SessionState, historyIndex: number, classification: string): Promise<SessionState> {
    return this.request('/api/session/reclassify', {
      session,
      history_index: historyIndex,
      classification
    });
  }

  refine(session: SessionState, prompt: string): Promise<SessionState> {
    return this.request('/api/session/refine', { session, prompt });
  }

  addExamples(session: SessionState, acceptTraces: string[], rejectTraces: string[]): Promise<SessionState> {
    return this.request('/api/session/examples', {
      session,
      accept_traces: acceptTraces,
      reject_traces: rejectTraces
    });
  }

  finalize(session: SessionState, formula?: string | null): Promise<SessionState> {
    return this.request('/api/session/finalize', { session, formula: formula ?? null });
  }

  importSession(session: SessionState): Promise<SessionState> {
    return this.request('/api/session/import', { session });
  }

  async listModels(provider?: ProviderConfig): Promise<string[]> {
    const r = await this.request<{ models: string[] }>(
      '/api/models',
      provider,
      provider ? 'POST' : 'GET'
    );
    return r.models ?? [];
  }

  testConnection(provider: ProviderConfig): Promise<unknown> {
    return this.request('/api/settings/test', provider);
  }
}
