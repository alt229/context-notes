// ---------------------------------------------------------------- running
function setRunning(on) {
  running = on;
  $("optionsSet").disabled = on;
  for (const id of ["path", "pickFile", "pickFolder", "browseBtn", "recursive"]) $(id).disabled = on;
  $("cancelBtn").hidden = !on;
  $("runBtn").hidden = on;
  $("cancelBtn").disabled = false;
  $("cancelBtn").textContent = "Cancel";
  updateRunButton();
}
function log(line) {
  const pre = $("log");
  if (pre.dataset.fresh !== "no") { pre.textContent = ""; pre.dataset.fresh = "no"; }
  pre.append(line + "\n");
  pre.scrollTop = pre.scrollHeight;
}
function videoRow(path) { return videos.find((v) => v.path === path); }

// A rebuild rewrites the .notes.ass, so the page shows what changes first. Its own Go starts the run.
async function run() {
  if (videos.some((v) => v.state === "rebuild")) { await openRebuildPreview(); return; }
  await startRun();
}
let embedAfterRebuild = false;
async function startRun() {
  keepNote = false;
  const r = await api("/api/run", { ...options(), embed: embedAfterRebuild });
  embedAfterRebuild = false;
  if (r.error) { note("left", "Can't start", r.error); return; }
  $("log").dataset.fresh = "yes";
  startPolling(true);
}
async function openRebuildPreview() {
  $("rebuildIntro").textContent = "Looking…";
  $("rebuildDiffs").replaceChildren();
  $("rebuildMsg").textContent = "";
  $("rebuildMsg").className = "msg";
  $("rebuildEmbedRow").hidden = true;
  $("rebuildEmbed").checked = false;
  $("rebuildGo").disabled = true;
  $("rebuild").showModal();
  const r = await api("/api/rebuild-preview", options());
  if (r.error) { $("rebuildIntro").textContent = r.error; return; }
  const films = r.films || [];
  if (!films.length) { $("rebuildIntro").textContent = "Nothing to rebuild here."; return; }
  $("rebuildIntro").textContent = `${plural(films.length, "subtitle file")} will be rebuilt from the notes. This is free: `
    + "nothing is sent to Claude. Each old .notes.ass is kept as a .bak first. Settings that change are marked.";
  $("rebuildDiffs").replaceChildren(...films.map(rebuildBlock));
  $("rebuildEmbedRow").hidden = !r.embedded;
  $("rebuildGo").disabled = false;
}
function rebuildBlock(f) {
  return el("section", { class: "dsection" },
    el("h3", {}, f.name),
    el("table", { class: "diff" },
      el("thead", {}, el("tr", {}, el("th", {}, "Setting"), el("th", {}, "Now"), el("th", {}, "After rebuild"))),
      el("tbody", {}, ...f.rows.map((x) => el("tr", { class: x.changed ? "changed" : "" },
        el("th", {}, x.setting), el("td", {}, x.now), el("td", {}, x.after))))),
    el("ul", { class: "entries" }, ...f.files.map((t) => el("li", {}, t))));
}
async function rebuildGo() {
  embedAfterRebuild = $("rebuildEmbed").checked;
  $("rebuild").close();
  await startRun();
}
function startPolling(fresh) {
  if (fresh) job = { next: 0 };
  lastEstimate = null;
  resetSteps(alignmentOn(), btsOn());
  setRunning(true);
  hideNote("left");
  showScreen();
  poll();
}
async function poll() {
  if (polling) return;
  polling = true;
  try {
    for (;;) {
      const r = await api(`/api/job?after=${job.next}`);
      if (r.error) { note("left", "Problem", r.error); setRunning(false); return; }
      for (const item of r.items || []) handle(item);
      job.next = r.next ?? job.next;
      if (!r.pending && asking) { stopCountdown(); hideNote("left"); asking = false; }
      if (!r.running) { finished(r); return; }
      await sleep(400);
    }
  } finally { polling = false; }
}
function handle(item) {
  if (item.text !== undefined) {
    log(item.text);
    const t = item.text.trim();
    if (t && !t.startsWith("$ ") && !t.startsWith("===")) subline(t);
    return;
  }
  const ev = item.event;
  if (ev.type === "video") {
    const v = videoRow(ev.path);
    if (v) { v.state = "working"; v.reason = null; renderVideos(); }
    title(stem(baseName(ev.path)), ev.total > 1 ? `Video ${ev.index} of ${ev.total}` : "");
    resetSteps(alignmentOn(), btsOn());
    hideNote("right");
  } else if (ev.type === "embed-video") {
    const v = videoRow(ev.path);
    if (v) { v.state = "working"; v.reason = null; renderVideos(); }
    title(stem(baseName(ev.path)), ev.total > 1 ? `Film ${ev.index} of ${ev.total}` : "");
    $("steps").hidden = true;
    hideNote("right");
  } else if (ev.type === "embed-result") {
    const v = videoRow(ev.path);
    if (v) {
      v.state = ev.result === "embedded" ? "ready" : "problem";
      v.reason = ev.result === "embedded" ? "The notes are inside the film." : ev.reason;
      renderVideos();
    }
  } else if (ev.type === "step") { step(ev.step); hideNote("right"); }
  else if (ev.type === "progress") progress(ev);
  else if (ev.type === "estimate") lastEstimate = ev;
  else if (ev.type === "usage") loadUsage();
  else if (ev.type === "question") ask(ev);
  else if (ev.type === "input") askText(ev);
  else if (ev.type === "video-result") {
    const v = videoRow(ev.path);
    if (v) {
      v.state = ev.result === "stopped" ? "problem" : "ready";
      v.reason = ev.result === "stopped" ? ev.reason : v.rebuild ? "Subtitle file rebuilt just now." : "Notes written just now.";
      renderVideos();
    }
    if (ev.result !== "stopped") { step("done"); hideNote("right"); }
  }
}

