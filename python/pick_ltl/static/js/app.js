const SESSION_STORAGE_KEY = "pick-ltl-session";
const PROMPTS_STORAGE_KEY = "pick-ltl-prompts";

let appState = null;
let settings = null;

const statusBar = document.getElementById("statusBar");
const promptInput = document.getElementById("promptInput");
const workspaceSection = document.getElementById("workspaceSection");
const pairSection = document.getElementById("pairSection");
const resultSection = document.getElementById("resultSection");
const atomsList = document.getElementById("atomsList");
const candidateList = document.getElementById("candidateList");
const historyList = document.getElementById("historyList");
const currentPrompt = document.getElementById("currentPrompt");

document.addEventListener("DOMContentLoaded", init);

async function init() {
  bindEvents();
  await loadSettings();
  restoreSession();
  render();
}

function bindEvents() {
  document.getElementById("generateBtn").addEventListener("click", generateSession);
  document.getElementById("refineBtn").addEventListener("click", refineSession);
  document.getElementById("resultRefineBtn").addEventListener("click", refineSession);
  document.getElementById("startFreshBtn").addEventListener("click", resetSession);
  document.getElementById("resultStartFreshBtn").addEventListener("click", resetSession);
  document.getElementById("submitExamplesBtn").addEventListener("click", submitExamples);
  document.getElementById("openSettingsBtn").addEventListener("click", () => toggleSettings(true));
  document.getElementById("closeSettingsBtn").addEventListener("click", () => toggleSettings(false));
  document.getElementById("saveSettingsBtn").addEventListener("click", saveSettings);
  document.getElementById("testSettingsBtn").addEventListener("click", testSettings);
  document.getElementById("refreshModelsBtn").addEventListener("click", refreshModels);
  document.getElementById("exportBtn").addEventListener("click", exportSession);
  document.getElementById("importBtn").addEventListener("click", () => document.getElementById("importInput").click());
  document.getElementById("importInput").addEventListener("change", importSession);
  document.querySelectorAll(".vote").forEach((button) => {
    button.addEventListener("click", () => submitClassification(button.dataset.trace, button.dataset.classification));
  });
}

function setStatus(message, isError = false) {
  if (!message) {
    statusBar.classList.add("hidden");
    statusBar.textContent = "";
    statusBar.style.borderColor = "";
    return;
  }
  statusBar.classList.remove("hidden");
  statusBar.textContent = message;
  statusBar.style.borderColor = isError ? "var(--danger)" : "";
}

