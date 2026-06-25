import * as vscode from 'vscode';
import { logger } from './logger';

export interface LtlAtom {
  name: string;
  meaning?: string;
}

export interface LtlCandidate {
  formula: string;
  explanation: string;
  confidence?: number;
}

export interface LtlGenerationResult {
  atoms?: LtlAtom[];
  candidates: LtlCandidate[];
  warnings?: string[];
}

export interface LtlGenerationOptions {
  /**
   * Example traces (Spot lasso format) that SHOULD satisfy the intended property.
   * Used as lightweight grounding context for the LLM.
   */
  positiveExamples?: string[];
}

/**
 * Represents an available LLM chat model
 */
export interface AvailableChatModel {
  id: string;
  name: string;
  vendor: string;
  family: string;
}

/**
 * Error thrown when user has not granted permission to use language models
 */
export class PermissionRequiredError extends Error {
  constructor(message: string = 'Permission required to use language models. Please approve the permission request when prompted.') {
    super(message);
    this.name = 'PermissionRequiredError';
  }
}

/**
 * Error thrown when no language models are available
 */
export class NoModelsAvailableError extends Error {
  constructor(message: string = 'No language models available. Please ensure you have a language model extension installed (e.g., GitHub Copilot).') {
    super(message);
    this.name = 'NoModelsAvailableError';
  }
}

/**
 * Error thrown when the selected model is not supported by the backend
 */
export class ModelNotSupportedError extends Error {
  constructor(modelName: string) {
    super(`The model "${modelName}" is not currently supported. This could mean:\n\n• The model doesn't exist or has been deprecated\n• The model requires a subscription you don't have\n• The model may require additional workspace permissions or account setup\n\nPlease try selecting a different model from the dropdown.`);
    this.name = 'ModelNotSupportedError';
  }
}

/**
 * Error thrown when a model is listed but not enabled/accessible in this workspace
 */
export class ModelNotEnabledError extends Error {
  constructor(modelName: string, details?: string) {
    super(
      `The model "${modelName}" appears in your list but is not currently enabled for this workspace.\n\n` +
      `${details || 'This may require additional setup or permissions.'}\n\n` +
      `What you can do:\n` +
      `• Check if the model requires workspace-specific permissions\n` +
      `• Verify you're signed in to the correct account\n` +
      `• Try selecting a different model from the dropdown`
    );
    this.name = 'ModelNotEnabledError';
  }
}

/**
 * Get all available chat models from VS Code
 */
export async function getAvailableChatModels(): Promise<AvailableChatModel[]> {
  try {
    const models = await vscode.lm.selectChatModels({});
    const uniqueModels = new Map<string, AvailableChatModel>();
    models.forEach(model => {
      if (!uniqueModels.has(model.id)) {
        uniqueModels.set(model.id, {
          id: model.id,
          name: model.name,
          vendor: model.vendor,
          family: model.family
        });
      }
    });
    return Array.from(uniqueModels.values());
  } catch (error) {
    logger.warn(`Failed to get available chat models: ${error}`);
    return [];
  }
}

/**
 * Get unique vendors from available models
 */
export async function getAvailableVendors(): Promise<string[]> {
  const models = await getAvailableChatModels();
  const vendors = new Set(models.map(m => m.vendor));
  return Array.from(vendors).sort();
}

/**
 * Get unique model families from available models, optionally filtered by vendor
 */
export async function getAvailableFamilies(vendor?: string): Promise<string[]> {
  const models = await getAvailableChatModels();
  const filtered = vendor ? models.filter(m => m.vendor === vendor) : models;
  const families = new Set(filtered.map(m => m.family));
  return Array.from(families).sort();
}

function sanitizeAtoms(rawAtoms: unknown): LtlAtom[] {
  if (!Array.isArray(rawAtoms)) {
    return [];
  }
  const out: LtlAtom[] = [];
  for (const a of rawAtoms) {
    if (a && typeof a === 'object' && typeof (a as any).name === 'string') {
      const name = (a as any).name.trim();
      if (/^[a-z0-9]+$/.test(name)) {
        out.push({ name, meaning: typeof (a as any).meaning === 'string' ? (a as any).meaning : undefined });
      }
    } else if (typeof a === 'string' && /^[a-z0-9]+$/.test(a.trim())) {
      out.push({ name: a.trim() });
    }
  }
  // dedupe by name
  const seen = new Set<string>();
  return out.filter(a => (seen.has(a.name) ? false : (seen.add(a.name), true)));
}

