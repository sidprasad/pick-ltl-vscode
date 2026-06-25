import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import { WordClassification, WordClassificationRecord } from './pickTypes';
import { generateLtlFromDescription, PermissionRequiredError, NoModelsAvailableError, ModelNotSupportedError, ModelNotEnabledError, getAvailableChatModels, LtlCandidate, LtlAtom } from './ltlService';
import { logger } from './logger';
import { openIssueReport } from './issueReporter';
import { SurveyPrompt } from './surveyPrompt';
import { LtlBackend, BackendUnavailableError, SessionState } from './ltlBackend';
import { PythonSidecar, SidecarError } from './sidecar';
import { traceToRenderData } from './traceRender';

/**
 * Order the model's interpretations by confidence (highest first) so the
 * highest-confidence one becomes the primary seed. We deliberately keep *all*
 * of them: the Python backend deduplicates seeds semantically (SPOT
 * equivalence), so feeding every distinct interpretation only enriches the
 * candidate pool — it never produces duplicates. (Previously this truncated to
 * the top 2, discarding interpretations the model was explicitly asked for.)
 */
export function orderCandidatesByConfidence(candidates: LtlCandidate[]): LtlCandidate[] {
  const sorted = [...candidates].sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0));
  logger.info(
    `Seeding backend with all ${sorted.length} model interpretation(s) ` +
    `(confidence: ${sorted.map(c => c.confidence ?? 0).join(', ')}); backend dedupes equivalents.`
  );
  return sorted;
}

