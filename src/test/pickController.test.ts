import * as assert from 'assert';
import { PickController, PickState, WordClassification } from '../pickController';

/**
 * Controller tests for the LTL variant of PICK. Candidates are LTL formulas and
 * "words" are Spot lasso trace strings. These exercise the (domain-agnostic)
 * PICK state machine against the real @sidprasad/ltl-ts engine.
 *
 * Runs under @vscode/test-cli (the controller needs the `vscode` API). Trace
 * facts used below (verified against the engine):
 *   satisfies('cycle{a}', 'G a')      === true
 *   satisfies('!a;cycle{a}', 'G a')   === false   (a fails at position 0)
 *   satisfies('!a;cycle{a}', 'F a')   === true    (a holds eventually)
 *   satisfies('cycle{!a}', 'F a')     === false   (a never holds)
 */
suite('PickController (LTL) Test Suite', () => {
  let controller: PickController;

  setup(() => {
    controller = new PickController();
  });

  const acceptDirect = (trace: string) =>
    controller.classifyDirectWords([{ word: trace, classification: WordClassification.ACCEPT }]);
  const rejectDirect = (trace: string) =>
    controller.classifyDirectWords([{ word: trace, classification: WordClassification.REJECT }]);

  test('Initial state should be INITIAL', () => {
    assert.strictEqual(controller.getState(), PickState.INITIAL);
  });

  test('generateCandidates transitions to VOTING with correct counts', async () => {
    await controller.generateCandidates('eventually a', ['G a', 'F a', 'a U b']);

    assert.strictEqual(controller.getState(), PickState.VOTING);
    assert.strictEqual(controller.getActiveCandidateCount(), 3);

    const status = controller.getStatus();
    assert.strictEqual(status.totalCandidates, 3);
    assert.strictEqual(status.activeCandidates, 3);
  });

  test('classifications are recorded in history', async () => {
    await controller.generateCandidates('test', ['G a', 'F a']);
    acceptDirect('cycle{a}');
    rejectDirect('cycle{!a}');

    const history = controller.getWordHistory();
    assert.strictEqual(history.length, 2);
    assert.strictEqual(history[0].word, 'cycle{a}');
    assert.strictEqual(history[0].classification, WordClassification.ACCEPT);
    assert.strictEqual(history[1].classification, WordClassification.REJECT);
  });

  test('ACCEPT vote: matchers gain positive, non-matchers gain negative and are eliminated', async () => {
    await controller.generateCandidates('a eventually holds', ['G a', 'F a']);
    controller.setThreshold(1); // deterministic elimination

    // '!a;cycle{a}' satisfies F a but NOT G a.
    acceptDirect('!a;cycle{a}');

    const status = controller.getStatus();
    const ga = status.candidateDetails.find(c => c.pattern === 'G a')!;
    const fa = status.candidateDetails.find(c => c.pattern === 'F a')!;

    assert.strictEqual(ga.eliminated, true, 'G a should be eliminated (failed to accept the trace)');
    assert.strictEqual(fa.eliminated, false, 'F a should survive');
    assert.ok(fa.positiveVotes >= 1, 'F a should have a positive vote');

    // One survivor with a positive vote -> converge.
    assert.strictEqual(controller.getState(), PickState.FINAL_RESULT);
    assert.strictEqual(controller.getFinalFormula(), 'F a');
  });

  test('REJECT vote: a candidate that accepts a rejected trace is penalized', async () => {
    await controller.generateCandidates('a never holds at start', ['F a']);
    controller.setThreshold(1);

    // 'cycle{a}' satisfies F a, but the user says this trace should NOT hold.
    rejectDirect('cycle{a}');

    const status = controller.getStatus();
    const fa = status.candidateDetails.find(c => c.pattern === 'F a')!;
    assert.strictEqual(fa.eliminated, true, 'F a should be eliminated after wrongly accepting a rejected trace');

    // No survivors -> final result with no formula.
    assert.strictEqual(controller.getState(), PickState.FINAL_RESULT);
    assert.strictEqual(controller.getFinalFormula(), null);
  });

  test('UNSURE classifications do not change votes', async () => {
    await controller.generateCandidates('test', ['G a', 'F a']);
    controller.classifyDirectWords([{ word: 'cycle{a}', classification: WordClassification.UNSURE }]);

    const status = controller.getStatus();
    for (const c of status.candidateDetails) {
      assert.strictEqual(c.positiveVotes, 0);
      assert.strictEqual(c.negativeVotes, 0);
    }
  });

  test('generateNextPair yields two distinct, classifiable traces', async () => {
    await controller.generateCandidates('distinguish G a from F a', ['G a', 'F a']);

    const pair = await controller.generateNextPair();
    assert.ok(pair.word1.length > 0 && pair.word2.length > 0);
    assert.notStrictEqual(pair.word1, pair.word2);

    // Pair-flow classification should not throw and should record history.
    controller.classifyWord(pair.word1, WordClassification.ACCEPT);
    controller.classifyWord(pair.word2, WordClassification.REJECT);
    assert.strictEqual(controller.getWordHistory().length, 2);
  });

  test('updateClassification replays votes from scratch', async () => {
    await controller.generateCandidates('a eventually holds', ['G a', 'F a']);
    controller.setThreshold(1);

    acceptDirect('!a;cycle{a}'); // eliminates G a (see above)
    assert.strictEqual(controller.getStatus().candidateDetails.find(c => c.pattern === 'G a')!.eliminated, true);

    // Flip that classification to UNSURE -> G a should no longer be eliminated.
    controller.updateClassification(0, WordClassification.UNSURE);
    const ga = controller.getStatus().candidateDetails.find(c => c.pattern === 'G a')!;
    assert.strictEqual(ga.eliminated, false, 'G a should recover after the classification is flipped to UNSURE');
    assert.strictEqual(ga.negativeVotes, 0);
  });

  test('reset returns to INITIAL', async () => {
    await controller.generateCandidates('test', ['G a', 'F a']);
    controller.reset();
    assert.strictEqual(controller.getState(), PickState.INITIAL);
    assert.strictEqual(controller.getActiveCandidateCount(), 0);
  });
});
