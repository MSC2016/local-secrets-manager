const statusPanel = document.getElementById("status-panel");
const countdown = document.getElementById("countdown");
const countdownStat = document.getElementById("countdown-stat");
const statusPill = document.getElementById("status-pill");
const mergedStatus = document.getElementById("merged-status");
const timeoutMinutesStat = document.getElementById("timeout-minutes-stat");
const timerEnabledStat = document.getElementById("timer-enabled-stat");
const databaseStateDetail = document.getElementById("database-state-detail");
const databaseMessage = document.getElementById("database-message");
const timeoutWarning = document.getElementById("timeout-warning");
const countdownNote = document.getElementById("countdown-note");
const lastEvent = document.getElementById("last-event");
const sessionLogPreview = document.getElementById("session-log-preview");
const sessionLogFull = document.getElementById("session-log-full");
const sessionLogSearch = document.getElementById("session-log-search");
const sessionLogEmpty = document.getElementById("session-log-empty");
const sessionLogLevelFilters = Array.from(document.querySelectorAll(".session-log-level-filter"));
const summaryUnlockButton = document.getElementById("summary-unlock-button");
const summaryLockForm = document.getElementById("summary-lock-form");
const retrievalHelperPanel = document.getElementById("retrieval-helper-panel");
const serviceUnreachableWarning = document.getElementById("service-unreachable-warning");
const unlockForm = document.getElementById("unlock-form");
const unlockPassphrase = document.getElementById("unlock-passphrase");
const unlockSubmitButton = document.getElementById("unlock-submit-button");
const revealTimers = new Map();
const allServiceControls = Array.from(document.querySelectorAll("button, input, select, textarea"));
let activeRevealSelectionButton = null;
const retrievalHelperStateKey = "local-secrets-manager.retrieval-helper-open";

function setHidden(element, hidden) {
  if (element) {
    element.classList.toggle("hidden", hidden);
  }
}

function visibleForMode(element, mode) {
  if (element.hasAttribute("data-requires-unreachable")) {
    return mode === "unreachable";
  }
  if (element.hasAttribute("data-requires-unlocked")) {
    return mode === "unlocked";
  }
  if (element.hasAttribute("data-requires-locked")) {
    return mode === "locked";
  }
  return true;
}

function updateStateRegions(mode) {
  for (const element of document.querySelectorAll("[data-requires-unlocked], [data-requires-locked], [data-requires-unreachable]")) {
    setHidden(element, !visibleForMode(element, mode));
  }
}

function setServiceAvailability(available) {
  for (const control of allServiceControls) {
    if (!available) {
      if (!("unavailableDisabled" in control.dataset)) {
        control.dataset.unavailableDisabled = control.disabled ? "true" : "false";
      }
      control.disabled = true;
      continue;
    }

    if ("unavailableDisabled" in control.dataset) {
      control.disabled = control.dataset.unavailableDisabled === "true";
      delete control.dataset.unavailableDisabled;
    }
  }
}

function stopAllReveals() {
  for (const button of document.querySelectorAll(".reveal-button")) {
    if (button.dataset.state === "shown") {
      maskSecret(button);
    }
  }
}

function stripLevelToken(event) {
  return (event.rendered || "").replace(`[${event.level}] `, "");
}

function buildLogItem(event) {
  const item = document.createElement("li");
  item.className = `log-entry log-level-${event.level}`;
  item.dataset.level = event.level;
  item.dataset.search = event.search_text || "";

  const line = document.createElement("span");
  line.className = "log-entry-line";
  const badge = document.createElement("span");
  badge.className = `log-level-badge log-level-badge-${event.level}`;
  badge.textContent = event.level;

  const text = document.createElement("span");
  text.className = "log-entry-text";
  text.textContent = event.rendered_without_level || stripLevelToken(event);

  line.appendChild(badge);
  line.appendChild(text);
  item.appendChild(line);

  return item;
}

function activeLogLevels() {
  const checkedLevels = sessionLogLevelFilters.filter((input) => input.checked).map((input) => input.value);
  return checkedLevels.length > 0 ? new Set(checkedLevels) : null;
}

function applySessionLogFilters() {
  if (!sessionLogFull) {
    return;
  }

  const textFilter = (sessionLogSearch?.value || "").trim().toLowerCase();
  const levels = activeLogLevels();
  let visibleCount = 0;

  for (const item of sessionLogFull.querySelectorAll("li")) {
    const matchesText = !textFilter || (item.dataset.search || "").includes(textFilter);
    const matchesLevel = !levels || levels.has(item.dataset.level);
    const visible = matchesText && matchesLevel;
    item.classList.toggle("hidden", !visible);
    if (visible) {
      visibleCount += 1;
    }
  }

  if (sessionLogEmpty) {
    sessionLogEmpty.classList.toggle("hidden", visibleCount > 0);
  }
}

function renderSessionLog(listElement, events) {
  if (!listElement) {
    return;
  }

  listElement.innerHTML = "";
  for (const event of events) {
    listElement.appendChild(buildLogItem(event));
  }

  if (listElement === sessionLogFull) {
    applySessionLogFilters();
  }
}

