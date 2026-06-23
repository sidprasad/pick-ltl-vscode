import * as vscode from 'vscode';
import { PickViewProvider } from './pickViewProvider';
import { initializeLogging, logger } from './logger';
import { openIssueReport } from './issueReporter';
import { SurveyPrompt } from './surveyPrompt';
import { PythonSidecar, SidecarError } from './sidecar';
import { LtlBackend } from './ltlBackend';

let sidecar: PythonSidecar | undefined;

/**
 * Surface a sidecar startup failure with actionable buttons. SidecarError
 * carries a precise reason (missing python / spot / deps, boot failure, timeout).
 */
async function presentSidecarError(error: unknown, offerSetup = false): Promise<void> {
  const isSidecar = error instanceof SidecarError;
  const summary = isSidecar
    ? error.message
    : `Failed to start the PICK LTL backend: ${error instanceof Error ? error.message : String(error)}`;
  const detail = isSidecar && error.details ? `\n\n${error.details}` : '';
  logger.error(error instanceof Error ? error : new Error(String(error)), summary);

  const actions = offerSetup
    ? ['Set Up Backend', 'Open Settings', 'Show Logs']
    : ['Open Settings', 'Show Logs'];
  const pick = await vscode.window.showErrorMessage(`${summary}${detail}`, ...actions);
  if (pick === 'Set Up Backend') {
    await vscode.commands.executeCommand('pick-ltl.restartBackend');
  } else if (pick === 'Open Settings') {
    await vscode.commands.executeCommand('workbench.action.openSettings', 'pick-ltl.backend');
  } else if (pick === 'Show Logs') {
    logger.show();
  }
}

// This method is called when your extension is activated
// Your extension is activated the very first time the command is executed
export function activate(context: vscode.ExtensionContext) {
	const log = initializeLogging(context);
	log.info('PICK: LTL Builder is now active!');

	// Initialize survey prompt manager
	const surveyPrompt = new SurveyPrompt(context);

	// The Python backend (misconception mutation + SPOT) runs as a managed
	// localhost sidecar. The extension owns session state and drives it over HTTP.
	sidecar = new PythonSidecar(context.extensionUri, context.globalStorageUri);
	const backend = new LtlBackend(() => sidecar?.getBaseUrl() ?? null);
	context.subscriptions.push({ dispose: () => sidecar?.dispose() });

	// Register the PICK webview provider
        const provider = new PickViewProvider(
                context.extensionUri,
                surveyPrompt,
                context.globalState,
                backend,
                sidecar
        );
        context.subscriptions.push(
                vscode.window.registerWebviewViewProvider(PickViewProvider.viewType, provider, {
                        webviewOptions: {
                                retainContextWhenHidden: true
                        }
                })
        );

	const reportIssueCommand = vscode.commands.registerCommand('pick-ltl.reportIssue', async () => {
		await openIssueReport();
	});

        const resetSurveyCommand = vscode.commands.registerCommand('pick-ltl.resetSurveyState', async () => {
                await surveyPrompt.resetUsageTracking();
                await provider.resetLocalWebviewState();
                vscode.window.showInformationMessage('PICK local storage, history, and splash preference have been cleared.');
        });

        const restartBackendCommand = vscode.commands.registerCommand('pick-ltl.restartBackend', async () => {
                try {
                        const url = await vscode.window.withProgress(
                                { location: vscode.ProgressLocation.Notification, title: 'PICK LTL: starting backend…' },
                                () => sidecar!.restart()
                        );
                        vscode.window.showInformationMessage(`PICK LTL backend is running at ${url}.`);
                        await provider.onBackendReady();
                        return;
                } catch (error) {
                        const envIssue = error instanceof SidecarError
                                && (error.kind === 'python-missing' || error.kind === 'spot-missing' || error.kind === 'deps-missing');
                        if (!envIssue) {
                                await presentSidecarError(error);
                                return;
                        }

                        const choice = await vscode.window.showWarningMessage(
                                `${(error as SidecarError).message}\n\nPICK can create a conda environment named "pick-ltl" (SPOT from conda-forge) for you. This downloads packages and may take a few minutes.`,
                                { modal: true },
                                'Create environment',
                                'Show instructions'
                        );
                        if (choice === 'Show instructions') {
                                logger.show();
                                return;
                        }
                        if (choice !== 'Create environment') {
                                return;
                        }

                        try {
                                const pythonPath = await vscode.window.withProgress(
                                        {
                                                location: vscode.ProgressLocation.Notification,
                                                title: 'PICK LTL: creating conda environment (this can take a few minutes)…'
                                        },
                                        () => sidecar!.provisionEnvironment(line => logger.info(`[setup] ${line}`))
                                );
                                await vscode.workspace
                                        .getConfiguration('pick-ltl')
                                        .update('backend.pythonPath', pythonPath, vscode.ConfigurationTarget.Global);

                                const url = await vscode.window.withProgress(
                                        { location: vscode.ProgressLocation.Notification, title: 'PICK LTL: starting backend…' },
                                        () => sidecar!.restart()
                                );
                                vscode.window.showInformationMessage(`PICK LTL backend is ready at ${url}.`);
                                await provider.onBackendReady();
                        } catch (provisionError) {
                                await presentSidecarError(provisionError);
                        }
                }
        });

	context.subscriptions.push(reportIssueCommand, resetSurveyCommand, restartBackendCommand);

        // Auto-start the sidecar unless disabled. Failures are non-fatal: the
        // webview shows setup guidance and the user can retry via the command.
        const autoStart = vscode.workspace.getConfiguration('pick-ltl').get<boolean>('backend.autoStart', true);
        if (autoStart) {
                void sidecar
                        .ensureStarted()
                        .then(() => provider.onBackendReady())
                        .catch((error) => presentSidecarError(error, true));
        }
}

// This method is called when your extension is deactivated
export function deactivate() {
	sidecar?.dispose();
	logger.dispose();
}