export class PickViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = 'pick-ltl.pickView';
  private view?: vscode.WebviewView;
  private renderCache = new Map<string, unknown>();
  private cancellationTokenSource?: vscode.CancellationTokenSource;
  private activeHeartbeat?: { stop: () => void };
  private lastModelDescription?: string;
  private lastModelId?: string;
  // Backend-driven session state (replaces the in-TS PickController loop).
  private session: SessionState | null = null;
  private currentPairTraces: [string, string] | null = null;
  private currentPairClassified = new Set<string>();

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly surveyPrompt: SurveyPrompt,
    private readonly globalState: vscode.Memento,
    private readonly backend: LtlBackend,
    private readonly sidecar: PythonSidecar
  ) {}

  /**
   * Called when the backend sidecar becomes reachable (on auto-start or after
   * the "Set Up / Restart Backend" command). The full webview rewire onto the
   * backend API will refresh state here; for now it records readiness and
   * clears any "backend unavailable" notice in the webview.
   */
  async onBackendReady(): Promise<void> {
    logger.info('PICK LTL backend is ready.');
    this.view?.webview.postMessage({ type: 'backendReady', baseUrl: this.sidecar.getBaseUrl() });
  }

  // ---- Backend-driven PICK loop (sidecar adapter) ----------------------------

  /** Map a backend SessionState's candidates into the webview's candidate shape. */
  private sessionToCandidates(session: SessionState) {
    return session.candidate_states.map(c => ({
      pattern: c.formula,
      explanation: c.explanation || undefined,
      confidence: c.confidence ?? undefined,
      positiveVotes: c.positive_votes,
      negativeVotes: c.negative_votes,
      eliminated: c.eliminated,
      eliminationThreshold: c.elimination_threshold,
      equivalents: c.equivalents ?? []
    }));
  }

  /** Build the webview "status" object from a backend SessionState. */
  private sessionToStatus(session: SessionState) {
    const candidateDetails = this.sessionToCandidates(session);
    const wordHistory = session.history.map(h => ({
      word: h.trace,
      classification: h.classification,
      matchingFormulas: h.matching_candidates
    }));
    const thresholds = session.candidate_states.map(c => c.elimination_threshold);
    return {
      candidateDetails,
      threshold: thresholds.length ? Math.min(...thresholds) : 2,
      wordHistory,
      activeCandidates: candidateDetails.filter(c => !c.eliminated).length,
      totalCandidates: candidateDetails.length
    };
  }

  /** Backend history -> the WordClassificationRecord shape used by refinement helpers. */
  private historyToRecords(session: SessionState): WordClassificationRecord[] {
    return session.history.map(h => ({
      word: h.trace,
      classification: h.classification as WordClassification,
      timestamp: h.timestamp,
      matchingFormulas: h.matching_candidates,
      source: (h.source === 'direct' || h.source === 'manual' ? 'direct' : 'pair') as 'pair' | 'direct'
    }));
  }

  private toSeedAtoms(atoms: LtlAtom[]): Array<{ name: string; meaning: string }> {
    return atoms.map(a => ({ name: a.name, meaning: a.meaning ?? '' }));
  }

  /** Surface a sidecar/backend failure as a webview error with setup guidance. */
  private async reportBackendError(error: unknown): Promise<void> {
    let message: string;
    if (error instanceof SidecarError) {
      message = `${error.message}${error.details ? `\n\n${error.details}` : ''}\n\nRun "PICK LTL: Set Up / Restart Backend" after fixing your environment.`;
    } else if (error instanceof BackendUnavailableError) {
      message = `${error.message}\n\nRun "PICK LTL: Set Up / Restart Backend" to start it.`;
    } else {
      message = error instanceof Error ? error.message : String(error);
    }
    logger.error(error instanceof Error ? error : new Error(String(error)), 'PICK LTL backend error');
    this.sendMessage({ type: 'error', message });
  }

  /** Render the current session to the webview according to its mode. */
  private async renderSession(): Promise<void> {
    const session = this.session;
    if (!session) {
      return;
    }
    const status = this.sessionToStatus(session);
    const accepts = () => status.wordHistory.filter(r => r.classification === 'accept').map(r => r.word);
    const rejects = () => status.wordHistory.filter(r => r.classification === 'reject').map(r => r.word);

    if (session.mode === 'final_result' || session.mode === 'single_candidate') {
      const fr = session.final_result;
      const historyRenderData = await this.buildHistoryRenderData(status.wordHistory.map(r => r.word));
      if (fr && fr.formula) {
        this.sendMessage({
          type: 'finalResult',
          formula: fr.formula,
          wordsIn: fr.examples_in ?? [],
          wordsOut: fr.examples_out ?? [],
          status,
          historyRenderData
        });
      } else {
        this.sendMessage({
          type: 'noFormulaFound',
          message: (fr && fr.message) || session.message || 'No candidate formulas match your requirements.',
          candidateDetails: status.candidateDetails,
          wordsIn: accepts(),
          wordsOut: rejects(),
          wordHistory: status.wordHistory,
          historyRenderData
        });
      }
      await this.surveyPrompt.incrementUsageAndCheckPrompt();
      return;
    }

    if (session.mode === 'no_result') {
      const historyRenderData = await this.buildHistoryRenderData(status.wordHistory.map(r => r.word));
      this.sendMessage({
        type: 'noFormulaFound',
        message: session.message || 'All candidate formulas were eliminated.',
        candidateDetails: status.candidateDetails,
        wordsIn: accepts(),
        wordsOut: rejects(),
        wordHistory: status.wordHistory,
        historyRenderData
      });
      await this.surveyPrompt.incrementUsageAndCheckPrompt();
      return;
    }

    // voting
    if (session.current_pair) {
      const pair = { word1: session.current_pair.trace1, word2: session.current_pair.trace2 };
      this.currentPairTraces = [pair.word1, pair.word2];
      this.currentPairClassified.clear();
      const renderData = {
        word1: traceToRenderData(pair.word1),
        word2: traceToRenderData(pair.word2)
      };
      const historyRenderData = await this.buildHistoryRenderData(status.wordHistory.map(r => r.word));
      this.sendMessage({
        type: 'newPair',
        pair,
        status,
        matches: { word1: session.current_pair.matches1, word2: session.current_pair.matches2 },
        renderData,
        historyRenderData
      });
      return;
    }

    if (session.exhausted) {
      this.sendMessage({
        type: 'insufficientWords',
        candidates: status.candidateDetails.filter(c => !c.eliminated),
        status,
        message: session.message || 'Unable to generate more distinguishing traces.'
      });
      return;
    }

    // Voting but no pair yet (e.g. right after build): the caller advances.
    logger.info('renderSession: voting with no current pair; awaiting advance().');
  }

  /** Ask the backend for the next distinguishing pair, then render. */
  private async advance(): Promise<void> {
    if (!this.session) {
      this.sendMessage({ type: 'error', message: 'No active session. Generate candidates first.' });
      return;
    }
    this.session = await this.backend.nextPair(this.session);
    await this.renderSession();
  }

  private readonly preferredModelKey = 'pick.preferredModelId';

  private getPreferredModelId(): string | undefined {
    return this.globalState.get<string>(this.preferredModelKey);
  }

  private async setPreferredModelId(modelId?: string) {
    await this.globalState.update(this.preferredModelKey, modelId);
  }

  public resolveWebviewView(
    webviewView: vscode.WebviewView,
    context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ) {
    this.view = webviewView;

    // Keep any options configured during registration (e.g., retainContextWhenHidden)
    // while enabling scripts and scoping resource loading.
    webviewView.webview.options = {
      ...webviewView.webview.options,
      enableScripts: true,
      localResourceRoots: [this.extensionUri]
    };

    webviewView.webview.html = this.getHtmlForWebview(webviewView.webview);

    // Handle messages from the webview
     webviewView.webview.onDidReceiveMessage(async (data) => {
      switch (data.type) {
        case 'webviewReady':
          // Webview is initialized and ready to receive messages
          logger.info('Webview initialized and ready');
          await this.checkAvailableModels();
          break;
        case 'log':
          // Forward webview logs to backend logger
          if (data.level === 'info') {
            logger.info(`[Webview] ${data.message}`);
          } else if (data.level === 'warn') {
            logger.warn(`[Webview] ${data.message}`);
          } else if (data.level === 'error') {
            logger.error(`[Webview] ${data.message}`);
          }
          break;
        case 'generateCandidates':
          // Don't await - run asynchronously so other messages can be processed
          this.handleGenerateCandidates(data.prompt, data.modelId).catch(error => {
            logger.error(error, 'Error in handleGenerateCandidates');
          });
          break;
        case 'refineCandidates':
          // Don't await - run asynchronously so other messages can be processed
          this.handleRefineCandidates(data.prompt, data.modelId, data.modelChanged, data.previousModelId).catch(error => {
            logger.error(error, 'Error in handleRefineCandidates');
          });
          break;
        case 'classifyWord':
          this.handleClassifyWord(data.word, data.classification);
          break;
        case 'updateClassification':
          this.handleUpdateClassification(data.index, data.classification);
          break;
        case 'wordEdited':
          this.handleWordEdited(data.originalWord, data.newWord);
          break;
        case 'vote':
          this.handleVote(data.acceptedWord);
          break;
        case 'reset':
          this.handleReset(data.preserveClassifications);
          break;
        case 'requestNextPair':
          this.handleRequestNextPair();
          break;
        case 'copy':
          try {
            await this.copyToClipboard(data.formula || '');
            this.sendMessage({ type: 'copied', formula: data.formula });
          } catch (error) {
            logger.error(error, 'Failed to copy to clipboard');
            this.sendMessage({ type: 'error', message: 'Failed to copy to clipboard' });
          }
          break;
        case 'submitExamples':
          await this.handleSubmitExamples(data.acceptWords, data.rejectWords);
          break;
        case 'cancel':
          this.handleCancel();
          break;
        case 'checkModels':
          await this.checkAvailableModels();
          break;
        case 'modelSelected':
          await this.setPreferredModelId(data.modelId);
          break;
        case 'reportIssue':
          try {
            await openIssueReport();
          } catch (error) {
            logger.error(error, 'Failed to open issue report');
            this.sendMessage({ type: 'error', message: 'Failed to open issue report' });
          }
          break;
        case 'loadSession':
          this.handleLoadSession(data.data).catch(error => {
            logger.error(error, 'Error in handleLoadSession');
          });
          break;
      }
    });
  }

  /**
   * Check if language models are available and notify the webview
   */
  private async checkAvailableModels() {
    try {
      const models = await getAvailableChatModels();
      const preferredModelId = this.getPreferredModelId();

      if (models.length === 0) {
        logger.warn('No language models available on startup');
        this.sendMessage({
          type: 'noModelsAvailable',
          message: 'No language models available. Please ensure you have a language model extension installed (e.g., GitHub Copilot) and that you are signed in.'
        });
      } else {
        logger.info(`Found ${models.length} available language model(s): ${models.map(m => m.name).join(', ')}`);
        const availableIds = models.map(m => m.id);
        const selectedModelId = (preferredModelId && availableIds.includes(preferredModelId))
          ? preferredModelId
          : models[0].id;
        await this.setPreferredModelId(selectedModelId);

        this.sendMessage({
          type: 'modelsAvailable',
          models: models,
          preferredModelId: selectedModelId
        });
      }
    } catch (error) {
      logger.warn(`Failed to check available models: ${error}`);
      // Don't show an error here - the user will see it when they try to generate
    }
  }

  /**
   * Build a friendly description of the model being used so we can surface it in UI status updates
   */
  private async getModelDescription(modelId?: string): Promise<string | null> {
    try {
      const models = await getAvailableChatModels();
      if (models.length === 0) {
        return null;
      }

      const preferred = modelId ? models.find(m => m.id === modelId) : undefined;
      const model = preferred ?? models[0];
      const vendorPart = model.vendor ? ` from ${model.vendor}` : '';
      const familyPart = model.family ? ` (${model.family})` : '';
      return `${model.name}${familyPart}${vendorPart}`;
    } catch (error) {
      logger.warn(`Unable to describe model for status message: ${error}`);
      return null;
    }
  }

  private collectPositiveExamplesForRefinement(wordHistory: WordClassificationRecord[]): string[] {
    const MAX_EXAMPLES = 6;
    const MAX_TOTAL_CHARS = 240;
    const MAX_EXAMPLE_LENGTH = 80;

    const normalize = (records: WordClassificationRecord[]) =>
      records
        .filter(record => record.classification === WordClassification.ACCEPT)
        .map(record => ({ ...record, word: record.word.trim() }))
        .filter(record => record.word.length > 0)
        .sort((a, b) => b.timestamp - a.timestamp);

    const directAccepts = normalize(wordHistory.filter(record => record.source === 'direct'));
    const pairAccepts = normalize(wordHistory.filter(record => record.source !== 'direct'));

    const examples: string[] = [];
    const seen = new Set<string>();
    let totalChars = 0;

    const tryAddExamples = (records: WordClassificationRecord[]) => {
      for (const record of records) {
        if (examples.length >= MAX_EXAMPLES || totalChars >= MAX_TOTAL_CHARS) {
          return;
        }

        const word = record.word;
        if (seen.has(word)) {
          continue;
        }

        if (word.length > MAX_EXAMPLE_LENGTH) {
          logger.info(
            `Skipping positive example longer than ${MAX_EXAMPLE_LENGTH} characters to avoid bloating the prompt: "${word}".`
          );
          continue;
        }

        if (totalChars + word.length > MAX_TOTAL_CHARS) {
          logger.info(
            `Skipping positive example to stay within prompt size limit (${MAX_TOTAL_CHARS} chars total): "${word}".`
          );
          return;
        }

        seen.add(word);
        examples.push(word);
        totalChars += word.length;
      }
    };

    // Prefer user-provided direct examples, then fall back to pair-based accepts.
    tryAddExamples(directAccepts);
    tryAddExamples(pairAccepts);

    return examples;
  }

  private async handleGenerateCandidates(prompt: string, modelId?: string) {
    try {
      this.sendMessage({ type: 'clearWarnings' });

      const modelDescription = await this.getModelDescription(modelId);
      this.lastModelDescription = modelDescription ?? undefined;
      this.lastModelId = modelId;
      const statusMessage = modelDescription
        ? `Asking ${modelDescription} to propose candidate formulas...`
        : 'Asking your language model to propose candidate formulas...';
      this.sendMessage({ type: 'status', message: statusMessage });

      // While VS Code surfaces some LLM activity in the UI, the webview does not receive those updates.
      // Send periodic heartbeats so users see that the model is still working when responses take longer.
      const heartbeat = this.startModelHeartbeat(
        modelDescription
          ? `Waiting for ${modelDescription} to respond with candidates...`
          : 'Waiting for your language model to respond with candidates...'
      );

      // Generate candidate formulas using LLM
      // Dispose any existing cancellation token
      if (this.cancellationTokenSource) {
        this.cancellationTokenSource.dispose();
      }
      this.cancellationTokenSource = new vscode.CancellationTokenSource();

      let candidates: LtlCandidate[] = [];
      let warnings: string[] = [];
      let atoms: LtlAtom[] = [];
      try {
        const result = await generateLtlFromDescription(prompt, this.cancellationTokenSource.token, modelId);
        candidates = result.candidates;
        warnings = result.warnings ?? [];
        atoms = result.atoms ?? [];
        logger.info(`Generated ${candidates.length} candidates from LLM`);

        // Log each candidate with explanation
        result.candidates.forEach((c, i) => {
          logger.info(`Candidate ${i + 1}: ${c.formula} (confidence: ${c.confidence ?? 'N/A'}) - ${c.explanation}`);
        });
      } catch (error) {
        // Debug logging to see what type of error we're getting
        logger.info(`Caught error type: ${error?.constructor?.name}, instanceof ModelNotSupportedError: ${error instanceof ModelNotSupportedError}`);
        
        // Check if it was cancelled
        if (this.cancellationTokenSource.token.isCancellationRequested) {
          logger.info('Candidate generation was cancelled by user');
          this.sendMessage({
            type: 'cancelled',
            message: 'Operation cancelled by user.'
          });
          return;
        }

        // Handle specific error types
        if (error instanceof PermissionRequiredError) {
          logger.error(error, 'Permission required for language model access');
          this.sendMessage({
            type: 'permissionRequired',
            message: error.message
          });
          return;
        }

        if (error instanceof NoModelsAvailableError) {
          logger.error(error, 'No language models available');
          this.sendMessage({
            type: 'noModelsAvailable',
            message: error.message
          });
          return;
        }

        if (error instanceof ModelNotSupportedError) {
          logger.error(error, 'Model not supported');
          this.sendMessage({
            type: 'error',
            message: error.message
          });
          return;
        }

        if (error instanceof ModelNotEnabledError) {
          logger.error(error, 'Model not enabled/accessible');
          this.sendMessage({
            type: 'error',
            message: error.message
          });
          return;
        }

        // Check for model_not_supported in error message (fallback if error class doesn't match)
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (errorMessage.includes('model_not_supported') || 
            errorMessage.toLowerCase().includes('model is not supported')) {
          logger.error(error, 'Model not supported (detected from message)');
          const msg = 'The selected model is not currently supported. Please try a different model.';
          vscode.window.showErrorMessage(msg, 'Select Different Model').then(selection => {
            if (selection === 'Select Different Model') {
              this.checkAvailableModels();
            }
          });
          this.sendMessage({
            type: 'error',
            message: msg
          });
          return;
        }

        logger.error(error, 'Failed to generate candidate formulas');
        this.sendMessage({
          type: 'error',
          message: 'Could not generate any candidate formulas. Please try again.'
        });
        return;
      } finally {
        heartbeat.stop();
      }

      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        logger.info('Operation cancelled after model responded (before validation)');
        this.sendMessage({
          type: 'cancelled',
          message: 'Operation cancelled by user.'
        });
        return;
      }

      if (candidates.length === 0) {
        this.sendMessage({
          type: 'error',
          message: 'Could not generate any candidate formulas. Please try again.'
        });
        return;
      }

      this.sendMessage({ type: 'status', message: 'Expanding candidates with misconception mutations…' });

      try {
        await this.sidecar.ensureStarted();
      } catch (startError) {
        await this.reportBackendError(startError);
        return;
      }

      // Hand the top LLM interpretations to the backend as PICK seeds; it expands
      // each via misconception + syntactic mutation and uses SPOT to generate
      // distinguishing traces and set per-candidate elimination thresholds.
      const seeds = orderCandidatesByConfidence(candidates).map(candidate => ({
        formula: candidate.formula,
        explanation: candidate.explanation ?? '',
        atoms: this.toSeedAtoms(atoms),
        warnings: []
      }));

      this.session = await this.backend.buildCandidates({ prompt, seeds });
      
      // Check cancellation before sending results
      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        logger.info('Operation cancelled before sending candidates to UI');
        this.sendMessage({ 
          type: 'cancelled', 
          message: 'Operation cancelled by user.' 
        });
        return;
      }

      this.sendMessage({
        type: 'candidatesGenerated',
        candidates: this.sessionToCandidates(this.session!)
      });

      this.surfaceModelWarnings(warnings);

      // Check cancellation before generating first pair
      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        logger.info('Operation cancelled before generating first word pair');
        this.sendMessage({
          type: 'cancelled', 
          message: 'Operation cancelled by user.' 
        });
        return;
      }

      // Generate first word pair (or proceed to final result if only 1 candidate)
      this.handleRequestNextPair();
      
    } catch (error) {
      logger.error(error, 'Error generating candidates');
      this.sendMessage({
        type: 'error',
        message: `Error: ${error}`
      });
    }
  }

  private async handleRequestNextPair() {
    try {
      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        this.sendMessage({ type: 'cancelled', message: 'Operation cancelled by user.' });
        return;
      }
      if (!this.session) {
        this.sendMessage({ type: 'error', message: 'No active session. Generate candidates first.' });
        return;
      }
      await this.advance();
    } catch (error) {
      if (error instanceof BackendUnavailableError || error instanceof SidecarError) {
        await this.reportBackendError(error);
        return;
      }
      logger.error(error, 'Error generating next pair');
      this.sendMessage({ type: 'error', message: `Error generating pair: ${error instanceof Error ? error.message : String(error)}` });
    }
  }

  private async handleClassifyWord(word: string, classification: string) {
    try {
      if (!this.session) {
        this.sendMessage({ type: 'error', message: 'No active session to classify against.' });
        return;
      }
      const cls = classification as 'accept' | 'reject' | 'unsure';
      this.session = await this.backend.classify(this.session, word, cls, 'pair');
      this.currentPairClassified.add(word);

      // Classification may have converged the session (final / no-result / single).
      if (this.session.mode !== 'voting') {
        await this.renderSession();
        return;
      }

      const bothClassified = !!this.currentPairTraces
        && this.currentPairTraces.every(trace => this.currentPairClassified.has(trace));
      this.sendMessage({ type: 'wordClassified', status: this.sessionToStatus(this.session), bothClassified });

      if (bothClassified) {
        await this.advance();
      }
    } catch (error) {
      if (error instanceof BackendUnavailableError || error instanceof SidecarError) {
        await this.reportBackendError(error);
        return;
      }
      logger.error(error, 'Error classifying word');
      this.sendMessage({ type: 'error', message: `Error classifying word: ${error instanceof Error ? error.message : String(error)}` });
    }
  }

  private async handleUpdateClassification(index: number, classification: string) {
    try {
      if (!this.session) {
        return;
      }
      this.session = await this.backend.reclassify(this.session, index, classification);
      if (this.session.mode !== 'voting') {
        await this.renderSession();
        return;
      }
      this.sendMessage({ type: 'classificationUpdated', status: this.sessionToStatus(this.session) });
      // reclassify clears the current pair; fetch a fresh one to keep voting.
      await this.advance();
    } catch (error) {
      if (error instanceof BackendUnavailableError || error instanceof SidecarError) {
        await this.reportBackendError(error);
        return;
      }
      logger.error(error, 'Error updating classification');
      this.sendMessage({ type: 'error', message: `Error updating classification: ${error instanceof Error ? error.message : String(error)}` });
    }
  }

  /**
   * Apply user-provided examples outside the current word pair flow.
   */
  private async handleSubmitExamples(acceptWords: string[] = [], rejectWords: string[] = []) {
    try {
      if (!this.session) {
        this.sendMessage({ type: 'examplesRejected', message: 'Generate candidates before adding your own examples.' });
        return;
      }
      const normalizedAccept = this.normalizeExampleWords(acceptWords);
      const normalizedReject = this.normalizeExampleWords(rejectWords);

      const conflicts = normalizedAccept.filter(word => normalizedReject.includes(word));
      if (conflicts.length > 0) {
        this.sendMessage({ type: 'examplesRejected', message: `The same word appears in both lists: ${conflicts.join(', ')}. Remove duplicates and try again.` });
        return;
      }

      const combined = [
        ...normalizedAccept.map(word => ({ word, classification: 'accept' as const })),
        ...normalizedReject.map(word => ({ word, classification: 'reject' as const }))
      ];
      if (combined.length === 0) {
        this.sendMessage({ type: 'examplesRejected', message: 'Add at least one example that should match or should not match.' });
        return;
      }

      const maxExamples = 12;
      const limited = combined.slice(0, maxExamples);
      const truncated = combined.length - limited.length;
      const acceptList = limited.filter(entry => entry.classification === 'accept').map(entry => entry.word);
      const rejectList = limited.filter(entry => entry.classification === 'reject').map(entry => entry.word);

      this.session = await this.backend.addExamples(this.session, acceptList, rejectList);
      logger.info(`Applied ${limited.length} direct classification(s) from user-provided examples.`);

      this.sendMessage({
        type: 'examplesApplied',
        status: this.sessionToStatus(this.session),
        acceptCount: acceptList.length,
        rejectCount: rejectList.length,
        truncated
      });

      if (this.session.mode !== 'voting') {
        await this.renderSession();
      }
    } catch (error) {
      if (error instanceof BackendUnavailableError || error instanceof SidecarError) {
        await this.reportBackendError(error);
        return;
      }
      logger.error(error, 'Error applying custom examples');
      this.sendMessage({ type: 'error', message: `Error applying your examples: ${error instanceof Error ? error.message : String(error)}` });
    }
  }

  /**
   * Normalize user-provided examples by trimming whitespace and removing duplicates.
   */
  private normalizeExampleWords(words: unknown): string[] {
    if (!Array.isArray(words)) {
      return [];
    }

    const seen = new Set<string>();
    const normalized: string[] = [];

    for (const entry of words) {
      if (typeof entry !== 'string') {
        continue;
      }
      const word = entry.trim();
      if (word.length === 0 || seen.has(word)) {
        continue;
      }
      seen.add(word);
      normalized.push(word);
    }

    return normalized;
  }

  /**
   * Load a previously exported session from JSON data
   */
  private async handleLoadSession(data: any) {
    try {
      logger.info('Loading session from exported JSON');
      if (!data || typeof data !== 'object') {
        this.sendMessage({ type: 'error', message: 'Invalid session data: not an object' });
        return;
      }
      if (!Array.isArray(data.candidates) || data.candidates.length === 0) {
        this.sendMessage({ type: 'error', message: 'Invalid session data: candidates must be a non-empty array' });
        return;
      }
      if (!Array.isArray(data.classifications)) {
        this.sendMessage({ type: 'error', message: 'Invalid session data: classifications must be an array' });
        return;
      }

      const loadedPrompt = typeof data.prompt === 'string' ? data.prompt : '';
      const loadedModelId = typeof data.modelId === 'string' ? data.modelId : '';

      const candidateStates: SessionState['candidate_states'] = [];
      for (const candidate of data.candidates) {
        if (!candidate || typeof candidate.formula !== 'string' || candidate.formula.trim().length === 0) {
          logger.warn('Skipping candidate with missing or invalid formula');
          continue;
        }
        candidateStates.push({
          formula: candidate.formula,
          explanation: typeof candidate.explanation === 'string' ? candidate.explanation : '',
          origin: { kind: 'seed', misconception_code: null },
          confidence: typeof candidate.confidence === 'number' ? candidate.confidence : null,
          equivalents: Array.isArray(candidate.equivalents) ? candidate.equivalents.map((x: unknown) => String(x)) : [],
          positive_votes: 0,
          negative_votes: 0,
          elimination_threshold: 2,
          eliminated: false
        });
      }
      if (candidateStates.length === 0) {
        this.sendMessage({ type: 'error', message: 'No valid candidate formulas found in session data' });
        return;
      }

      const toCls = (raw: string): 'accept' | 'reject' | 'unsure' => {
        const n = (raw || '').toLowerCase();
        if (n === 'in' || n === 'accept') {
          return 'accept';
        }
        if (n === 'out' || n === 'reject') {
          return 'reject';
        }
        return 'unsure';
      };
      const accepts: string[] = [];
      const rejects: string[] = [];
      for (const item of data.classifications) {
        if (!item || typeof item.word !== 'string') {
          continue;
        }
        const cls = toCls(item.classification);
        if (cls === 'accept') {
          accepts.push(item.word);
        } else if (cls === 'reject') {
          rejects.push(item.word);
        }
      }

      this.sendMessage({ type: 'status', message: 'Loading session…' });
      try {
        await this.sidecar.ensureStarted();
      } catch (startError) {
        await this.reportBackendError(startError);
        return;
      }

      const importedSession: SessionState = {
        version: 1,
        prompt: loadedPrompt || 'Loaded session',
        provider: {},
        seed: null,
        seeds: [],
        candidate_states: candidateStates,
        history: [],
        mode: 'voting',
        warnings: [],
        current_pair: null,
        final_result: null,
        exhausted: false,
        message: ''
      };
      this.session = await this.backend.importSession(importedSession);

      const classificationCount = accepts.length + rejects.length;
      if (classificationCount > 0) {
        this.sendMessage({ type: 'status', message: `Applying ${classificationCount} classification(s)…` });
        this.session = await this.backend.addExamples(this.session, accepts, rejects);
      }

      this.sendMessage({
        type: 'sessionLoaded',
        status: this.sessionToStatus(this.session),
        candidateCount: candidateStates.length,
        classificationCount,
        prompt: loadedPrompt || undefined,
        modelId: loadedModelId || undefined
      });

      if (this.session.mode !== 'voting') {
        await this.renderSession();
      } else {
        this.sendMessage({ type: 'showVoting' });
        await this.advance();
      }
    } catch (error) {
      if (error instanceof BackendUnavailableError || error instanceof SidecarError) {
        await this.reportBackendError(error);
        return;
      }
      logger.error(error, 'Error loading session');
      this.sendMessage({ type: 'error', message: `Error loading session: ${error instanceof Error ? error.message : String(error)}` });
    }
  }

  /**
   * Handle word edit in the current voting pair
   */
  private handleWordEdited(originalWord: string, newWord: string) {
    try {
      logger.info(`Word edited: "${originalWord}" -> "${newWord}"`);
      if (this.currentPairTraces) {
        const idx = this.currentPairTraces.indexOf(originalWord);
        if (idx >= 0) {
          this.currentPairTraces[idx] = newWord;
        }
      }
      if (this.session?.current_pair) {
        if (this.session.current_pair.trace1 === originalWord) {
          this.session.current_pair.trace1 = newWord;
        } else if (this.session.current_pair.trace2 === originalWord) {
          this.session.current_pair.trace2 = newWord;
        }
      }
    } catch (error) {
      logger.error(error, 'Error updating word in pair');
    }
  }

  private async handleVote(acceptedWord: string) {
    try {
      if (!this.session || !this.currentPairTraces) {
        return;
      }
      const [w1, w2] = this.currentPairTraces;
      const rejectedWord = acceptedWord === w1 ? w2 : w1;
      this.session = await this.backend.classify(this.session, acceptedWord, 'accept', 'pair');
      this.session = await this.backend.classify(this.session, rejectedWord, 'reject', 'pair');
      if (this.session.mode !== 'voting') {
        await this.renderSession();
        return;
      }
      this.sendMessage({ type: 'voteProcessed', status: this.sessionToStatus(this.session) });
      await this.advance();
    } catch (error) {
      if (error instanceof BackendUnavailableError || error instanceof SidecarError) {
        await this.reportBackendError(error);
        return;
      }
      logger.error(error, 'Error processing vote');
      this.sendMessage({ type: 'error', message: `Error processing vote: ${error instanceof Error ? error.message : String(error)}` });
    }
  }

  private async handleFinalResult() {
    await this.renderSession();
  }

  private async handleRefineCandidates(prompt: string, modelId?: string, modelChanged?: boolean, previousModelId?: string) {
    try {
      this.sendMessage({ type: 'clearWarnings' });

      // Log revision type
      if (modelChanged && previousModelId) {
        const prevModelDesc = await this.getModelDescription(previousModelId);
        const newModelDesc = await this.getModelDescription(modelId);
        logger.info(`Revising with MODEL CHANGE: ${prevModelDesc || previousModelId} → ${newModelDesc || modelId}`);
      } else {
        logger.info(`Revising with prompt refinement (same model: ${modelId || 'default'})`);
      }

      const modelDescription = await this.getModelDescription(modelId);
      this.lastModelDescription = modelDescription ?? undefined;
      this.lastModelId = modelId;
      const statusMessage = modelDescription
        ? `Asking ${modelDescription} to refine your formula candidates...`
        : 'Asking your language model to refine your formula candidates...';
      this.sendMessage({ type: 'status', message: statusMessage });

      const heartbeat = this.startModelHeartbeat(
        modelDescription
          ? `Waiting for ${modelDescription} to finish refining your candidates...`
          : 'Waiting for your language model to finish refining your candidates...'
      );

      // Get session data before refinement
      const sessionData = { wordHistory: this.session ? this.historyToRecords(this.session) : [] };
      
      // Generate new candidate formulas using LLM
      // Dispose any existing cancellation token
      if (this.cancellationTokenSource) {
        this.cancellationTokenSource.dispose();
      }
      this.cancellationTokenSource = new vscode.CancellationTokenSource();

      const positiveExamples = this.collectPositiveExamplesForRefinement(sessionData.wordHistory);
      if (positiveExamples.length > 0) {
        logger.info(`Including ${positiveExamples.length} positive example(s) in refinement prompt.`);
      }

      let candidates: LtlCandidate[] = [];
      let warnings: string[] = [];
      let atoms: LtlAtom[] = [];
      try {
        const result = await generateLtlFromDescription(prompt, this.cancellationTokenSource.token, modelId, {
          positiveExamples
        });
        candidates = result.candidates;
        warnings = result.warnings ?? [];
        atoms = result.atoms ?? [];
        logger.info(`Generated ${candidates.length} candidates from LLM for refinement`);

        // Log each candidate with explanation
        result.candidates.forEach((c, i) => {
          logger.info(`Candidate ${i + 1}: ${c.formula} (confidence: ${c.confidence ?? 'N/A'}) - ${c.explanation}`);
        });
      } catch (error) {
        // Check if it was cancelled
        if (this.cancellationTokenSource.token.isCancellationRequested) {
          logger.info('Candidate refinement was cancelled by user');
          this.sendMessage({
            type: 'cancelled',
            message: 'Operation cancelled by user.'
          });
          return;
        }

        // Handle specific error types
        if (error instanceof PermissionRequiredError) {
          logger.error(error, 'Permission required for language model access');
          this.sendMessage({
            type: 'permissionRequired',
            message: error.message
          });
          return;
        }

        if (error instanceof NoModelsAvailableError) {
          logger.error(error, 'No language models available');
          this.sendMessage({
            type: 'noModelsAvailable',
            message: error.message
          });
          return;
        }

        if (error instanceof ModelNotSupportedError) {
          logger.error(error, 'Model not supported');
          this.sendMessage({
            type: 'error',
            message: error.message
          });
          return;
        }

        if (error instanceof ModelNotEnabledError) {
          logger.error(error, 'Model not enabled/accessible');
          this.sendMessage({
            type: 'error',
            message: error.message
          });
          return;
        }

        // Check for model_not_supported in error message (fallback if error class doesn't match)
        const errorMessage = error instanceof Error ? error.message : String(error);
        if (errorMessage.includes('model_not_supported') || 
            errorMessage.toLowerCase().includes('model is not supported')) {
          logger.error(error, 'Model not supported (detected from message)');
          const msg = 'The selected model is not currently supported. Please try a different model.';
          vscode.window.showErrorMessage(msg, 'Select Different Model').then(selection => {
            if (selection === 'Select Different Model') {
              this.checkAvailableModels();
            }
          });
          this.sendMessage({
            type: 'error',
            message: msg
          });
          return;
        }

        logger.error(error, 'Failed to generate candidate formulas during refinement');
        this.sendMessage({
          type: 'error',
          message: 'Could not generate any candidate formulas. Please try again.'
        });
        return;
      } finally {
        heartbeat.stop();
      }

      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        logger.info('Operation cancelled after model responded (refinement, before validation)');
        this.sendMessage({
          type: 'cancelled',
          message: 'Operation cancelled by user.'
        });
        return;
      }

      if (candidates.length === 0) {
        this.sendMessage({
          type: 'error',
          message: 'Could not generate any candidate formulas. Please try again.'
        });
        return;
      }

      this.sendMessage({ type: 'status', message: 'Expanding candidates with misconception mutations…' });

      try {
        await this.sidecar.ensureStarted();
      } catch (startError) {
        await this.reportBackendError(startError);
        return;
      }

      // Replay the user's prior classifications onto the rebuilt candidate pool.
      const replayAccepts = sessionData.wordHistory
        .filter(r => r.classification === WordClassification.ACCEPT)
        .map(r => r.word);
      const replayRejects = sessionData.wordHistory
        .filter(r => r.classification === WordClassification.REJECT)
        .map(r => r.word);

      const seeds = orderCandidatesByConfidence(candidates).map(candidate => ({
        formula: candidate.formula,
        explanation: candidate.explanation ?? '',
        atoms: this.toSeedAtoms(atoms),
        warnings: []
      }));

      this.session = await this.backend.buildCandidates({ prompt, seeds });
      if (replayAccepts.length > 0 || replayRejects.length > 0) {
        this.session = await this.backend.addExamples(this.session, replayAccepts, replayRejects);
      }
      
      // Check cancellation before sending results
      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        logger.info('Operation cancelled before sending refined candidates to UI');
        this.sendMessage({ 
          type: 'cancelled', 
          message: 'Operation cancelled by user.' 
        });
        return;
      }

      this.sendMessage({
        type: 'candidatesRefined',
        candidates: this.sessionToCandidates(this.session!),
        preservedClassifications: sessionData.wordHistory.length
      });

      this.surfaceModelWarnings(warnings);

      // Check cancellation before generating first pair
      if (this.cancellationTokenSource?.token.isCancellationRequested) {
        logger.info('Operation cancelled before generating first word pair (refinement)');
        this.sendMessage({ 
          type: 'cancelled', 
          message: 'Operation cancelled by user.' 
        });
        return;
      }

      // Generate first word pair (or proceed to final result if only 1 candidate)
      this.handleRequestNextPair();
      
    } catch (error) {
      logger.error(error, 'Error refining candidates');
      this.sendMessage({
        type: 'error',
        message: `Error: ${error}`
      });
    }
  }

  private handleReset(preserveClassifications = false) {
    this.session = null;
    this.currentPairTraces = null;
    this.currentPairClassified.clear();
    logger.info(`Reset requested from webview (preserveClassifications: ${preserveClassifications}).`);
    this.sendMessage({ type: 'reset', preserveClassifications });
  }

  private handleCancel() {
    logger.info('Cancel requested from webview');
    
    // Cancel any ongoing LLM request
    if (this.cancellationTokenSource) {
      this.cancellationTokenSource.cancel();
      // Don't dispose or set to undefined yet - ongoing operations still need to check isCancellationRequested
      // The token will be disposed and replaced when a new operation starts
    }
    this.stopActiveHeartbeat();
    
    // Reset session state
    this.session = null;
    this.currentPairTraces = null;
    this.currentPairClassified.clear();
    
    // Notify webview
    this.sendMessage({ 
      type: 'cancelled', 
      message: 'Operation cancelled by user.' 
    });
  }

  private sendMessage(message: any) {
    if (this.view) {
      this.view.webview.postMessage(message);
    }
  }

  private surfaceModelWarnings(warnings: string[]) {
    const formatted = warnings
      .map(warning => warning.trim())
      .filter(warning => warning.length > 0)
      .map(warning => warning.slice(0, 240));

    if (formatted.length === 0) {
      return;
    }

    const cautionIntro = 'This task may not be best suited for LTLs.';
    
    let warningBody: string;
    if (formatted.length === 1) {
      warningBody = formatted[0];
    } else {
      const bulletPoints = formatted.map(w => `• ${w}`).join('\n');
      warningBody = bulletPoints;
    }
    
    const disclaimer = `\n\nThis determination was made by the language model and may be incorrect.`;

    this.sendMessage({
      type: 'warning',
      message: `${cautionIntro}\n\n${warningBody}${disclaimer}`
    });
  }

  /**
   * Periodically surface a status heartbeat to the webview while waiting for LLM responses.
   */
  private startModelHeartbeat(message: string, intervalMs = 8000): { stop: () => void } {
    this.stopActiveHeartbeat();

    const interval = setInterval(() => this.sendMessage({ type: 'status', message }), intervalMs);
    const stop = () => {
      clearInterval(interval);
      if (this.activeHeartbeat && this.activeHeartbeat.stop === stop) {
        this.activeHeartbeat = undefined;
      }
    };

    const heartbeat = { stop };
    this.activeHeartbeat = heartbeat;
    return heartbeat;
  }

  private stopActiveHeartbeat() {
    if (this.activeHeartbeat) {
      this.activeHeartbeat.stop();
      this.activeHeartbeat = undefined;
    }
  }

  /** Build a map of trace string -> SVG render data for the given words (cached). */
  private async buildHistoryRenderData(words: string[]): Promise<Record<string, unknown>> {
    const out: Record<string, unknown> = {};
    for (const w of new Set(words)) {
      if (!this.renderCache.has(w)) {
        this.renderCache.set(w, traceToRenderData(w));
      }
      const rd = this.renderCache.get(w);
      if (rd) {
        out[w] = rd;
      }
    }
    return out;
  }

  private getHtmlForWebview(webview: vscode.Webview) {
    const htmlPath = path.join(this.extensionUri.fsPath, 'media', 'pickView.html');
    const splashPath = path.join(this.extensionUri.fsPath, 'media', 'pickSplash.html');
    const jsUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', 'pickView.js'));
    const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', 'pickView.css'));
    const traceRendererUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', 'vendor', 'tracerenderer.js'));
    
    try {
      const splashHtml = fs.readFileSync(splashPath, 'utf8');
      let html = fs.readFileSync(htmlPath, 'utf8');
      // Inject the CSS, JS, and splash partial into the HTML
      html = html.replace('<!--CSS_URI_PLACEHOLDER-->', cssUri.toString());
      html = html.replace('<!--TRACERENDERER_URI_PLACEHOLDER-->', traceRendererUri.toString());
      html = html.replace('<!--JS_URI_PLACEHOLDER-->', jsUri.toString());
      html = html.replace('<!--SPLASH_HTML_PLACEHOLDER-->', splashHtml);
      return html;
    } catch (err) {
      // In test environments the media file may not be available. Return a minimal
      // HTML fallback so unit tests that instantiate the view provider don't fail
      // with ENOENT. This keeps production behavior unchanged when the file exists.
      const errorMessage = err instanceof Error ? err.message : String(err);
      logger.warn(`Could not read webview HTML at ${htmlPath}: ${errorMessage}`);
      return `<!doctype html><html><body><div id="pick-root"></div><script>const vscode = acquireVsCodeApi();</script></body></html>`;
    }
  }

  /**
   * Clear any persisted webview state (prompt history, splash acknowledgement).
   * Invoked by the reset command so the splash and history reset alongside global storage.
   */
  public async resetLocalWebviewState() {
    await this.setPreferredModelId(undefined);
    this.sendMessage({ type: 'resetLocalState' });
  }

  // Separated clipboard access for easier stubbing in tests
  private async copyToClipboard(text: string) {
    return vscode.env.clipboard.writeText(text);
  }
}
