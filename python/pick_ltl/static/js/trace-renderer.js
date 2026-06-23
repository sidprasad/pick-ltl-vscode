/**
 * LTL SPOT Trace Renderer with Mermaid Diagrams
 * 
 * This module provides functionality to parse SPOT traces and render them
 * as Mermaid flowcharts (linked list style) with cycle back-arrows.
 * 
 * SPOT trace format: prefix;cycle{...}
 * Example: "a;!b;cycle{a&b;!a}" 
 * Renders as: a → ¬b → a∧b → ¬a → (back to a∧b)
 */

class TraceRenderer {
    constructor() {
        this.stateIdCounter = 0;
        this.mermaidReady = null;
    }

    /**
     * Parse a SPOT trace string into structured data
     * @param {string} traceStr - The SPOT trace string
     * @returns {Object} Parsed trace with prefix and cycle states
     */
    parseTrace(traceStr) {
        const trimmed = traceStr.trim();
        if (!trimmed) {
            return { prefix: [], cycle: [], hasCycle: false };
        }

        // Split on 'cycle' to separate prefix and cycle parts
        const parts = trimmed.split('cycle');
        const prefixPart = parts[0];
        const cyclePart = parts.length > 1 ? parts[1] : '';

        // Parse prefix states (semicolon-separated)
        const prefixStates = prefixPart
            .split(';')
            .map(s => s.trim())
            .filter(s => s.length > 0)
            .map(state => this.parseState(state));

        // Parse cycle states if present
        let cycleStates = [];
        let hasCycle = false;
        
        if (cyclePart) {
            hasCycle = true;
            // Extract content between { and }
            const cycleMatch = cyclePart.match(/\{([^}]*)\}/);
            if (cycleMatch) {
                const cycleContent = cycleMatch[1];
                cycleStates = cycleContent
                    .split(';')
                    .map(s => s.trim())
                    .filter(s => s.length > 0)
                    .map(state => this.parseState(state));
            }
        }