function costText(e) {
  const model = MODELS[e.model] || e.model;
  const cost = money(e.cost_usd);
  const price = e.route === "plan" ? ", on your Claude plan through Claude Code, with no API credits."
    : cost ? `, for ${cost} of API credit` : ". (The price of this model isn't known here.)";
  if (e.step === "research") {
    const commentary = e.commentary_tracks ? ` and read ${plural(e.commentary_tracks, "commentary track")}` : "";
    return `Claude will look the film up on the web${commentary}` + (e.searches ? ` (up to ${e.searches} searches)` : "")
      + `, in ${plural(e.requests, "request")} to ${model}${price}${cost && e.route !== "plan" ? "." : ""}`
      + " It keeps only facts it finds a source for.";
  }
  if (e.step === "refine") {
    let t = `Claude will look at ${plural(e.images, "contact sheet")} of frames, with the dialogue and your ${plural(e.notes, "note")}, in ${plural(e.requests, "request")} to ${model}${price}`;
    if (cost && e.route !== "plan") t += ".";
    if (e.mode === "visual-only") t += " The subtitles aren't in step with this video, so it will only add notes about what's on screen.";
    return t;
  }
  return `Claude will read ${plural(e.lines, "subtitle line")} in ${plural(e.requests, "request")} to ${model}${price}${cost && e.route !== "plan" ? "." : ""}`;
}
function creditText(e) {
  if (e.balance_usd == null || e.route === "plan") return "";
  let t = ` You have about ${dollars(Math.max(e.balance_usd, 0))} of credit left.`;
  if (e.cost_usd != null && e.cost_usd > e.balance_usd) t += " That's more than is left, so it may stop part-way; add credit and run it again to pick up.";
  return t;
}
const AUTO_SEND = 10;            // seconds the cost is shown before it's sent by itself (when that box is ticked)
let countdown = null;
function stopCountdown() {
  if (countdown) clearInterval(countdown);
  countdown = null;
}
function ask(ev) {
  stopCountdown();
  asking = true;
  const send = ev.id === "generate.send" || ev.id === "refine.send" || ev.id === "research.send";
  const plan = ev.id === "plan.fallback" || ev.id === "plan.allowance";
  const label = send ? "Cost" : ev.id && ev.id.endsWith(".resume") ? "Pick up" : ev.id === "credit.continue" ? "Credit"
    : plan ? "Claude plan" : "Question";
  const text = send && lastEstimate ? costText(lastEstimate) + creditText(lastEstimate) : ev.text;
  const buttons = ev.choices.map((c) => {
    let name = c.label.charAt(0).toUpperCase() + c.label.slice(1);
    if (send) name = c.key === "y" ? "Send to Claude" : "Don't send";
    if (ev.id === "credit.continue") name = c.key === "y" ? "Carry on anyway" : "Stop here";
    if (ev.id === "plan.fallback") name = c.key === "y" ? "Use API credits" : "Stop here";
    if (ev.id === "plan.allowance") name = c.key === "y" ? "Carry on with API credits" : "Stop here";
    const primary = send ? c.key === "y" : c.key === ev.default;
    return el("button", { type: "button", class: primary ? "primary" : null, "data-key": c.key,
                          onclick: () => answer(c.key) }, name);
  });
  const sendBtn = buttons.find((b) => b.dataset.key === "y");
  if (send && sendBtn && autoSendOn()) {
    const wait = el("button", { type: "button", onclick: () => {
      stopCountdown();
      sendBtn.textContent = "Send to Claude";
      wait.remove();
      sendBtn.focus();
    } }, "Wait");
    buttons.push(wait);
    const deadline = Date.now() + AUTO_SEND * 1000;
    const tick = () => {
      const left = Math.ceil((deadline - Date.now()) / 1000);
      if (left <= 0) { stopCountdown(); answer("y"); }
      else sendBtn.textContent = `Send to Claude (${left})`;
    };
    tick();
    countdown = setInterval(tick, 250);
  }
  hideNote("right");
  subline("");
  note("left", label, text, buttons);
  showScreen();
  const first = $("noteLeft").querySelector("button.primary") || $("noteLeft").querySelector("button");
  if (first) first.focus({ preventScroll: true });
}
function askText(ev) {
  asking = true;
  const input = el("input", { type: ev.hidden ? "password" : "text", "aria-label": ev.text });
  const ok = el("button", { type: "button", class: "primary", onclick: () => answer(input.value) }, "OK");
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") answer(input.value); });
  note("left", "Question", ev.text, [input, ok]);
  input.focus();
}
async function answer(text) {
  stopCountdown();
  for (const b of $("noteLeft").querySelectorAll("button, input")) b.disabled = true;
  const r = await api("/api/answer", { answer: text });
  if (!r.ok) note("left", "Problem", "That answer didn't reach the run. It may have finished already.");
  else { hideNote("left"); asking = false; }
}
async function cancel() {
  stopCountdown();
  $("cancelBtn").disabled = true;
  $("cancelBtn").textContent = "Stopping…";
  await api("/api/cancel", {});
  note("left", "Stopping", "Stopping. Notes Claude has already written are kept, and the next run can pick up from there.");
}
function finished(r) {
  stopCountdown();
  loadUsage();
  setRunning(false);
  hideNote("right");
  asking = false;
  const lines = $("log").textContent.trim().split("\n").filter((l) => l.trim());
  const last = lines.length ? lines[lines.length - 1].trim() : "";
  if (r.cancelled) {
    note("left", "Stopped", embedding ? "Cancelled. The film being worked on is exactly as it was."
      : "Cancelled. Notes already written are kept. Press Write the notes to pick up where it left off.");
  } else if (r.returncode === 0) {
    step("done");
    note("left", "Done", embedding ? "The notes are inside. Each original is kept in its film's context-notes folder until you delete it."
      : "Finished. Open a video in VLC from the list.");
  } else {
    note("left", "Stopped", `It stopped before the end: ${last || "see Details below."}`);
    $("logBox").open = true;
  }
  embedding = false;
  keepNote = true;
  refresh().then(() => { keepNote = false; });
}

