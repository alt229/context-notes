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
  renderClaudeSignIn();
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
    + (info.speech ? "installed." : info.python && info.python.newer ? "not installed."
       : "not installed. To add it: pip3 install faster-whisper")
    + (info.python && info.python.newer ? " " + info.python.advice : "");
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


// ---------------------------------------------------------------- signing Claude Code in from the page
// `claude auth login` prints a link and waits for the code that page shows (claude_code.login_start). The link may be
// opened on another computer (the account's owner can sign in and send the code back); only this computer may start
// it (LOCAL_ONLY in app.py), so the row is hidden from another device.
let loginPoll = null;
function renderClaudeSignIn() {
  const c = info.claude || {}, open = !$("claudeLoginPanel").hidden;
  $("claudeLoginBtn").hidden = !c.installed || open;
  $("claudeLoginBtn").textContent = c.signed_in && !c.problem ? "Sign in as someone else…" : "Sign in to Claude Code…";
  $("claudeLogoutBtn").hidden = !c.signed_in || open;
}
function showLoginPanel(url) {
  $("claudeLoginPanel").hidden = false;
  $("claudeLoginLink").href = url || "#";
  $("claudeLoginLink").textContent = url ? "Open the sign-in page" : "Waiting for the link…";
  $("claudeLoginCopy").disabled = !url;
  $("claudeLoginCode").value = "";
  renderClaudeSignIn();
}
function hideLoginPanel() {
  $("claudeLoginPanel").hidden = true;
  if (loginPoll) clearInterval(loginPoll);
  loginPoll = null;
  renderClaudeSignIn();
}
async function startClaudeLogin() {
  msg("c_msg", "Starting the sign-in…");
  const r = await api("/api/claude/login", {});
  if (r.error || r.ok === false) return msg("c_msg", r.error || "The sign-in couldn't start.", false);
  msg("c_msg", "");
  showLoginPanel(r.url);
  msg("claudeLoginMsg", r.url ? "" : "Claude Code opened a browser window itself; if it did, finish there.");
  if (r.url) window.open(r.url, "_blank", "noopener");  // may be blocked: the link is there to click too
  // While the link is open, watch for a sign-in that finishes by itself (Claude Code's own browser window).
  loginPoll = setInterval(async () => {
    const st = await api("/api/claude/login/state", {});
    if (st.waiting !== false) return;
    finishedLogin(st);
  }, 3000);
}
function finishedLogin(st) {
  if (st.claude) info.claude = st.claude;
  hideLoginPanel();
  renderSettings();
  msg("c_msg", st.ok ? "Signed in. " + claudeText(info.claude) : (st.error || "The sign-in didn't finish."), !!st.ok);
  if (!running) (videos.length ? readyScreen : idleScreen)();
}
async function finishClaudeLogin() {
  const code = $("claudeLoginCode").value.trim();
  if (!code) return msg("claudeLoginMsg", "Paste the code from the sign-in page first.", false);
  msg("claudeLoginMsg", "Checking the code…");
  $("claudeLoginDone").disabled = true;
  const st = await api("/api/claude/login/code", { code });
  $("claudeLoginDone").disabled = false;
  if (st.error && st.waiting) return msg("claudeLoginMsg", st.error, false);
  if (st.waiting) return msg("claudeLoginMsg", "Still waiting…");
  finishedLogin(st);
}
async function cancelClaudeLogin() {
  const r = await api("/api/claude/login/cancel", {});
  if (r.claude) info.claude = r.claude;
  hideLoginPanel();
  msg("c_msg", "");
}
async function copyLoginLink() {
  const url = $("claudeLoginLink").href;
  try { await navigator.clipboard.writeText(url); msg("claudeLoginMsg", "Copied. Send it to whoever's account this is.", true); }
  catch (e) { msg("claudeLoginMsg", "Couldn't copy by itself. Right-click the link and copy its address.", false); }
}
async function claudeLogout() {
  msg("c_msg", "Signing out…");
  const r = await api("/api/claude/logout", {});
  if (r.claude) info.claude = r.claude;
  renderSettings();
  msg("c_msg", r.message || r.error, !!r.ok);
}