        return {
            prefix: prefixStates,
            cycle: cycleStates,
            hasCycle: hasCycle
        };
    }

    /**
     * Parse a single state string into a NodeRepr-like object
     * @param {string} stateStr - State string like "a&!b" or "1" or "0"
     * @returns {Object} Parsed state object with ID and display
     */
    parseState(stateStr) {
        const id = `state_${++this.stateIdCounter}`;
        
        // Handle special cases
        if (stateStr === '1') {
            return { id, display: '⊤', raw: stateStr };
        }
        if (stateStr === '0') {
            return { id, display: '⊥', raw: stateStr };
        }
        if (stateStr === '') {
            return { id, display: '∅', raw: stateStr };
        }

        // Parse conjunctions and negations (similar to Python NodeRepr)
        const literals = stateStr.split('&').map(lit => lit.trim());
        const processedLiterals = literals.map(lit => {
            if (lit.startsWith('!')) {
                let litc = lit.slice(1).trim();
                return `**${litc}**.OFF`;
            } 
            return `**${lit}**.ON`;
        });

        const display = processedLiterals
                        .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()))
                        .join(' \n ');
        
        return {
            id,
            display,
            raw: stateStr
        };
    }

    /**
     * Generate Mermaid code for a parsed trace (flowchart style)
     * @param {Object} trace - Parsed trace object
     * @param {Object} options - Options for code generation
     * @returns {string} Mermaid diagram code
     */
    generateMermaidCode(trace, options = {}) {
        const fontSize = options.fontSize || 30;
        const isEnlarged = options.enlarged || false;
        
        // Per-diagram mermaid init: set theme to 'neutral' and font size
        // Use different approaches for different font sizes
        let initBlock;
        if (isEnlarged) {
            initBlock = `
---
config:
    theme: neutral
    flowchart:
        htmlLabels: true
    themeVariables:
        primaryTextColor: "#000000"
        primaryColor: "#ffffff"
        primaryBorderColor: "#000000"
        fontSize: "${fontSize}px"
---
`;
        } else {
            initBlock = `
---
config:
    theme: neutral
    flowchart:
        htmlLabels: true
---
`;
        }
        
        if (trace.prefix.length === 0 && trace.cycle.length === 0) {
            return initBlock + 'flowchart LR;\nA["Empty trace"];';
        }

        let mermaidCode = initBlock + 'flowchart LR;\n';
        const allStates = [...trace.prefix, ...trace.cycle];

        // Create nodes
        allStates.forEach(state => {
            let display = state.display.replace(/"/g, '\\"'); // Escape quotes
            display = "`" + display + "`"; // Use backticks for better formatting in Mermaid
            mermaidCode += `${state.id}["${display}"];\n`;
        });

        // Create connections for prefix
        for (let i = 0; i < trace.prefix.length - 1; i++) {
            mermaidCode += `${trace.prefix[i].id}-->${trace.prefix[i + 1].id};\n`;
        }

        // Create connections for cycle
        if (trace.hasCycle && trace.cycle.length > 0) {
            // Connect last prefix to first cycle (if prefix exists)
            if (trace.prefix.length > 0) {
                mermaidCode += `${trace.prefix[trace.prefix.length - 1].id}-->${trace.cycle[0].id};\n`;
            }

            // Connect cycle states
            for (let i = 0; i < trace.cycle.length - 1; i++) {
                mermaidCode += `${trace.cycle[i].id}-->${trace.cycle[i + 1].id};\n`;
            }

            // Add back-arrow for cycle (to first cycle node)
            if (trace.cycle.length >= 1) {
                mermaidCode += `${trace.cycle[trace.cycle.length - 1].id}-->${trace.cycle[0].id};\n`;
            }
        }

        return mermaidCode;
    }

    /**
     * Render a parsed trace as a Mermaid diagram with magnification
     * @param {Object} trace - Parsed trace object
     * @param {Object} options - Rendering options
     * @returns {string} HTML string with Mermaid diagram and magnification
     */
    renderTrace(trace, options = {}) {
        const mermaidCode = this.generateMermaidCode(trace);
        const traceId = `trace_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
        
        return `
            <div class="mermaid-trace" data-trace-id="${traceId}" title="Click to enlarge">
                <div class="mermaid-trace-magnify-icon">🔍</div>
                <pre class="mermaid">
${mermaidCode}
                </pre>
            </div>
        `;
    }

    /**
     * Create and show magnification modal
     * @param {string} mermaidCode - The Mermaid diagram code (will be regenerated with larger font)
     * @param {string} originalTrace - The original trace string
     */
    showMagnifiedTrace(mermaidCode, originalTrace) {
        // Remove existing modal if present
        const existingModal = document.getElementById('mermaid-modal');
        if (existingModal) {
            existingModal.remove();
        }

        // Parse the trace and generate larger Mermaid code for the modal
        const parsedTrace = this.parseTrace(originalTrace);
        const enlargedMermaidCode = this.generateMermaidCode(parsedTrace, { fontSize: 48, enlarged: true });

        // Create modal HTML
        const modalHtml = `
            <div id="mermaid-modal" class="mermaid-modal-overlay">
                <div class="mermaid-modal-content">
                    <div class="mermaid-modal-header">
                        <h5 class="mermaid-modal-title">Trace Diagram</h5>
                        <button class="mermaid-modal-close" aria-label="Close">&times;</button>
                    </div>
                    <div class="mermaid-modal-body">
                        <div class="mermaid-modal-trace">
                            <pre class="mermaid">
${enlargedMermaidCode}
                            </pre>
                        </div>
                        <div class="mermaid-modal-original">
                            <strong>Original Trace:</strong>
                            <code>${originalTrace}</code>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Inject modal into DOM
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const modal = document.getElementById('mermaid-modal');
        const closeBtn = modal.querySelector('.mermaid-modal-close');

        // Close modal handlers
        const closeModal = () => {
            // Restore body scroll before removing modal
            document.body.style.overflow = '';
            modal.remove();
        };

        closeBtn.addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        // Close on Escape key
        document.addEventListener('keydown', function escHandler(e) {
            if (e.key === 'Escape') {
                closeModal();
                document.removeEventListener('keydown', escHandler);
            }
        });

        // Force Mermaid to render the enlarged diagram with custom config
        setTimeout(() => {
            if (typeof mermaid !== 'undefined') {
                const mermaidPre = modal.querySelector('.mermaid');
                if (mermaidPre) {
                    // Initialize with larger font configuration for this specific diagram
                    mermaid.init({
                        theme: 'neutral',
                        flowchart: { 
                            htmlLabels: true,
                            fontSize: '48px'
                        },
                        themeVariables: {
                            fontSize: '48px',
                            primaryTextColor: '#000000'
                        }
                    }, mermaidPre);
                }
            }
        }, 100);

        // Prevent body scroll when modal is open
        document.body.style.overflow = 'hidden';
    }

    /**
     * Apply trace rendering to all elements with ltl-spot-trace class
     * @param {Object} options - Rendering options
     */
    renderAllTraces(options = {}) {
        return this.ensureMermaidLoaded()
            .then(() => {
                const traceElements = document.querySelectorAll('.ltl-spot-trace');

                traceElements.forEach(element => {
            // Get the original trace from data-word
            let traceText = element.getAttribute('data-word');
            
            // If data-word is missing or empty, try to extract from textContent (but only if not already rendered)
            if (!traceText || traceText.trim() === '') {
                if (!element.classList.contains('ltl-trace-rendered')) {
                    // Fallback: Decode HTML entities from textContent (e.g., &amp; -> &)
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = element.textContent;
                    traceText = tempDiv.textContent || tempDiv.innerText;
                    console.warn('Using fallback trace from textContent for element:', element, 'Trace:', traceText);
                } else {
                    console.warn('Skipping already-rendered element with no data-word:', element);
                    return;
                }
            }
            
            // If still no trace, skip
            if (!traceText || traceText.trim() === '') {
                console.warn('No trace found for element:', element);
                return;
            }
            
            // If already rendered, skip to prevent overwriting
            if (element.classList.contains('ltl-trace-rendered')) {
                return;
            }
            
            const parsed = this.parseTrace(traceText);
            const rendered = this.renderTrace(parsed, options);
            const mermaidCode = this.generateMermaidCode(parsed);
            
            // Set attributes correctly (only once)
            element.setAttribute('data-original', traceText);  // Original SPOT trace
            element.setAttribute('data-mermaid', mermaidCode);  // Generated Mermaid code
            
            element.innerHTML = rendered;
            element.classList.add('ltl-trace-rendered');
            
            // Add click handler for magnification
            element.addEventListener('click', () => {
                this.showMagnifiedTrace(mermaidCode, traceText);
            });
            
            if (typeof mermaid !== 'undefined') {
                const mermaidPre = element.querySelector('.mermaid');
                if (mermaidPre) {
                    mermaid.init(undefined, mermaidPre);
                }
            }
        });
            })
            .catch(error => {
                console.error('Failed to load Mermaid for trace rendering.', error);
            });
    }

    /**
     * Ensure Mermaid.js is loaded
     */
    ensureMermaidLoaded() {
        if (typeof mermaid !== 'undefined') {
            return Promise.resolve(mermaid);
        }
        if (this.mermaidReady) {
            return this.mermaidReady;
        }

        this.mermaidReady = new Promise((resolve, reject) => {
            const existing = document.querySelector('script[data-pick-ltl-mermaid="true"]');
            if (existing) {
                existing.addEventListener('load', () => resolve(mermaid), { once: true });
                existing.addEventListener('error', reject, { once: true });
                return;
            }

            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
            script.dataset.pickLtlMermaid = 'true';
            script.onload = () => {
                mermaid.initialize({
                    startOnLoad: true,
                    theme: 'neutral',
                    flowchart: { htmlLabels: true },
                });
                resolve(mermaid);
            };
            script.onerror = reject;
            document.head.appendChild(script);
        });

        return this.mermaidReady;
    }

    /**
     * Initialize the trace renderer on page load
     * @param {Object} options - Default rendering options
     */
    static init(options = {}) {
        const renderer = new TraceRenderer();
        
        // Auto-render on DOM ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                renderer.renderAllTraces(options);
            });
        } else {
            renderer.renderAllTraces(options);
        }

        return renderer;
    }
}

