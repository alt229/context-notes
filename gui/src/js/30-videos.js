// ---------------------------------------------------------------- the list of videos
function stateOf(v) {
  if (v.done) return "ready";
  if (v.rebuild) return "rebuild";
  if (v.notes_stopped || v.refined === "stopped") return "stopped";
  return "todo";
}
function describe(v) {
  let notes;
  if (v.notes) {
    notes = plural(v.notes, "note") + (v.limit ? ` for the first ${clock(v.limit)}` : "");
    if (v.refined === "yes") notes += ", with the frames looked at";
    if (v.refined === "stopped") notes += "; looking at the frames stopped part-way";
    if (v.refine_unreadable) notes += `; Claude's reply about ${v.refine_unreadable} ${v.refine_unreadable === 1 ? "stretch" : "stretches"} of frames couldn't be read, so the next run sends just those again`;
  } else notes = v.notes_stopped ? "Writing the notes stopped part-way" : "No notes yet";
  if (v.track === BTS) notes = (v.facts != null ? `Looked up: ${plural(v.facts, "fact")}. ` : "Not looked up yet. ") + notes;
  if (v.unreadable) notes += `. Claude's reply for ${plural(v.unreadable, "part")} couldn't be read, so those lines have no notes yet; the next run sends just those again`;
  if (v.rebuild) notes += ". The subtitle file needs a rebuild for these settings (free)";
  const subs = v.subtitles ? `Subtitles: ${v.subtitles}` : "No subtitles beside it yet; it will look inside the video, then online";
  return `${notes}. ${subs}.`;
}
function lookText(look) {
  if (!look) return "its look isn't recorded";
  const solid = look.opacity == null ? "" : `, ${Math.round(look.opacity)}% solid`;
  return `box: ${look.background}${solid}; ${Math.round(look.wpm)} words a minute`;
}
// The film's state inside the .mkv, for the track the form is set to.
function insideFor(v) {
  const i = v.inside;
  if (!i || !i.tracks || i.action === "skip") return i;     // skipped as a whole (an .mp4, a link, ...): its reason
  const key = btsOn() ? BTS : "context";
  if (i.tracks[key]) return { ...i, ...i.tracks[key] };
  return { ...i, action: "skip", reason: key === BTS ? "no Behind the Scenes notes yet" : "no context notes yet" };
}
function insideText(i) {
  if (i.action === "current") return `Inside the film: yes, these notes. Look: ${lookText(i.look)}. To change it, set the look under How the notes look, press Rebuild (free), then Embed.`;
  if (i.action === "update") return `Inside the film: older notes. They changed since they went in, so Embed puts them in again (a full rewrite). Look inside now: ${lookText(i.look)}.`;
  if (i.action === "add") return "Inside the film: not yet. Embed can put them in.";
  return `Inside the film: no (${i.reason}).`;
}
function renderVideos() {
  const list = $("videoList");
  list.replaceChildren();
  $("videosEmpty").hidden = videos.length > 0;
  for (const v of videos) {
    const acts = [];
    if (v.state === "ready" || (v.ass && v.state !== "working")) {
      acts.push(el("button", { type: "button", class: "btn local-only", onclick: () => openVlc(v) }, "Open in VLC"));
      acts.push(el("button", { type: "button", class: "btn quiet local-only", onclick: () => reveal(v) }, "Show in folder"));
    }
    list.append(el("li", {},
      el("div", { class: "name" }, v.name),
      el("div", { class: `state ${v.state}` }, v.stateText || STATES[v.state]),
      el("div", { class: "meta" }, v.reason ? v.reason : describe(v)),
      v.inside ? el("div", { class: "meta inside" }, insideText(insideFor(v))) : null,
      acts.length ? el("div", { class: "acts" }, acts) : null));
  }
  $("titleField").hidden = videos.length > 1;
  updateRunButton();
}
function onlyRebuilds() {
  const left = videos.filter((v) => v.state !== "ready");
  return left.length > 0 && left.every((v) => v.state === "rebuild") && !$("redo").checked && !again();
}
function again() { return btsOn() && $("research_again").checked; }
function updateRunButton() {
  const todo = videos.filter((v) => v.state !== "ready").length;
  const btn = $("runBtn");
  const redo = $("redo").checked || again();
  btn.disabled = running || !videos.length || (!todo && !redo);
  btn.textContent = videos.length && !todo && !redo ? "Everything here is done"
    : onlyRebuilds() ? "Rebuild (free)" : btsOn() ? "Make Behind the Scenes" : "Write the notes";
}

