// The Settings dialog: Claude (Claude Code sign-in or API key), the OpenSubtitles login, the VLC extension, and about this
// computer. Which parts show depends on the backend chosen and on whether the app runs on another computer (info.hosted).
(() => {
  const { $, api, state } = CN;

  function renderSettings() {
    const { info } = state;
    const chosen = document.querySelector(`input[name=backend][value="${info.backend}"]`);
    if (chosen) chosen.checked = true;
    const where = info.hosted ? "the server" : "this computer";
    $("claudeCodeStatus").textContent = info.claude_code.installed ? "(installed)" : `(not found on ${where}: install Claude Code and sign in)`;
    $("claudeCodeBox").hidden = info.backend !== "claude-code";
    $("apiKeyBox").hidden = info.backend !== "api";
    renderClaudeStatus();
    const k = info.key;
    if (k.found) $("keyStatus").textContent = k.source === "environment"
      ? `Using the key in the ANTHROPIC_API_KEY setting of ${where} (ends in …${k.ends}). A key saved here takes its place.`
      : `Saved. It ends in …${k.ends} and is kept in ${k.file}, readable only by the app.`;
    else $("keyStatus").textContent = "No key yet.";
    if (k.problem) $("keyStatus").textContent += " " + k.problem;
    $("testKeyBtn").disabled = !k.found;
    $("keyBanner").hidden = !(info.backend === "api" && !k.found);
    // Things that only make sense when the browser and the app are on the same computer.
    const hosted = !!info.hosted;
    $("pickFile").hidden = $("pickFolder").hidden = !info.dialogs;
    $("aboutSection").hidden = hosted;
    $("vlcLocal").hidden = hosted;
    $("vlcHosted").hidden = !hosted;
    $("vlcDownload").href = "/api/vlc/extension?k=" + encodeURIComponent(CN.key);
    const os = info.opensubtitles;
    $("osStatus").textContent = os.saved ? `Saved, for the account ${os.username}.` : "No login saved.";
    const vlc = info.vlc || [];
    if (!vlc.length) $("vlcStatus").textContent = "Couldn't work out where VLC keeps extensions on this computer.";
    else if (vlc.every((x) => x.current)) $("vlcStatus").textContent = "Installed and up to date.";
    else if (vlc.some((x) => x.installed)) $("vlcStatus").textContent = "Installed, but an older version.";
    else $("vlcStatus").textContent = "Not installed yet.";
    $("installVlcBtn").textContent = vlc.some((x) => x.installed) ? "Update the VLC extension" : "Install the VLC extension";
    const systems = { mac: "a Mac", linux: "Linux", wsl: "Linux in Windows (WSL)", windows: "Windows" };
    $("aboutText").textContent = `Running on ${systems[info.system] || info.system}. Speech recognition (for re-timing subtitles and checking notes) is `
      + (info.speech ? "installed." : "not installed. To add it: pip3 install faster-whisper");
    $("speechHint").textContent = info.speech ? "Slow the first time; free." : "Needs speech recognition, which isn't installed (see Settings).";
  }
  // The line under "Claude Code": what /api/claude/status last said (state.claudeStatus), or what /api/info already knows.
  function renderClaudeStatus() {
    const { info, claudeStatus } = state;
    const status = $("claudeStatus");
    $("claudeSharedNote").hidden = true;
    $("checkSignInBtn").disabled = !info.claude_code.installed;
    if (!info.claude_code.installed) { status.textContent = `Claude Code isn't installed on ${info.hosted ? "the server" : "this computer"}.`; return; }
    if (!claudeStatus) { status.textContent = "Checking the sign-in…"; return; }
    status.textContent = claudeStatus.signed_in
      ? `Signed in${claudeStatus.method ? " (" + claudeStatus.method + ")" : ""}.` : claudeStatus.message || "Not signed in.";
    $("claudeSharedNote").hidden = !(claudeStatus.signed_in && !info.claude_code.token_saved);
  }
  // Ask the app whether Claude Code is signed in (it runs the Claude Code command, so it takes a moment).
  async function checkClaude() {
    const { info } = state;
    if (!info || !info.claude_code.installed) { state.claudeSignedIn = null; renderClaudeStatus(); return; }
    state.claudeStatus = null;
    renderClaudeStatus();
    const r = await api("/api/claude/status", {});
    state.claudeStatus = r.error ? { signed_in: false, message: r.error } : r;
    state.claudeSignedIn = r.error ? null : !!r.signed_in;
    renderClaudeStatus();
    if (!state.running) (state.videos.length ? CN.readyScreen : CN.idleScreen)();
  }
  async function reloadInfo() {
    const r = await api("/api/info");
    if (r.error) { CN.note("left", "Problem", r.error); return false; }
    state.info = r;
    renderSettings();
    return true;
  }
  function msg(id, text, ok) {
    const m = $(id);
    m.textContent = text || "";
    m.className = "msg" + (ok === true ? " ok" : ok === false ? " bad" : "");
  }
  async function saveBackend() {
    const picked = document.querySelector("input[name=backend]:checked");
    if (!picked) return;
    msg("backendMsg", "Saving…");
    const r = await api("/api/backend", { backend: picked.value });
    msg("backendMsg", r.message || r.error, !!r.ok);
    await reloadInfo();
    if (picked.value === "claude-code") await checkClaude();
    else if (!state.running) (state.videos.length ? CN.readyScreen : CN.idleScreen)();
  }
  async function saveToken() {
    msg("tokenMsg", "Saving…");
    const r = await api("/api/claude/token", { token: $("claudeToken").value });
    $("claudeToken").value = "";
    msg("tokenMsg", r.message || r.error, !!r.ok);
    await reloadInfo();
    if (r.ok) await checkClaude();
  }
  async function saveKey() {
    msg("keyMsg", "Saving…");
    const r = await api("/api/key", { key: $("keyInput").value });
    $("keyInput").value = "";
    msg("keyMsg", r.message || r.error, !!r.ok);
    await reloadInfo();
    if (!state.running) (state.videos.length ? CN.readyScreen : CN.idleScreen)();
  }
  async function testKey() {
    msg("keyMsg", "Checking…");
    const r = await api("/api/key/test", {});
    msg("keyMsg", r.message || r.error, !!r.ok);
  }
  async function saveOs() {
    msg("osMsg", "Saving and logging in…");
    const r = await api("/api/opensubtitles", { api_key: $("osKey").value, username: $("osUser").value, password: $("osPass").value });
    $("osKey").value = $("osPass").value = "";
    msg("osMsg", (r.lines || [r.error]).join("\n"), !!r.ok);
    await reloadInfo();
  }
  async function installVlc() {
    msg("vlcMsg", "Installing…");
    const r = await api("/api/vlc/install", {});
    msg("vlcMsg", r.message || r.error, !!r.ok);
    await reloadInfo();
  }

  Object.assign(CN, { renderSettings, reloadInfo, checkClaude, saveToken, msg, saveBackend, saveKey, testKey, saveOs, installVlc });
})();
