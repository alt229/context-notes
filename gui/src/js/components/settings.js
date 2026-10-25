// The Settings dialog: where Claude runs, the API key, the OpenSubtitles login, the VLC extension, and about this computer.
(() => {
  const { $, api, state } = CN;

  function renderSettings() {
    const { info } = state;
    const chosen = document.querySelector(`input[name=backend][value="${info.backend}"]`);
    if (chosen) chosen.checked = true;
    $("claudeCodeStatus").textContent = info.claude_code.installed ? "(installed)" : "(not found: install Claude Code and sign in)";
    const k = info.key;
    if (k.found) $("keyStatus").textContent = k.source === "environment"
      ? `Using the key in the ANTHROPIC_API_KEY setting of this computer (ends in …${k.ends}). A key saved here takes its place.`
      : `Saved. It ends in …${k.ends} and is kept in ${k.file}, readable only by you.`;
    else $("keyStatus").textContent = "No key yet.";
    if (k.problem) $("keyStatus").textContent += " " + k.problem;
    $("testKeyBtn").disabled = !k.found;
    $("keyBanner").hidden = !(info.backend === "api" && !k.found);
    const os = info.opensubtitles;
    $("osStatus").textContent = os.saved ? `Saved, for the account ${os.username}.` : "No login saved.";
    const vlc = info.vlc;
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
    if (!state.running) (state.videos.length ? CN.readyScreen : CN.idleScreen)();
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

  Object.assign(CN, { renderSettings, reloadInfo, msg, saveBackend, saveKey, testKey, saveOs, installVlc });
})();