function humanizeDatabaseState(state) {
  if (state === "ready") return "Ready";
  if (state === "corrupted") return "Corrupted database";
  if (state === "missing" || state === "uninitialized") return "Setup required";
  return state.charAt(0).toUpperCase() + state.slice(1).replaceAll("_", " ");
}

function buildMergedStatus(status, mode = status.unlocked ? "unlocked" : "locked") {
  if (mode === "unreachable") {
    return "Service unreachable";
  }
  return `${status.unlocked ? "Unlocked" : "Locked"} · ${humanizeDatabaseState(status.database_state)}`;
}

function renderCountdown(seconds) {
  if (seconds === null) {
    countdown.textContent = "disabled";
    countdown.dataset.seconds = "";
    countdownStat.textContent = "Disabled";
    countdownNote.classList.add("hidden");
    return;
  }

  countdownNote.classList.remove("hidden");
  countdown.dataset.seconds = String(seconds);
  countdown.textContent = `${seconds}s`;
  countdownStat.textContent = `${seconds}s`;
}

function startCountdown() {
  if (!countdown || !countdown.dataset.seconds) {
    return;
  }

  const current = Number(countdown.dataset.seconds);
  if (Number.isNaN(current) || current <= 0) {
    renderCountdown(Math.max(current, 0));
    return;
  }

  window.setTimeout(() => {
    const next = Number(countdown.dataset.seconds) - 1;
    if (!Number.isNaN(next)) {
      renderCountdown(Math.max(next, 0));
      startCountdown();
    }
  }, 1000);
}

function maskSecret(button) {
  const target = document.getElementById(button.dataset.target);

  if (revealTimers.has(button.dataset.target)) {
    window.clearTimeout(revealTimers.get(button.dataset.target));
    revealTimers.delete(button.dataset.target);
  }

  if (target) {
    target.textContent = "••••••••";
    target.dataset.revealedValue = "";
  }
  button.dataset.state = "hidden";
  button.textContent = "Show";
}

function scheduleAutoHide(button) {
  if (revealTimers.has(button.dataset.target)) {
    window.clearTimeout(revealTimers.get(button.dataset.target));
  }

  const timerId = window.setTimeout(() => maskSecret(button), 9000);
  revealTimers.set(button.dataset.target, timerId);
}

function clearAutoHideTimer(button) {
  if (!button || !revealTimers.has(button.dataset.target)) {
    return;
  }

  window.clearTimeout(revealTimers.get(button.dataset.target));
  revealTimers.delete(button.dataset.target);
}

function normalizeEventTarget(target) {
  if (target instanceof Element) {
    return target;
  }
  return target?.parentElement || null;
}

function shouldIgnoreSelectionClick(target) {
  const element = normalizeEventTarget(target);
  if (!element) {
    return false;
  }

  return Boolean(element.closest("a, button, input, textarea, select, summary, form, label, details, [data-secret-value-zone], [data-prevent-row-toggle]"));
}

function secretValueRegionForTarget(target) {
  const element = normalizeEventTarget(target);
  if (!element) {
    return null;
  }

  return element.closest(".secret-value-region[data-secret-value-zone]");
}

function revealButtonForValueRegion(valueRegion) {
  const value = valueRegion?.querySelector(".secret-value[id]");
  if (!value) {
    return null;
  }

  return document.querySelector(`.reveal-button[data-target="${value.id}"]`);
}

function wireSelectableContainers(selector, { stopPropagation = false } = {}) {
  for (const element of document.querySelectorAll(selector)) {
    element.addEventListener("click", (event) => {
      if (stopPropagation) {
        event.stopPropagation();
      }
      if (shouldIgnoreSelectionClick(event.target)) {
        return;
      }
      const url = element.dataset.selectUrl;
      if (url) {
        window.location.href = url;
      }
    });
  }
}

function initializeRetrievalHelperState() {
  if (!retrievalHelperPanel) {
    return;
  }

  const savedState = window.sessionStorage.getItem(retrievalHelperStateKey);
  retrievalHelperPanel.open = savedState === "true";
  retrievalHelperPanel.addEventListener("toggle", () => {
    window.sessionStorage.setItem(retrievalHelperStateKey, String(retrievalHelperPanel.open));
  });
}

for (const control of document.querySelectorAll(".summary-control")) {
  control.addEventListener("click", (event) => {
    event.stopPropagation();
  });
}

if (summaryLockForm) {
  summaryLockForm.addEventListener("click", (event) => {
    event.stopPropagation();
  });
}

if (summaryUnlockButton) {
  summaryUnlockButton.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    statusPanel.open = true;

    const input = document.getElementById("unlock-passphrase");
    if (input) {
      input.focus();
    }
  });
}

if (sessionLogSearch) {
  sessionLogSearch.addEventListener("input", applySessionLogFilters);
}

for (const input of sessionLogLevelFilters) {
  input.addEventListener("change", applySessionLogFilters);
}

