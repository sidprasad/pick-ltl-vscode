import { logger } from './logger';

/**
 * Engine bridge to @sidprasad/ltl-ts (pure-TS LTL engine), the drop-in
 * replacement for the formula extension's @gruhn/formula-utils bridge.
 *
 * Method names mirror the old FormulaAnalyzer so the PICK controller changes
 * minimally, but "word" now means a Spot lasso trace string and "formula" an LTL
 * formula string.
 *
 * The engine is ESM; we load it once via dynamic import and cache it so that
 * membership checks (verifyMatch) can stay synchronous — the controller calls
 * them inside synchronous vote loops.
 */

interface LtlTrace {
  toString(): string;
}

/**
 * Minimal hand-written surface of the @sidprasad/ltl-ts ESM module. We type it
 * by hand (rather than `typeof import(...)`) because a type-position import of an
 * ESM module from this CommonJS extension would require a resolution-mode
 * attribute; the runtime dynamic `import()` (value position) is fine.
 */
interface LtlModule {
  parseFormula(formula: string): unknown;
  satisfies(trace: string, formula: string): boolean;
  areEquivalent(a: string, b: string): boolean;
  isSufficientFor(a: string, b: string): boolean;
  getSatisfyingTrace(formula: string, excludedTraces?: string[]): LtlTrace;
  getTwoDistinguishingWords(candidates: string[], excludedWords?: string[]): [LtlTrace, LtlTrace];
  generateFormula(atoms: string[], satisfyingTraces: string[], notSatisfyingTraces: string[]): string;
  NoSatisfyingTraceError: new (...args: unknown[]) => Error;
  Trace: { parse(s: string): LtlTrace };
  traceToRenderData(trace: LtlTrace): RenderData;
}

/** Shape consumed by the SVG trace renderer (viz/tracerenderer.js). */
export interface RenderData {
  prefix: Array<{ label: string }>;
  cycle: Array<{ label: string }>;
}

let cachedModule: LtlModule | null = null;
async function loadLtl(): Promise<LtlModule> {
  if (!cachedModule) {
    // Bare specifier kept opaque to the type system; cast the value to our surface.
    const spec = '@sidprasad/ltl-ts';
    cachedModule = (await import(spec)) as unknown as LtlModule;
  }
  return cachedModule;
}

export interface TracePairResult {
  wordIn: string;
  wordNotIn: string;
  explanation?: string;
}

export interface TwoDistinguishingTracesResult {
  words: [string, string];
  explanation: string;
  properties?: string[];
}

export class LtlAnalyzer {
  private ltl: LtlModule | null = null;

  constructor() {
    // Kick off the load eagerly; init() awaits completion.
    void loadLtl().then(m => { this.ltl = m; }).catch(() => { /* surfaced in init() */ });
  }

  /** Must be awaited before any synchronous verifyMatch calls. */
  async init(): Promise<void> {
    this.ltl = await loadLtl();
  }

  private mod(): LtlModule {
    if (!this.ltl) {
      throw new Error('LtlAnalyzer used before init() — call and await analyzer.init() first');
    }
    return this.ltl;
  }

  /** Is this a syntactically valid LTL formula? */
  isValidFormula(formula: string): boolean {
    try {
      this.mod().parseFormula(formula);
      return true;
    } catch {
      return false;
    }
  }

  /** Async alias of isValidFormula (the engine supports the full grammar). */
  async hasSupportedSyntax(formula: string): Promise<boolean> {
    try {
      const { parseFormula } = await loadLtl();
      parseFormula(formula);
      return true;
    } catch {
      return false;
    }
  }

  /** Does `trace` satisfy `formula`? (synchronous; requires init()) */
  verifyMatch(trace: string, formula: string): boolean {
    try {
      return this.mod().satisfies(trace, formula);
    } catch (error) {
      logger.warn(`verifyMatch failed for trace='${trace}' formula='${formula}': ${error}`);
      return false;
    }
  }

  /** Are two formulas logically equivalent? */
  async areEquivalent(formulaA: string, formulaB: string): Promise<boolean> {
    try {
      const { areEquivalent } = await loadLtl();
      return areEquivalent(formulaA, formulaB);
    } catch (error) {
      logger.warn(`areEquivalent failed for '${formulaA}' vs '${formulaB}': ${error}`);
      return false;
    }
  }