// CSS styles for Mermaid traces and magnification
const TRACE_STYLES = `
<style>
.mermaid-trace {
    margin: 0.5rem 0;
    padding: 0.5rem;
    border: 1px solid #dee2e6;
    border-radius: 0.375rem;
    background-color: #ffffff;
    transition: all 0.2s ease;
    cursor: pointer;
    position: relative;
}

.mermaid-trace:hover {
    border-color: #0d6efd;
    box-shadow: 0 0 0 0.2rem rgba(13, 110, 253, 0.25);
    background-color: #f8f9fa;
}

.mermaid-trace-magnify-icon {
    position: absolute;
    top: 0.25rem;
    right: 0.25rem;
    opacity: 0;
    transition: opacity 0.2s ease;
    font-size: 0.75rem;
    color: #6c757d;
    pointer-events: none;
}

.mermaid-trace:hover .mermaid-trace-magnify-icon {
    opacity: 0.6;
}

.mermaid-trace pre {
    margin: 0;
    white-space: pre-wrap;
}

/* Magnification Modal Styles */
.mermaid-modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(0, 0, 0, 0.7);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 9999;
    animation: fadeIn 0.3s ease;
}

.mermaid-modal-content {
    background-color: white;
    border-radius: 0.5rem;
    box-shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
    max-width: 95vw;
    max-height: 95vh;
    width: 1200px;
    display: flex;
    flex-direction: column;
    animation: slideIn 0.3s ease;
}

.mermaid-modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    border-bottom: 1px solid #dee2e6;
}

.mermaid-modal-title {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 500;
    color: #212529;
}

.mermaid-modal-close {
    background: none;
    border: none;
    font-size: 1.5rem;
    color: #6c757d;
    cursor: pointer;
    padding: 0;
    width: 2rem;
    height: 2rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 0.25rem;
    transition: all 0.2s ease;
}

.mermaid-modal-close:hover {
    background-color: #f8f9fa;
    color: #212529;
}

.mermaid-modal-body {
    padding: 2rem;
    overflow-y: auto;
    flex: 1;
}

.mermaid-modal-trace {
    margin-bottom: 1.5rem;
}

.mermaid-modal-trace pre {
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 0.25rem;
    padding: 1rem;
    font-size: 0.875rem;
    line-height: 1.5;
}

/* Force larger font sizes in modal Mermaid diagrams */
.mermaid-modal-trace .mermaid svg {
    font-size: 48px !important;
}

.mermaid-modal-trace .mermaid svg text {
    font-size: 48px !important;
}

.mermaid-modal-trace .mermaid svg .node rect,
.mermaid-modal-trace .mermaid svg .node circle,
.mermaid-modal-trace .mermaid svg .node ellipse,
.mermaid-modal-trace .mermaid svg .node polygon {
    stroke-width: 3px !important;
}

.mermaid-modal-trace .mermaid svg .edgePath path {
    stroke-width: 3px !important;
}

.mermaid-modal-original {
    background-color: #f8f9fa;
    border: 1px solid #dee2e6;
    border-radius: 0.25rem;
    padding: 0.75rem;
    font-size: 1.4rem;
}

.mermaid-modal-original code {
    background-color: #e9ecef;
    padding: 0.125rem 0.25rem;
    border-radius: 0.125rem;
    font-family: 'Courier New', monospace;
    word-break: break-all;
    font-size: 1.4rem;
}

/* Animations */
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@keyframes slideIn {
    from { 
        opacity: 0;
        transform: scale(0.9) translateY(-20px);
    }
    to { 
        opacity: 1;
        transform: scale(1) translateY(0);
    }
}

/* Responsive design */
@media (max-width: 768px) {
    .mermaid-trace {
        font-size: 0.8rem;
    }
    
    .mermaid-modal-content {
        width: 95vw;
        max-height: 95vh;
    }
    
    .mermaid-modal-header {
        padding: 0.75rem 1rem;
    }
    
    .mermaid-modal-body {
        padding: 1rem;
    }
    
    .mermaid-modal-title {
        font-size: 1.1rem;
    }
}
</style>
`;

// Inject styles into document head
if (typeof document !== 'undefined') {
    document.head.insertAdjacentHTML('beforeend', TRACE_STYLES);
}

// Make TraceRenderer available globally
if (typeof window !== 'undefined') {
    window.TraceRenderer = TraceRenderer;
}

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TraceRenderer;
}
