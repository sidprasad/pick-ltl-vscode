/**
 * Hand-written SPOT lasso-trace -> SVG render-data parser.
 *
 * The Python/SPOT backend produces trace strings in Spot's lasso syntax
 * ("p0;p1;cycle{c0;c1}"); this turns one into the `{prefix, cycle}` shape the
 * webview renderer (media/vendor/tracerenderer.js) consumes. Keeping this in the
 * extension means we ship no LTL engine — SPOT stays the single source of truth
 * for the traces themselves, and we only format them for display.
 */

/** Shape consumed by the SVG trace renderer. */
export interface RenderData {
  prefix: Array<{ label: string }>;
  cycle: Array<{ label: string }>;
}

/** Convert one state ("! r & b", "a&b", "1") into a renderer label ("¬r b"). */
function stateToLabel(state: string): string {
  const s = state.trim();
  if (s === '' || s === '1' || s === 'true') {
    return '';
  }
  return s
    .split('&')
    .map(part => part.trim())
    .filter(part => part.length > 0)
    .map(lit => (lit.startsWith('!') ? '¬' + lit.slice(1).trim() : lit))
    .join(' ');
}

/**
 * Parse a Spot lasso trace into render data. Returns null if the string is empty
 * or has no cycle (every ultimately-periodic word must have one).
 */
export function traceToRenderData(word: string): RenderData | null {
  if (typeof word !== 'string' || word.trim().length === 0) {
    return null;
  }
  try {
    let prefixPart = word;
    let cyclePart = '';
    const marker = 'cycle{';
    const ci = word.indexOf(marker);
    if (ci >= 0) {
      prefixPart = word.slice(0, ci);
      const inner = word.slice(ci + marker.length);
      const close = inner.lastIndexOf('}');
      cyclePart = close >= 0 ? inner.slice(0, close) : inner;
    }
    const toStates = (part: string): Array<{ label: string }> =>
      part
        .split(';')
        .map(s => s.trim())
        .filter(s => s.length > 0)
        .map(s => ({ label: stateToLabel(s) }));
    const prefix = toStates(prefixPart);
    const cycle = toStates(cyclePart);
    if (cycle.length === 0) {
      return null;
    }
    return { prefix, cycle };
  } catch {
    return null;
  }
}