async function api(path, payload, method = "POST") {
  const options = { method, headers: {} };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

async function loadSettings() {
  settings = await api("/api/settings", undefined, "GET");
  fillSettingsForm(settings);
  await refreshModels();
}

function currentProvider() {
  return {
    kind: document.getElementById("providerKind").value,
    base_url: document.getElementById("providerBaseUrl").value.trim(),
    model: document.getElementById("providerModel").value.trim(),
    api_key: document.getElementById("providerApiKey").value.trim(),
    timeout_seconds: Number(document.getElementById("providerTimeout").value || 60),
  };
}

function fillSettingsForm(data) {
  document.getElementById("providerKind").value = data.kind || "ollama";
  document.getElementById("providerBaseUrl").value = data.base_url || "";
  document.getElementById("providerModel").value = data.model || "";
  document.getElementById("providerApiKey").value = data.api_key || "";
  document.getElementById("providerTimeout").value = data.timeout_seconds || 60;
}

function toggleSettings(open) {
  document.getElementById("settingsModal").classList.toggle("hidden", !open);
}

async function saveSettings() {
  const saved = await api("/api/settings", currentProvider());
  settings = saved;
  fillSettingsForm(saved);
  await refreshModels();
  setStatus("Settings saved.");
}

async function testSettings() {
  try {
    const data = await api("/api/settings/test", currentProvider());
    setStatus(`Connection ok. Found ${data.models.length} model(s).`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function refreshModels() {
  const modelList = document.getElementById("modelList");
  try {
    const data = await api("/api/models", currentProvider());
    modelList.innerHTML = data.models.length
      ? data.models.map((model) => `<div class="atom-item">${escapeHtml(model)}</div>`).join("")
      : '<div class="atom-item">No models reported by the provider.</div>';
  } catch (error) {
    modelList.innerHTML = `<div class="atom-item">${escapeHtml(error.message)}</div>`;
  }
}

async function generateSession() {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    setStatus("Enter a prompt first.", true);
    return;
  }

  try {
    setStatus("Generating initial formulas...");
    const provider = currentProvider();
    const seed = await api("/api/seed/generate", { prompt, provider });
    setStatus("Building candidate set...");
    appState = await api("/api/candidates/build", { prompt, provider, seeds: seed.seeds || [seed] });
    rememberPrompt(prompt);
    if (appState.mode === "voting") {
      appState = await api("/api/session/next-pair", { session: appState });
    }
    persistSession();
    render();
    setStatus(appState.message || "Candidate set ready.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function refineSession() {
  if (!appState) {
    return;
  }
  try {
    setStatus("Refining from the updated prompt...");
    appState = await api("/api/session/refine", { session: appState, prompt: promptInput.value.trim() });
    if (appState.mode === "voting") {
      appState = await api("/api/session/next-pair", { session: appState });
    }
    persistSession();
    render();
    setStatus(appState.message || "Session refined.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function submitClassification(which, classification) {
  if (!appState || !appState.current_pair) {
    return;
  }
  const trace = which === "a" ? appState.current_pair.trace1 : appState.current_pair.trace2;
  try {
    appState = await api("/api/session/classify", {
      session: appState,
      trace,
      classification,
      source: "pair",
    });
    if (appState.mode === "voting" && !appState.current_pair && !appState.exhausted) {
      appState = await api("/api/session/next-pair", { session: appState });
    }
    persistSession();
    render();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function submitExamples() {
  if (!appState) {
    return;
  }
  const accept_traces = document.getElementById("acceptExamples").value.split("\n");
  const reject_traces = document.getElementById("rejectExamples").value.split("\n");
  try {
    appState = await api("/api/session/examples", { session: appState, accept_traces, reject_traces });
    document.getElementById("acceptExamples").value = "";
    document.getElementById("rejectExamples").value = "";
    if (appState.mode === "voting" && !appState.current_pair && !appState.exhausted) {
      appState = await api("/api/session/next-pair", { session: appState });
    }
    persistSession();
    render();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function submitReclassification(historyIndex, classification) {
  if (!appState) {
    return;
  }
  try {
    setStatus("Recalculating from updated classification...");
    appState = await api("/api/session/reclassify", {
      session: appState,
      history_index: Number(historyIndex),
      classification,
    });
    if (appState.mode === "voting" && !appState.current_pair && !appState.exhausted) {
      appState = await api("/api/session/next-pair", { session: appState });
    }
    persistSession();
    render();
    setStatus(appState.message || "Classification updated.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function chooseCandidate(formula) {
  try {
    appState = await api("/api/session/finalize", { session: appState, formula });
    persistSession();
    render();
  } catch (error) {
    setStatus(error.message, true);
  }
}

function resetSession() {
  appState = null;
  promptInput.value = "";
  document.getElementById("acceptExamples").value = "";
  document.getElementById("rejectExamples").value = "";
  localStorage.removeItem(SESSION_STORAGE_KEY);
  render();
  setStatus("");
}

function exportSession() {
  if (!appState) {
    setStatus("Nothing to export yet.", true);
    return;
  }
  const blob = new Blob([JSON.stringify(appState, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "pick-ltl-session.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

async function importSession(event) {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    appState = await api("/api/session/import", { session: data });
    promptInput.value = appState.prompt || "";
    persistSession();
    render();
    setStatus("Session imported.");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    event.target.value = "";
  }
}

function restoreSession() {
  const raw = localStorage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return;
  }
  try {
    appState = JSON.parse(raw);
    promptInput.value = appState.prompt || "";
  } catch {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

function persistSession() {
  if (appState) {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(appState));
  }
}

function rememberPrompt(prompt) {
  const prompts = JSON.parse(localStorage.getItem(PROMPTS_STORAGE_KEY) || "[]");
  const next = [prompt, ...prompts.filter((item) => item !== prompt)].slice(0, 8);
  localStorage.setItem(PROMPTS_STORAGE_KEY, JSON.stringify(next));
}

function render() {
  const hasSession = Boolean(appState);
  document.getElementById("refineBtn").disabled = !hasSession;
  document.getElementById("resultRefineBtn").disabled = !hasSession;

  renderAtoms();
  renderCandidates();
  renderHistory();

  if (!hasSession) {
    workspaceSection.classList.add("hidden");
    resultSection.classList.add("hidden");
    currentPrompt.textContent = "";
    return;
  }

  currentPrompt.textContent = appState.prompt;
  promptInput.value = appState.prompt;

  if (appState.mode === "voting") {
    workspaceSection.classList.remove("hidden");
    resultSection.classList.add("hidden");
    renderPair();
  } else {
    workspaceSection.classList.remove("hidden");
    pairSection.classList.add("hidden");
    resultSection.classList.remove("hidden");
    renderResult();
  }

}

function renderAtoms() {
  const seeds = appState?.seeds?.length ? appState.seeds : (appState?.seed ? [appState.seed] : []);
  const atoms = [];
  const seen = new Set();
  seeds.forEach((seed) => {
    (seed.atoms || []).forEach((atom) => {
      if (seen.has(atom.name)) {
        return;
      }
      seen.add(atom.name);
      atoms.push(atom);
    });
  });

  if (!atoms.length) {
    atomsList.className = "atoms-list empty";
    atomsList.textContent = "No formula yet.";
    return;
  }
  atomsList.className = "atoms-list";
  atomsList.innerHTML = atoms
    .map((atom) => `<div class="atom-item"><strong>${escapeHtml(atom.name)}</strong>: ${escapeHtml(atom.meaning)}</div>`)
    .join("");
}

function renderCandidates() {
  if (!appState?.candidate_states?.length) {
    candidateList.className = "candidate-list empty";
    candidateList.textContent = "No candidates yet.";
    return;
  }
  candidateList.className = "candidate-list";
  candidateList.innerHTML = appState.candidate_states.map((candidate) => {
    const chooseButton = appState.exhausted && !candidate.eliminated
      ? `<button class="secondary pick-btn" data-formula="${escapeAttr(candidate.formula)}">Pick This One</button>`
      : "";
    const notes = candidate.explanation
      ? `
        <details class="candidate-notes">
          <summary>Show Notes</summary>
          <p class="prose">${escapeHtml(candidate.explanation)}</p>
        </details>
      `
      : "";
    return `
      <article class="candidate-item ${candidate.eliminated ? "eliminated" : ""}">
        <div class="candidate-meta">
          <span class="badge">+${candidate.positive_votes}</span>
          <span class="badge">-${candidate.negative_votes}</span>
        </div>
        <p class="candidate-formula">${escapeHtml(candidate.formula)}</p>
        ${notes}
        ${chooseButton}
      </article>
    `;
  }).join("");

  document.querySelectorAll(".pick-btn").forEach((button) => {
    button.addEventListener("click", () => chooseCandidate(button.dataset.formula));
  });
}

function renderHistory() {
  if (!appState?.history?.length) {
    historyList.className = "history-list empty";
    historyList.textContent = "No classifications yet.";
    return;
  }
  historyList.className = "history-list";
  historyList.innerHTML = appState.history.map((item, index) => `
    <article class="history-item">
      <div class="history-trace">${renderTrace(item.trace)}</div>
      <div class="history-actions">
        <button class="history-vote accept ${item.classification === "accept" ? "active" : ""}" data-history-index="${index}" data-classification="accept" aria-pressed="${item.classification === "accept" ? "true" : "false"}">Accept</button>
        <button class="history-vote reject ${item.classification === "reject" ? "active" : ""}" data-history-index="${index}" data-classification="reject" aria-pressed="${item.classification === "reject" ? "true" : "false"}">Reject</button>
        <button class="history-vote unsure ${item.classification === "unsure" ? "active" : ""}" data-history-index="${index}" data-classification="unsure" aria-pressed="${item.classification === "unsure" ? "true" : "false"}">Unsure</button>
      </div>
    </article>
  `).join("");

  historyList.querySelectorAll(".history-vote").forEach((button) => {
    button.addEventListener("click", () => submitReclassification(button.dataset.historyIndex, button.dataset.classification));
  });
}

function renderPair() {
  pairSection.classList.remove("hidden");
  if (!appState.current_pair) {
    document.getElementById("traceA").innerHTML = `<p class="prose">${escapeHtml(appState.message || "No trace pair ready.")}</p>`;
    document.getElementById("traceB").innerHTML = "";
    document.getElementById("traceAMatches").innerHTML = "";
    document.getElementById("traceBMatches").innerHTML = "";
    return;
  }

  document.getElementById("traceA").innerHTML = renderTrace(appState.current_pair.trace1);
  document.getElementById("traceB").innerHTML = renderTrace(appState.current_pair.trace2);
  document.getElementById("traceAMatches").innerHTML = renderMatchDetails(appState.current_pair.matches1);
  document.getElementById("traceBMatches").innerHTML = renderMatchDetails(appState.current_pair.matches2);
}

function renderResult() {
  const result = appState.final_result || {
    title: appState.mode === "single_candidate" ? "We could only get this one." : "Result",
    formula: appState.candidate_states.find((item) => !item.eliminated)?.formula || "",
    explanation: appState.candidate_states.find((item) => !item.eliminated)?.explanation || "",
    english: "",
    examples_in: [],
    examples_out: [],
    message: appState.message || "",
  };
  document.getElementById("resultTitle").textContent = result.title || "Result";
  document.getElementById("resultFormula").textContent = result.formula || "No final formula";
  document.getElementById("resultMessage").textContent = result.message || appState.message || "";
  document.getElementById("resultExplanation").innerHTML = result.explanation
    ? `<details class="result-notes"><summary>Show Notes</summary><p class="prose">${escapeHtml(result.explanation)}</p></details>`
    : '<p class="prose">No notes available.</p>';
  document.getElementById("resultEnglish").innerHTML = result.english
    ? `<details class="result-notes"><summary>Show English Gloss</summary><p class="prose">${escapeHtml(result.english)}</p></details>`
    : '<p class="prose">No English gloss available.</p>';
  document.getElementById("resultIn").innerHTML = renderExampleList(result.examples_in);
  document.getElementById("resultOut").innerHTML = renderExampleList(result.examples_out);
}

function renderExampleList(items) {
  if (!items?.length) {
    return '<div class="example-item">No examples.</div>';
  }
  return items.map((item) => `<div class="example-item">${renderTrace(item)}</div>`).join("");
}

function renderBadges(items) {
  if (!items?.length) {
    return `<span class="badge">matches none</span>`;
  }
  return items.map((formula) => `<span class="badge">${escapeHtml(shortFormula(formula))}</span>`).join("");
}

function renderMatchDetails(items) {
  const count = items?.length || 0;
  const label = count ? `Show matching formulas (${count})` : "Show matching formulas";
  return `
    <details class="match-details">
      <summary>${escapeHtml(label)}</summary>
      <div class="badge-row">${renderBadges(items)}</div>
    </details>
  `;
}

function renderTrace(trace) {
  return `<pre class="trace-string">${escapeHtml(trace)}</pre>`;
}

function shortFormula(formula) {
  return formula.length > 20 ? `${formula.slice(0, 20)}…` : formula;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}