// What has to be set up before Claude can write notes, or null: Claude Code on the plan, the API key otherwise.
function setupNeeded() {
  if (!info) return null;
  if (onPlan()) return info.claude && info.claude.problem
    ? `${info.claude.problem} Or choose API credits in Settings, Claude.` : null;
  return info.key.found ? null : "Add your Anthropic API key in Settings. It's only needed when Claude writes notes.";
}
function idleScreen() {
  title("Choose a film", "or a folder of episodes. Claude writes the notes, and they play in VLC.");
  hideNote("right");
  if (!keepNote) {
    if (setupNeeded()) note("left", "Before you start", setupNeeded());
    else note("left", "How it works", "Pick a film below. You choose how the notes are written, see the cost, and then Claude writes them. Nothing is sent until you say so.");
  }
  subline("");
}
function readyScreen() {
  const p = $("path").value.trim();
  const one = videos.length === 1;
  const ready = videos.filter((v) => v.state === "ready").length;
  const rebuild = videos.filter((v) => v.state === "rebuild").length;
  const name = one ? stem(videos[0].name) : baseName(p);
  let sub;
  if (one) sub = { ready: "Ready to watch.", stopped: "Stopped part-way; it can pick up from there.",
                   rebuild: "Notes written. The subtitle file needs a rebuild (free)." }[videos[0].state] || "No notes yet.";
  else sub = `${plural(videos.length, "video")}: ${ready} ready, ` + (rebuild ? `${rebuild} to rebuild, ` : "")
    + `${videos.length - ready - rebuild} to do.`;
  title(name, sub);
  hideNote("right");
  const old = videos.filter((v) => v.tidy > 0).length;
  if (old) note("right", "Tidy up", (one ? "This film still has its" : old === 1 ? "1 film here still has its" : `${old} films here still have their`)
    + " working files beside the video, where an earlier version left them. They work there; Tidy moves them into a "
    + "context-notes folder.", [el("button", { type: "button", class: "primary", onclick: openTidy }, "Tidy…")]);
  const toEmbed = videos.filter((v) => v.inside && (v.inside.action === "add" || v.inside.action === "update")).length;
  if (!old && toEmbed) note("right", "Embed", (one ? "This film's" : `${plural(toEmbed, "film")}'s`) + " notes can go inside the .mkv "
    + "as a subtitle track, so the notes travel with the film. It's free and nothing is re-encoded.",
    [el("button", { type: "button", onclick: openEmbed }, "Embed…")]);
  if (!keepNote) {
    if (setupNeeded()) note("left", "Before you start", setupNeeded());
    else if (videos.length && ready === videos.length) note("left", "Ready", "Everything here has notes. Open a video in VLC from the list.");
    else if (onlyRebuilds()) note("left", "Next", "Press Rebuild. It only remakes the subtitle file with these settings, so it's quick, and nothing is sent to Claude.");
    else if (btsOn()) note("left", "Next", "Press Make Behind the Scenes. Claude looks the film up first (its commentary tracks, if any, and the web), then places what it found on the film. You'll see the cost before each step.");
    else note("left", "Next", "Choose how the notes are written, then press Write the notes. You'll see the cost first.");
  }
  subline("");
}

let statusSeq = 0;
async function refresh() {
  const o = options();
  const seq = ++statusSeq;
  if (!o.path) { videos = []; renderVideos(); idleScreen(); return; }
  $("pathHint").classList.remove("bad");
  const slow = setTimeout(() => { if (seq === statusSeq) $("pathHint").textContent = "Looking… a network drive can take minutes"; }, 350);
  let r = await api("/api/status", o);
  if (r.id) {
    const id = r.id;
    for (r = { pending: true }; r.pending; ) {
      await new Promise((done) => setTimeout(done, 1500));
      if (seq !== statusSeq) { clearTimeout(slow); return; }
      r = await api(`/api/status?id=${encodeURIComponent(id)}`);
    }
  }
  clearTimeout(slow);
  if (seq !== statusSeq) return;
  if (r.error) {
    videos = [];
    renderVideos();
    $("pathHint").textContent = r.error;
    $("pathHint").classList.add("bad");
    idleScreen();
    return;
  }
  $("pathHint").textContent = "";
  videos = r.videos.map((v) => ({ ...v, state: stateOf(v) }));
  renderVideos();
  readyScreen();
}
function setPath(p) {
  $("path").value = p;
  rememberStartFolder(p);
  keepNote = false;
  refresh();
}