  /**
   * Distinguishability proxy (replaces formula set-difference cardinality).
   * Returns 1n if some trace satisfies A but not B (A ⊄ B), else 0n.
   * Used by the controller's threshold heuristic, which sums these over peers.
   */
  async countTracesInANotInB(formulaA: string, formulaB: string): Promise<bigint | undefined> {
    try {
      const { isSufficientFor } = await loadLtl();
      // |A \ B| > 0  iff  A does NOT imply B
      return isSufficientFor(formulaA, formulaB) ? 0n : 1n;
    } catch (error) {
      logger.warn(`countTracesInANotInB failed for '${formulaA}' \\ '${formulaB}': ${error}`);
      return undefined;
    }
  }

  /** Generate one trace that satisfies the formula and one that does not. */
  async generateTracePair(formula: string, excludedWords: string[] = []): Promise<TracePairResult> {
    const { getSatisfyingTrace, NoSatisfyingTraceError } = await loadLtl();

    let wordIn = '';
    try {
      wordIn = getSatisfyingTrace(formula, excludedWords).toString();
    } catch (error) {
      if (error instanceof NoSatisfyingTraceError) {
        throw new Error(`Formula is unsatisfiable: '${formula}'`);
      }
      throw error;
    }

    let wordNotIn = '';
    let isTautology = false;
    try {
      wordNotIn = getSatisfyingTrace(`!(${formula})`, [...excludedWords, wordIn]).toString();
    } catch (error) {
      if (error instanceof NoSatisfyingTraceError) {
        // Formula is a tautology — no violating trace exists.
        wordNotIn = wordIn;
        isTautology = true;
      } else {
        throw error;
      }
    }

    const explanation = isTautology
      ? `'${wordIn}' satisfies; no counterexample exists (formula is a tautology)`
      : `'${wordIn}' satisfies, '${wordNotIn}' does not`;
    return { wordIn, wordNotIn, explanation };
  }

  /** Generate multiple distinct traces satisfying the formula. */
  async generateMultipleTraces(
    formula: string,
    count: number,
    excludedWords: string[] = []
  ): Promise<string[]> {
    const { getSatisfyingTrace, NoSatisfyingTraceError } = await loadLtl();
    const excluded = [...excludedWords];
    const words: string[] = [];
    while (words.length < count) {
      try {
        const t = getSatisfyingTrace(formula, excluded).toString();
        words.push(t);
        excluded.push(t);
      } catch (error) {
        if (error instanceof NoSatisfyingTraceError) {
          break; // no more distinct satisfying traces
        }
        throw error;
      }
    }
    return words;
  }

  /**
   * Two traces that best split a set of candidate formulas. The engine performs
   * the pairwise selection internally; there is no timeout/poolSize.
   * (Extra params kept for signature compatibility with the old analyzer.)
   */
  async generateTwoDistinguishingTraces(
    candidateFormulas: string[],
    excludedWords: string[] = [],
    _timeoutMs?: number,
    _poolSizeLimit?: number
  ): Promise<TwoDistinguishingTracesResult> {
    if (candidateFormulas.length === 0) {
      throw new Error('Need at least one candidate formula');
    }
    const { getTwoDistinguishingWords } = await loadLtl();
    const [t1, t2] = getTwoDistinguishingWords(candidateFormulas, excludedWords);
    return {
      words: [t1.toString(), t2.toString()],
      explanation: `Traces selected to split ${candidateFormulas.length} candidate(s)`,
      properties: ['Distinguishing trace 1', 'Distinguishing trace 2']
    };
  }

  /**
   * Synthesize a formula from classified traces (no formula analogue).
   * Returns null if no consistent formula is found within the engine's bound.
   */
  async synthesizeFormula(
    atoms: string[],
    satisfyingTraces: string[],
    notSatisfyingTraces: string[]
  ): Promise<string | null> {
    try {
      const { generateFormula } = await loadLtl();
      return generateFormula(atoms, satisfyingTraces, notSatisfyingTraces);
    } catch (error) {
      logger.warn(`synthesizeFormula found no consistent formula: ${error}`);
      return null;
    }
  }

  /**
   * Convert a Spot lasso trace string into render data for the SVG renderer
   * (viz/tracerenderer.js). Returns null if the trace cannot be parsed.
   */
  async renderData(traceString: string): Promise<RenderData | null> {
    try {
      const { Trace, traceToRenderData } = await loadLtl();
      return traceToRenderData(Trace.parse(traceString));
    } catch (error) {
      logger.warn(`renderData failed for trace '${traceString}': ${error}`);
      return null;
    }
  }
}

/** Create analyzer instance. */
export function createLtlAnalyzer(): LtlAnalyzer {
  return new LtlAnalyzer();
}