for (const button of document.querySelectorAll(".reveal-button")) {
  button.addEventListener("click", async () => {
    const target = document.getElementById(button.dataset.target);

    if (button.dataset.state === "shown") {
      maskSecret(button);
      return;
    }

    const response = await fetch(
      `/api/v1/vaults/${encodeURIComponent(button.dataset.vault)}/secrets/${encodeURIComponent(button.dataset.secret)}`
    );
    const payload = await response.json();
    if (!response.ok) {
      if (target) {
        target.textContent = payload.error || "Unavailable";
        target.dataset.revealedValue = "";
      }
      return;
    }

    if (target) {
      target.textContent = payload.value;
      target.dataset.revealedValue = payload.value;
    }
    button.dataset.state = "shown";
    button.textContent = "Hide";
    scheduleAutoHide(button);
  });
}

for (const valueRegion of document.querySelectorAll(".secret-value-region[data-secret-value-zone]")) {
  valueRegion.addEventListener("mousedown", (event) => {
    if (event.button !== 0) {
      return;
    }

    const button = revealButtonForValueRegion(valueRegion);
    if (!button || button.dataset.state !== "shown") {
      return;
    }

    activeRevealSelectionButton = button;
    clearAutoHideTimer(button);
  });

  valueRegion.addEventListener("contextmenu", (event) => {
    if (!secretValueRegionForTarget(event.target)) {
      return;
    }

    event.stopPropagation();
  });
}

document.addEventListener("mouseup", () => {
  if (!activeRevealSelectionButton || activeRevealSelectionButton.dataset.state !== "shown") {
    activeRevealSelectionButton = null;
    return;
  }

  scheduleAutoHide(activeRevealSelectionButton);
  activeRevealSelectionButton = null;
});

window.addEventListener("blur", () => {
  if (!activeRevealSelectionButton || activeRevealSelectionButton.dataset.state !== "shown") {
    activeRevealSelectionButton = null;
    return;
  }

  scheduleAutoHide(activeRevealSelectionButton);
  activeRevealSelectionButton = null;
});

wireSelectableContainers(".secret-row[data-select-url]");
wireSelectableContainers(".metadata-container[data-select-url]", { stopPropagation: true });
wireSelectableContainers(".metadata-card[data-select-url]", { stopPropagation: true });
initializeRetrievalHelperState();

async function refreshStatus() {
  let response;
  try {
    response = await fetch("/ui/status", { headers: { Accept: "application/json" } });
  } catch {
    applyUnavailableState();
    return;
  }

  if (!response.ok) {
    applyUnavailableState();
    return;
  }

  const payload = await response.json();
  applyLiveStatus(payload);
}

function applyLiveStatus(payload) {
  const { status } = payload;
  const mode = status.unlocked ? "unlocked" : "locked";
  const canUnlockExistingDatabase = Boolean(status.database_unlockable && status.locked);

  setServiceAvailability(true);
  updateStateRegions(mode);
  statusPill.dataset.state = mode;
  mergedStatus.textContent = buildMergedStatus(status, mode);
  timerEnabledStat.textContent = status.timeout_enabled ? "Enabled" : "Disabled";
  timeoutMinutesStat.textContent = `${status.timeout_minutes} min`;
  databaseStateDetail.textContent = humanizeDatabaseState(status.database_state);
  lastEvent.textContent = status.last_event;
  databaseMessage.textContent = status.database_message;
  setHidden(timeoutWarning, Boolean(status.timeout_enabled));
  setHidden(serviceUnreachableWarning, true);
  setHidden(summaryUnlockButton, !canUnlockExistingDatabase);
  setHidden(summaryLockForm, Boolean(status.locked));
  setHidden(unlockForm, !canUnlockExistingDatabase);
  if (unlockPassphrase) {
    unlockPassphrase.disabled = !status.database_unlockable;
  }
  if (unlockSubmitButton) {
    unlockSubmitButton.disabled = !status.database_unlockable;
  }
  renderCountdown(status.seconds_remaining);

  renderSessionLog(sessionLogPreview, payload.session_log.slice(0, 5));
  renderSessionLog(sessionLogFull, payload.session_log);

  for (const button of document.querySelectorAll(".reveal-button")) {
    button.disabled = Boolean(status.locked);
  }

  if (status.locked) {
    stopAllReveals();
  }
}

function applyUnavailableState() {
  stopAllReveals();
  setServiceAvailability(false);
  updateStateRegions("unreachable");
  statusPill.dataset.state = "unreachable";
  mergedStatus.textContent = buildMergedStatus({ unlocked: false, database_state: "ready" }, "unreachable");
  timerEnabledStat.textContent = "Unavailable";
  timeoutMinutesStat.textContent = "Unavailable";
  databaseStateDetail.textContent = "Unavailable";
  lastEvent.textContent = "Unavailable";
  databaseMessage.textContent = "Unable to reach the service. Refresh after the backend is available again.";
  setHidden(timeoutWarning, true);
  setHidden(serviceUnreachableWarning, false);
  setHidden(summaryUnlockButton, true);
  setHidden(summaryLockForm, true);
  setHidden(unlockForm, true);
  renderCountdown(null);

  for (const button of document.querySelectorAll(".reveal-button")) {
    button.disabled = true;
  }
}

if (countdown) {
  startCountdown();
  window.setInterval(refreshStatus, 5000);
}
