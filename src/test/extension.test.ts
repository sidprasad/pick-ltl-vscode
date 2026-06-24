import * as assert from 'assert';

// You can import and use all API from the 'vscode' module
// as well as import your extension to test it
import * as vscode from 'vscode';
import { micromambaAssetName } from '../micromamba';

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
