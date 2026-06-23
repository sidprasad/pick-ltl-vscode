/**
 * Small shared types for the PICK webview flow. These used to live in
 * pickController.ts; they are kept here so the provider does not depend on the
 * (now-removed) in-TS controller.
 */

export enum WordClassification {
  ACCEPT = 'accept',
  REJECT = 'reject',
  UNSURE = 'unsure'
}

export interface WordClassificationRecord {
  word: string;
  classification: WordClassification;
  timestamp: number;
  matchingFormulas: string[];
  source: 'pair' | 'direct';
}
