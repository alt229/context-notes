// ---------------------------------------------------------------- settings
function renderSettings() {
  // From another device (app.py --hosted): hide what only works on the computer running the app (LOCAL_ONLY there).
  document.body.classList.toggle("remote", info.local === false);
  $("vlcDownload").href = `/api/vlc/extension?k=${encodeURIComponent(KEY)}`;
  usageNow = info.usage || usageNow;
  renderMeters();
  renderCredit();
  const k = info.key;
  if (k.found) $("keyStatus").textContent = k.source === "environment"
    ? `Using the key in the ANTHROPIC_API_KEY setting of this computer (ends in …${k.ends}). A key saved here takes its place.`
    : `Saved. It ends in …${k.ends} and is kept in ${k.file}, readable only by you.`;
  else $("keyStatus").textContent = "No key yet.";
  if (k.problem) $("keyStatus").textContent += " " + k.problem;
  $("testKeyBtn").disabled = !k.found;
  $("claudeStatus").textContent = claudeText(info.claude);
  $("claudeStatus").className = info.claude && info.claude.problem ? "msg bad" : "";
  // The banner says what's missing to write notes: Claude Code on the plan (unless API credits can stand in), else the key.
  const plan = onPlan(), codeOk = !!info.claude && !info.claude.problem;
  $("keyBanner").hidden = plan ? codeOk : k.found;
  $("keyBannerText").textContent = plan
    ? "To write notes on your Claude plan, Claude Code needs to be installed and signed in on this computer (see Settings, Claude)."
    : "To write notes, add your Anthropic API key. It stays on this computer.";
  $("bannerKeyBtn").textContent = plan ? "Open Settings" : "Add your key";
  const os = info.opensubtitles;
  $("osStatus").textContent = os.saved ? `Saved, for the account ${os.username}.` : "No login saved.";
  const vlc = info.vlc;
  if (!vlc.length) $("vlcStatus").textContent = "Couldn't work out where VLC keeps extensions on this computer.";
  else if (vlc.every((x) => x.current)) $("vlcStatus").textContent = "Installed and up to date.";
  else if (vlc.some((x) => x.installed)) $("vlcStatus").textContent = "Installed, but an older version.";
  else $("vlcStatus").textContent = "Not installed yet.";
  if (info.local === false) $("vlcStatus").textContent = "On the computer running the app: " + $("vlcStatus").textContent;
  $("installVlcBtn").textContent = vlc.some((x) => x.installed) ? "Update the VLC extension" : "Install the VLC extension";
  const systems = { mac: "a Mac", linux: "Linux", wsl: "Linux in Windows (WSL)", windows: "Windows" };
  $("aboutText").textContent = (info.local === false ? "You're using it from another device. " : "")
    + `Running on ${systems[info.system] || info.system}. Speech recognition (for re-timing subtitles and checking notes) is `
    + (info.speech ? "installed." : "not installed. To add it: pip3 install faster-whisper");
  $("speechHint").textContent = info.speech ? "Slow the first time; free." : "Needs speech recognition, which isn't installed (see Settings).";
}
async function reloadInfo() {
  const r = await api("/api/info");
  if (r.error) { note("left", "Problem", r.error); return false; }
  info = r;
  renderSettings();
  renderDefaults();
  return true;
}
function msg(id, text, ok) {
  const m = $(id);
  m.textContent = text || "";
  m.className = "msg" + (ok === true ? " ok" : ok === false ? " bad" : "");
}
async function saveKey() {
  msg("keyMsg", "Saving…");
  const r = await api("/api/key", { key: $("keyInput").value });
  $("keyInput").value = "";
  msg("keyMsg", r.message || r.error, !!r.ok);
  await reloadInfo();
  if (!running) (videos.length ? readyScreen : idleScreen)();
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