export function sanitizeWarnings(rawWarnings: unknown): string[] {
  if (!Array.isArray(rawWarnings)) {
    return [];
  }
  const normalized = rawWarnings
    .filter(candidate => typeof candidate === 'string')
    .map(candidate => candidate.trim())
    .filter(candidate => candidate.length > 0)
    .map(candidate => candidate.slice(0, 240));
  return Array.from(new Set(normalized)).slice(0, 3);
}

export async function generateLtlFromDescription(
  description: string,
  token: vscode.CancellationToken,
  modelId?: string,
  options: LtlGenerationOptions = {}
): Promise<LtlGenerationResult> {
  logger.info(`User prompt: ${description}`);

  const models = await vscode.lm.selectChatModels({});
  if (models.length === 0) {
    throw new NoModelsAvailableError();
  }

  let model = models[0];
  if (modelId) {
    const selectedModel = models.find(m => m.id === modelId);
    if (selectedModel) {
      model = selectedModel;
    } else {
      logger.warn(`Requested model "${modelId}" not found, using default: ${model.name}`);
    }
  }
  logger.info(`Using model: ${model.name} (vendor: ${model.vendor}, family: ${model.family})`);

  const positiveExamples = (options.positiveExamples ?? [])
    .map(example => example.trim())
    .filter(example => example.length > 0);
  const exampleLines = positiveExamples.length > 0
    ? [
        '',
        'Example traces (Spot lasso format) that SHOULD satisfy the property:',
        ...positiveExamples.map(example => `- ${example}`)
      ]
    : [];

  const messages: vscode.LanguageModelChatMessage[] = [
    vscode.LanguageModelChatMessage.User(
    [
      "You are an assistant that formalizes natural-language temporal properties as Linear Temporal Logic (LTL) formulas.",
      "Given a description of how a system should behave over time, produce 3–5 candidate LTL formulas capturing different reasonable interpretations.",
      "Return ONLY a single JSON object with this shape:",
      "{",
      "  \"atoms\": [ {\"name\": \"<atom>\", \"meaning\": \"<english meaning>\"} ],",
      "  \"candidates\": [",
      "    {\"formula\": \"<LTL>\", \"explanation\": \"<why this interpretation>\", \"confidence\": 0.0}",
      "  ],",
      "  // warnings: [\"<caution>\"]   // optional",
      "}",
      "",
      "LTL syntax rules (STRICT):",
      "- Operators ONLY: ! (not), X (next), F (eventually), G (globally), & (and), | (or), U (until), -> (implies), <-> (iff), and parentheses.",
      "- Do NOT use R, W, M, xor, or the word forms ALWAYS/EVENTUALLY/NEXT_STATE/AFTER/UNTIL — use the symbols above only.",
      "- Atoms (propositions) must match [a-z0-9]+ (lowercase letters/digits, e.g. 'a', 'req', 'grant1').",
      "- Every atom used in a formula MUST be declared in \"atoms\".",
      "",
      "Output rules:",
      "- Output must be valid JSON. No backticks, comments, or extra prose.",
      "- \"candidates\" must contain 3–5 items, diverse in meaning (e.g. safety vs liveness, scope of G/F, strict vs non-strict).",
      "- Each candidate: formula (LTL string using only the allowed syntax), explanation, confidence in [0,1].",
      "- Do NOT include example traces or any trace data — traces are generated formally by the engine, never by you.",
      "- Add warnings (max 2–3, short) if the description is not expressible in LTL (e.g. counting, real-time bounds, data values).",
      "",
      `Description: ${description}`,
      ...exampleLines,
    ].join('\n')
    )
  ];

  let response;
  try {
    response = await model.sendRequest(messages, {}, token);
  } catch (error: unknown) {
    logger.info(`Caught error in ltlService: ${error?.constructor?.name}, message: ${error instanceof Error ? error.message : String(error)}`);

    if (error instanceof vscode.LanguageModelError) {
      const errorCode = error.code;
      const errorMsg = error.message.toLowerCase();
      logger.error(error, `Language model error - code: ${errorCode}, message: ${error.message}`);

      if (errorCode === 'NoPermissions' ||
          errorCode === 'Blocked' ||
          errorMsg.includes('permission') ||
          errorMsg.includes('not allowed')) {
        throw new PermissionRequiredError(
          'You must grant permission for PICK to use language models. ' +
          'A permission dialog should appear - please click "Allow" to continue. ' +
          'If no dialog appears, you may need to sign in to your language model provider.'
        );
      }

      if (errorMsg.includes('not available') ||
          errorMsg.includes('not enabled') ||
          errorMsg.includes('not accessible') ||
          errorMsg.includes('not active')) {
        throw new ModelNotEnabledError(
          model.name,
          'The model may require additional workspace permissions or account setup.'
        );
      }

      if (errorMsg.includes('not found') || errorMsg.includes('does not exist')) {
        throw new ModelNotSupportedError(model.name);
      }
    }

    const errorMessage = error instanceof Error ? error.message : String(error);
    if (errorMessage.includes('model_not_supported') ||
        errorMessage.toLowerCase().includes('model is not supported') ||
        errorMessage.toLowerCase().includes('requested model is not supported')) {
      logger.error(error, `Model not supported by backend: ${model.name}`);
      throw new ModelNotSupportedError(model.name);
    }

    logger.error(error, `Unexpected error during model.sendRequest for ${model.name}`);
    throw error;
  }

  let fullText = '';
  try {
    for await (const chunk of response.stream) {
      if (chunk instanceof vscode.LanguageModelTextPart) {
        fullText += chunk.value;
      }
    }
  } catch (error: unknown) {
    logger.info(`Caught error during stream iteration: ${error?.constructor?.name}`);
    const errorMessage = error instanceof Error ? error.message : String(error);
    if (errorMessage.includes('model_not_supported') ||
        errorMessage.toLowerCase().includes('model is not supported') ||
        errorMessage.toLowerCase().includes('requested model is not supported')) {
      logger.error(error, `Model not supported by backend (during streaming): ${model.name}`);
      throw new ModelNotSupportedError(model.name);
    }
    if (errorMessage.toLowerCase().includes('not available') ||
        errorMessage.toLowerCase().includes('not enabled') ||
        errorMessage.toLowerCase().includes('not accessible') ||
        errorMessage.toLowerCase().includes('not active')) {
      throw new ModelNotEnabledError(
        model.name,
        'The model may require additional workspace permissions or account setup.'
      );
    }
    logger.error(error, `Unexpected error during stream iteration for ${model.name}`);
    throw error;
  }

  // Defensive JSON extraction
  const jsonMatch = fullText.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    throw new Error('Model did not return JSON.');
  }

  const parsed = JSON.parse(jsonMatch[0]);
  const warnings = sanitizeWarnings(parsed.warnings);
  const atoms = sanitizeAtoms(parsed.atoms);
  const declaredAtoms = new Set(atoms.map(a => a.name));

  if (!Array.isArray(parsed.candidates)) {
    throw new Error('Model JSON missing `candidates` array.');
  }

  // Shape + basic field validation
  const shaped: LtlCandidate[] = parsed.candidates
    .filter((c: any) => typeof c.formula === 'string' && c.formula.trim().length > 0)
    .map((c: any) => ({
      formula: c.formula.trim(),
      explanation: typeof c.explanation === 'string' ? c.explanation : '',
      confidence: typeof c.confidence === 'number' ? c.confidence : undefined
    }));

  // Parse-validation is delegated to the Python backend (ANTLR), which rejects
  // or normalizes formulas when it builds the candidate pool.
  const validated: LtlCandidate[] = shaped;

  // If atoms were declared, optionally flag candidates using undeclared atoms (kept, but logged).
  if (declaredAtoms.size > 0) {
    for (const c of validated) {
      const used = c.formula.match(/[a-z0-9]+/g) ?? [];
      const undeclared = used.filter(u => !declaredAtoms.has(u));
      if (undeclared.length > 0) {
        logger.warn(`Candidate "${c.formula}" uses undeclared atoms: ${undeclared.join(', ')}`);
      }
    }
  }

  if (validated.length === 0) {
    throw new Error('No valid LTL candidates returned by model.');
  }

  if (warnings.length > 0) {
    logger.warn(`Model flagged potential LTL limitations: ${warnings.join(' | ')}`);
  }

  return {
    atoms: atoms.length > 0 ? atoms : undefined,
    candidates: validated,
    warnings: warnings.length > 0 ? warnings : undefined
  };
}
