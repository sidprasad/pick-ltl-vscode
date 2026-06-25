import * as assert from 'assert';

// You can import and use all API from the 'vscode' module
// as well as import your extension to test it
import * as vscode from 'vscode';
import { micromambaAssetName } from '../micromamba';
import { extractExpressibilityWarnings, WARNING_CONFIDENCE_THRESHOLD } from '../ltlService';

suite('Extension Test Suite', () => {
	vscode.window.showInformationMessage('Start all tests.');

	test('Sample test', () => {
		assert.strictEqual(-1, [1, 2, 3].indexOf(5));
		assert.strictEqual(-1, [1, 2, 3].indexOf(0));
	});
});

suite('micromamba bootstrap', () => {
	test('maps supported platform/arch pairs to release assets', () => {
		assert.strictEqual(micromambaAssetName('darwin', 'arm64'), 'micromamba-osx-arm64');
		assert.strictEqual(micromambaAssetName('darwin', 'x64'), 'micromamba-osx-64');
		assert.strictEqual(micromambaAssetName('linux', 'x64'), 'micromamba-linux-64');
		assert.strictEqual(micromambaAssetName('linux', 'arm64'), 'micromamba-linux-aarch64');
		assert.strictEqual(micromambaAssetName('win32', 'x64'), 'micromamba-win-64.exe');
	});

	test('returns null for unsupported platform/arch', () => {
		assert.strictEqual(micromambaAssetName('darwin', 'ia32'), null);
		assert.strictEqual(micromambaAssetName('win32', 'arm64'), null);
		assert.strictEqual(micromambaAssetName('freebsd', 'x64'), null);
	});
});

suite('expressibility warning confidence gate', () => {
	test('keeps only high-confidence structured warnings', () => {
		const out = extractExpressibilityWarnings([
			{ issue: 'needs unbounded counting', confidence: 0.9 },
			{ issue: 'might be a bit tricky', confidence: 0.4 }
		]);
		assert.deepStrictEqual(out, ['needs unbounded counting']);
	});

	test('drops bare strings (they carry no confidence signal)', () => {
		assert.deepStrictEqual(extractExpressibilityWarnings(['needs counting']), []);
	});

	test('threshold is inclusive; just below is dropped', () => {
		assert.deepStrictEqual(
			extractExpressibilityWarnings([{ issue: 'x', confidence: WARNING_CONFIDENCE_THRESHOLD }]),
			['x']
		);
		assert.deepStrictEqual(
			extractExpressibilityWarnings([{ issue: 'x', confidence: WARNING_CONFIDENCE_THRESHOLD - 0.01 }]),
			[]
		);
	});

	test('returns [] for non-array input', () => {
		assert.deepStrictEqual(extractExpressibilityWarnings(undefined), []);
		assert.deepStrictEqual(extractExpressibilityWarnings(null), []);
		assert.deepStrictEqual(extractExpressibilityWarnings('nope'), []);
	});

	test('dedupes and caps at 3', () => {
		const out = extractExpressibilityWarnings([
			{ issue: 'a', confidence: 0.9 },
			{ issue: 'a', confidence: 0.95 },
			{ issue: 'b', confidence: 0.9 },
			{ issue: 'c', confidence: 0.9 },
			{ issue: 'd', confidence: 0.9 }
		]);
		assert.deepStrictEqual(out, ['a', 'b', 'c']);
	});

	test('respects a custom threshold', () => {
		assert.deepStrictEqual(
			extractExpressibilityWarnings([{ issue: 'x', confidence: 0.7 }], 0.6),
			['x']
		);
	});
});
