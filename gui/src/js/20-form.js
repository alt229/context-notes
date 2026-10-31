// ---------------------------------------------------------------- the form
function btsOn() { return document.querySelector("input[name=track]:checked").value === BTS; }
function options() {
  const bts = btsOn();
  return {
    path: $("path").value.trim(), recursive: $("recursive").checked,
    track: bts ? BTS : "context", spoilers: bts ? $("spoilers").value : "",
    research_again: bts && $("research_again").checked,
    quality: document.querySelector("input[name=quality]:checked").value,
    film_language: $("film_language").value, refine: $("refine").checked, limit: $("limit").value.trim(),
    subs_language: $("subs_language").value, show_subs: $("show_subs").value,
    notes_language: $("notes_language").value.trim(), show: $("show").value.trim(),
    title: videos.length === 1 ? $("titleInput").value.trim() : "",
    check_alignment: !bts && $("check_alignment").checked, frames: $("dense").checked ? "dense" : "keyframes",
    redo: $("redo").checked, audience: $("audience").value.trim(), offline: $("offline").checked,
    effort: $("effort").value, seconds_per_word: $("spw").value.trim(), note_background: $("note_background").value,
    box_opacity: $("note_background").value === "see-through" ? $("opacity").value.trim() : "",
    ...(onPlan() ? { api_fallback: $("api_fallback").checked, api_fallback_usd: $("api_fallback_usd").value.trim() } : {}),
  };
}
function onPlan() { return !!info && info.settings.route === "plan"; }
function showFallback() {
  $("fallbackRun").hidden = !onPlan();
  $("api_fallback_usd").disabled = !$("api_fallback").checked;
}
function showOpacity() { $("opacityField").hidden = $("note_background").value !== "see-through"; }
// Behind the Scenes: its own options; the timing check is about the context notes only.
function showTrack() {
  const bts = btsOn();
  $("btsOptions").hidden = !bts;
  $("alignmentRow").hidden = bts;
}
function alignmentOn() { return !btsOn() && $("check_alignment").checked; }
// The form starts from this install's defaults (settings.json, from the Settings page). Nothing is remembered in the
// browser any more: the app picks a new port each start, so a browser would forget it anyway.
function applySettings() {
  const s = info.settings;
  $("api_fallback").checked = s.api_fallback;
  $("api_fallback_usd").value = Number(s.api_fallback_usd).toFixed(2);
  showFallback();
  const q = document.querySelector(`input[name=quality][value="${s.quality}"]`);
  if (q) q.checked = true;
  $("effort").value = s.effort;
  $("audience").value = s.audience;
  $("notes_language").value = s.notes_language;
  $("spw").value = s.seconds_per_word == null ? "" : String(s.seconds_per_word);
  $("note_background").value = s.note_background;
  $("opacity").value = String(s.note_opacity);
  $("dense").checked = s.frames === "dense";
  $("check_alignment").checked = s.check_alignment;
  $("offline").checked = s.offline;
  $("recursive").checked = s.recursive;
  $("path").value = s.remember_start_folder ? s.start_folder : "";
}
function autoSendOn() { return !!info && info.settings.autosend; }
// The folder you choose opens next time, when "Remember starting folder" is on in Settings.
function rememberStartFolder(p) {
  if (!info || !info.settings.remember_start_folder || p === info.settings.start_folder) return;
  info.settings.start_folder = p;
  api("/api/settings", { start_folder: p });               // the page doesn't wait for it
}
function settingsMsg(text, ok) { $("d_msg").textContent = text; $("d_msg").className = ok ? "msg" : "msg bad"; }
function renderDefaults() {
  const s = info.settings;
  const route = document.querySelector(`input[name=d_route][value="${s.route}"]`);
  if (route) route.checked = true;
  $("d_api_fallback").checked = s.api_fallback;
  $("d_api_fallback_usd").value = Number(s.api_fallback_usd).toFixed(2);
  $("d_api_fallback_usd").disabled = !s.api_fallback;
  msg("c_msg", "");
  $("d_claude_path").value = s.claude_path || "";
  $("d_quality").value = s.quality;
  $("d_effort").value = s.effort;
  $("d_audience").value = s.audience;
  $("d_notes_language").value = s.notes_language;
  $("d_spw").value = s.seconds_per_word == null ? "" : String(s.seconds_per_word);
  $("d_background").value = s.note_background;
  $("d_opacity").value = String(s.note_opacity);
  $("d_bts_spoilers").value = s.bts_spoilers;
  $("d_frames").checked = s.frames === "dense";
  $("d_check_alignment").checked = s.check_alignment;
  $("d_offline").checked = s.offline;
  $("d_download_subs").checked = s.download_subs;
  $("d_download_subs").disabled = s.offline;
  $("d_check_subs").checked = s.check_subs;
  $("d_replace_bad_subs").checked = s.replace_bad_subs;
  $("d_replace_bad_subs").disabled = s.offline || !s.check_subs;
  $("d_recursive").checked = s.recursive;
  $("d_remember_start").checked = s.remember_start_folder;
  $("d_start_folder").textContent = s.start_folder || "none yet";
  $("d_yes_to_all").checked = s.yes_to_all;
  $("d_autosend").checked = s.autosend;
  settingsMsg("", true);
}
// A number that isn't one is sent as typed, so the app refuses it with a message instead of saving an empty value.
function numberOrText(text) {
  const n = Number(text);
  return Number.isFinite(n) ? n : text;
}
async function saveDefaults() {
  const spw = $("d_spw").value.trim();
  const body = {
    quality: $("d_quality").value, effort: $("d_effort").value, audience: $("d_audience").value.trim(),
    notes_language: $("d_notes_language").value.trim(), seconds_per_word: spw === "" ? null : numberOrText(spw),
    note_background: $("d_background").value, note_opacity: numberOrText($("d_opacity").value.trim()),
    frames: $("d_frames").checked ? "dense" : "keyframes", check_alignment: $("d_check_alignment").checked,
    offline: $("d_offline").checked, download_subs: $("d_download_subs").checked, recursive: $("d_recursive").checked,
    remember_start_folder: $("d_remember_start").checked, yes_to_all: $("d_yes_to_all").checked,
    autosend: $("d_autosend").checked, bts_spoilers: $("d_bts_spoilers").value,
    check_subs: $("d_check_subs").checked, replace_bad_subs: $("d_replace_bad_subs").checked,
  };
  const r = await api("/api/settings", body);
  if (r.error) return settingsMsg(r.error, false);
  info.settings = r.settings;
  renderDefaults();
  applySettings();
  settingsMsg("Saved. The app and the Terminal scripts use these from now on.", true);
}
async function saveClaude() {
  const usd = Number($("d_api_fallback_usd").value.trim().replace(/^\$/, "").replace(",", ""));
  if (!(usd >= 0.01 && usd <= 1000)) return msg("c_msg", "Up to: an amount in dollars from 0.01 to 1,000, like 5.", false);
  const body = { route: document.querySelector("input[name=d_route]:checked").value,
                 api_fallback: $("d_api_fallback").checked, api_fallback_usd: usd,
                 claude_path: $("d_claude_path").value.trim() };
  const r = await api("/api/settings", body);
  if (r.error) return msg("c_msg", r.error, false);
  info.settings = r.settings;
  if (r.claude) info.claude = r.claude;                     // the path changed: the app looked again
  renderDefaults();
  applySettings();
  renderSettings();
  msg("c_msg", "Saved. The app and the Terminal scripts use this from now on.", true);
}
async function checkClaude() {
  msg("c_msg", "Checking…");
  const r = await api("/api/claude/check", {});
  if (r.error) return msg("c_msg", r.error, false);
  info.claude = r.claude;
  renderSettings();
  msg("c_msg", "");
}
function claudeText(c) {
  if (!c) return "";
  if (!c.problem) return `Claude Code${c.version ? " " + c.version : ""} is ready`
    + (c.signed_in ? ", signed in with your Claude account." : ". It couldn't say how it's signed in; the first request will tell.");
  return c.problem;
}
async function resetDefaults() {
  const r = await api("/api/settings/reset", {});
  if (r.error) return settingsMsg(r.error, false);
  info.settings = r.settings;
  renderDefaults();
  applySettings();
  settingsMsg("Back to the built-in defaults.", true);
}

function fillLanguages() {
  for (const id of ["film_language", "subs_language", "show_subs"]) {
    const sel = $(id);
    for (const l of info.languages) sel.append(el("option", { value: l.code }, l.name));
  }
}

