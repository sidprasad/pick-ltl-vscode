import * as assert from 'assert';
import { createLtlAnalyzer } from '../ltlAnalyzer';

suite('LtlAnalyzer Test Suite', () => {
  let analyzer: ReturnType<typeof createLtlAnalyzer>;

  suiteSetup(async () => {
    analyzer = createLtlAnalyzer();
    await analyzer.init();
  });

  test('verifyMatch: trace membership', () => {
    assert.strictEqual(analyzer.verifyMatch('cycle{a}', 'G a'), true);
    assert.strictEqual(analyzer.verifyMatch('!a;cycle{a}', 'G a'), false);
    assert.strictEqual(analyzer.verifyMatch('!a;cycle{a}', 'F a'), true);
  });

  test('isValidFormula: LTL syntax validation', () => {
    assert.strictEqual(analyzer.isValidFormula('G (a -> F b)'), true);
    assert.strictEqual(analyzer.isValidFormula('a U b'), true);
    assert.strictEqual(analyzer.isValidFormula('(a'), false);
    assert.strictEqual(analyzer.isValidFormula('-> b'), false);
  });

  test('areEquivalent', async () => {
    assert.strictEqual(await analyzer.areEquivalent('G a', '!F !a'), true);
    assert.strictEqual(await analyzer.areEquivalent('a -> b', '!a | b'), true);
    assert.strictEqual(await analyzer.areEquivalent('G a', 'F a'), false);
  });

  test('countTracesInANotInB: distinguishability proxy', async () => {
    // G a implies F a, so |G a \ F a| == 0
    assert.strictEqual(await analyzer.countTracesInANotInB('G a', 'F a'), 0n);
    // F a does NOT imply G a, so |F a \ G a| > 0
    assert.strictEqual(await analyzer.countTracesInANotInB('F a', 'G a'), 1n);
  });

  test('generateTwoDistinguishingTraces', async () => {
    const r = await analyzer.generateTwoDistinguishingTraces(['F a', 'G a']);
    assert.strictEqual(r.words.length, 2);
    assert.notStrictEqual(r.words[0], r.words[1]);
  });

  test('generateTracePair: one satisfies, one does not', async () => {
    const p = await analyzer.generateTracePair('F a');
    assert.ok(analyzer.verifyMatch(p.wordIn, 'F a'), 'wordIn should satisfy F a');
    assert.ok(!analyzer.verifyMatch(p.wordNotIn, 'F a'), 'wordNotIn should not satisfy F a');
  });

  test('synthesizeFormula: learn from classified traces', async () => {
    const f = await analyzer.synthesizeFormula(['a'], ['cycle{a}'], ['cycle{!a}']);
    assert.ok(f, 'should synthesize a formula');
    assert.ok(analyzer.verifyMatch('cycle{a}', f as string));
    assert.ok(!analyzer.verifyMatch('cycle{!a}', f as string));
  });
});
