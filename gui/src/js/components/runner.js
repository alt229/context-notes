// Running: the Write the notes and Cancel buttons, following the job, and the questions a run asks.
(() => {
  const { $, el, api, sleep, plural, money, stem, baseName, MODELS, state } = CN;

  function updateRunButton() {
    const todo = state.videos.filter((v) => v.state !== "ready").length;
    const btn = $("runBtn");
    btn.disabled = state.running || !state.videos.length || (!todo && !$("redo").checked);
    btn.textContent = state.videos.length && !todo && !$("redo").checked ? "Everything here is done" : "Write the notes";
  }
  function setRunning(on) {
    state.running = on;
    $("optionsSet").disabled = on;
    for (const id of ["path", "pickFile", "pickFolder", "browseBtn", "recursive"]) $(id).disabled = on;
    $("cancelBtn").hidden = !on;
    $("runBtn").hidden = on;
    $("cancelBtn").disabled = false;
    $("cancelBtn").textContent = "Cancel";
    updateRunButton();
  }
  function videoRow(path) { return state.videos.find((v) => v.path === path); }

  async function run() {
    CN.remember();
    state.keepNote = false;
    const r = await api("/api/run", CN.options());
    if (r.error) { CN.note("left", "Can't start", r.error); return; }
    $("log").dataset.fresh = "yes";
    startPolling(true);
  }
  function startPolling(fresh) {
    if (fresh) state.job = { next: 0 };
    state.lastEstimate = null;
    CN.resetSteps($("check_alignment").checked);
    setRunning(true);
    CN.hideNote("left");
    poll();
  }
  async function poll() {
    if (state.polling) return;
    state.polling = true;
    try {
      for (;;) {
        const r = await api(`/api/job?after=${state.job.next}`);
        if (r.error) { CN.note("left", "Problem", r.error); setRunning(false); return; }
        for (const item of r.items || []) handle(item);
        state.job.next = r.next ?? state.job.next;
        if (!r.pending && state.asking) { CN.hideNote("left"); state.asking = false; }
        if (!r.running) { finished(r); return; }
        await sleep(400);
      }
    } finally { state.polling = false; }
  }
  function handle(item) {
    if (item.text !== undefined) {
      CN.log(item.text);
      const t = item.text.trim();
      if (t && !t.startsWith("$ ") && !t.startsWith("===")) CN.subline(t);
      return;
    }
    const ev = item.event;
    if (ev.type === "video") {
      const v = videoRow(ev.path);
      if (v) { v.state = "working"; v.reason = null; CN.renderVideos(); }
      CN.title(stem(baseName(ev.path)), ev.total > 1 ? `Video ${ev.index} of ${ev.total}` : "");
      CN.resetSteps($("check_alignment").checked);
      CN.hideNote("right");
    } else if (ev.type === "step") { CN.step(ev.step); CN.hideNote("right"); }
    else if (ev.type === "progress") CN.progress(ev);
    else if (ev.type === "estimate") state.lastEstimate = ev;
    else if (ev.type === "question") ask(ev);
    else if (ev.type === "input") askText(ev);
    else if (ev.type === "video-result") {
      const v = videoRow(ev.path);
      if (v) {
        v.state = ev.result === "stopped" ? "problem" : "ready";
        v.reason = ev.result === "stopped" ? ev.reason : "Notes written just now.";
        CN.renderVideos();
      }
      if (ev.result !== "stopped") { CN.step("done"); CN.hideNote("right"); }
    }
  }

  function costText(e) {
    const model = MODELS[e.model] || e.model;
    const cost = money(e.cost_usd);
    const sub = e.backend === "claude-code";
    const price = sub ? ", on your Claude subscription (no API credits)."
      : cost ? `, for ${cost} of API credit.` : ". (The price of this model isn't known here.)";
    if (e.step === "refine") {
      let t = `Claude will look at ${plural(e.images, "contact sheet")} of frames, with the dialogue and your ${plural(e.notes, "note")}, in ${plural(e.requests, "request")} to ${model}${price}`;
      if (e.mode === "visual-only") t += " The subtitles aren't in step with this video, so it will only add notes about what's on screen.";
      return t;
    }
    return `Claude will read ${plural(e.lines, "subtitle line")} in ${plural(e.requests, "request")} to ${model}${price}`;
  }
  function ask(ev) {
    state.asking = true;
    const send = ev.id === "generate.send" || ev.id === "refine.send";
    const onSubscription = send && state.lastEstimate && state.lastEstimate.backend === "claude-code";
    const label = send ? (onSubscription ? "Ready to send" : "Cost") : ev.id && ev.id.endsWith(".resume") ? "Pick up" : "Question";
    const text = send && state.lastEstimate ? costText(state.lastEstimate) : ev.text;
    const buttons = ev.choices.map((c) => {
      let name = c.label.charAt(0).toUpperCase() + c.label.slice(1);
      if (send) name = c.key === "y" ? "Send to Claude" : "Don't send";
      const primary = send ? c.key === "y" : c.key === ev.default;
      return el("button", { type: "button", class: primary ? "primary" : null, onclick: () => answer(c.key) }, name);
    });
    CN.hideNote("right");
    CN.subline("");
    CN.note("left", label, text, buttons);
    const first = $("noteLeft").querySelector("button.primary") || $("noteLeft").querySelector("button");
    if (first) first.focus({ preventScroll: true });
  }
  function askText(ev) {
    state.asking = true;
    const input = el("input", { type: ev.hidden ? "password" : "text", "aria-label": ev.text });
    const ok = el("button", { type: "button", class: "primary", onclick: () => answer(input.value) }, "OK");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") answer(input.value); });
    CN.note("left", "Question", ev.text, [input, ok]);
    input.focus();
  }
  async function answer(text) {
    for (const b of $("noteLeft").querySelectorAll("button, input")) b.disabled = true;
    const r = await api("/api/answer", { answer: text });
    if (!r.ok) CN.note("left", "Problem", "That answer didn't reach the run. It may have finished already.");
    else { CN.hideNote("left"); state.asking = false; }
  }
  async function cancel() {
    $("cancelBtn").disabled = true;
    $("cancelBtn").textContent = "Stopping…";
    await api("/api/cancel", {});
    CN.note("left", "Stopping", "Stopping. Notes Claude has already written are kept, and the next run can pick up from there.");
  }
  function finished(r) {
    setRunning(false);
    CN.hideNote("right");
    state.asking = false;
    const lines = $("log").textContent.trim().split("\n").filter((l) => l.trim());
    const last = lines.length ? lines[lines.length - 1].trim() : "";
    if (r.cancelled) {
      CN.note("left", "Stopped", "Cancelled. Notes already written are kept. Press Write the notes to pick up where it left off.");
    } else if (r.returncode === 0) {
      CN.step("done");
      CN.note("left", "Done", "Finished. Open a video in VLC from the list.");
    } else {
      CN.note("left", "Stopped", `It stopped before the end: ${last || "see Details below."}`);
      $("logBox").open = true;
    }
    state.keepNote = true;
    CN.refresh().then(() => { state.keepNote = false; });
  }

  Object.assign(CN, { updateRunButton, setRunning, videoRow, run, startPolling, poll, handle, costText, ask, askText, answer, cancel, finished });
})();
