// ---------------------------------------------------------------- change or delete (each action has its own Go)
function openDanger() {
  $("backupsIntro").textContent = "Looking…";
  $("backupsList").replaceChildren();
  $("backupsMsg").textContent = "";
  $("backupsMsg").className = "msg";
  $("backupsGo").hidden = true;
  $("backupsGo").disabled = false;
  renderRedo();
  $("danger").showModal();
  listBackups();
}
async function listBackups() {
  const r = await api("/api/backups", { path: $("path").value.trim(), recursive: $("recursive").checked });
  if (r.error) { $("backupsIntro").textContent = r.error; return; }
  const found = r.backups || [];
  if (!found.length) { $("backupsIntro").textContent = "No kept originals to delete here."; return; }
  const total = found.reduce((n, b) => n + b.size, 0);
  $("backupsIntro").textContent = `${plural(found.length, "kept original")} (${sizeText(total)}) will be deleted. Each is the `
    + "original file from before its notes went inside or before it became an MKV, so the films keep their notes. "
    + "This can't be undone.";
  $("backupsList").replaceChildren(...found.map((b) => el("li", {},
    el("p", { class: "tidyvideo" }, baseName(b.path)), el("p", { class: "tidyfiles" }, sizeText(b.size)))));
  $("backupsGo").hidden = false;
}
function renderRedo() {
  const films = videos.filter((v) => v.notes > 0);
  $("redoList").replaceChildren(...films.map((v) => el("li", {},
    el("p", { class: "tidyvideo" }, v.name),
    el("p", { class: "tidyfiles" }, `${plural(v.notes, "note")} now; the current notes are kept as a .bak`))));
  $("redoIntro").textContent = films.length
    ? `Writes the notes again for ${plural(films.length, "film")}, with the settings above. The notes they have now are kept `
      + "as a backup (.bak), and no film is deleted. Claude is sent the subtitles and frames again, so this costs money; "
      + "the cost is shown before anything is sent."
    : "None of the films here have notes yet, so there's nothing to write again.";
  $("redoGo").disabled = films.length === 0;
}
async function backupsGo() {
  $("backupsGo").disabled = true;
  const r = await api("/api/backups", { path: $("path").value.trim(), recursive: $("recursive").checked, go: true });
  if (r.error) { $("backupsMsg").textContent = r.error; $("backupsMsg").className = "msg bad"; $("backupsGo").disabled = false; return; }
  $("danger").close();
  embedding = true;
  $("log").dataset.fresh = "yes";
  startPolling(true);
}
async function redoGo() {
  $("redo").checked = true;               // read by the run that starts now, then cleared
  $("danger").close();
  await startRun();
  $("redo").checked = false;
}

async function openEmbed() {
  $("embedConvert").checked = false;
  $("embed").showModal();
  await listEmbed();
}
async function listEmbed() {
  $("embedIntro").textContent = "Looking…";
  $("embedList").replaceChildren();
  $("embedMsg").textContent = "";
  $("embedMsg").className = "msg";
  $("embedDefaultRow").hidden = true;
  $("embedBtn").hidden = false;
  $("embedBtn").disabled = true;
  const r = await api("/api/embed", embedTarget());
  if (r.error) { $("embedIntro").textContent = r.error; $("embedBtn").hidden = true; return; }
  const todo = r.videos.filter((v) => v.action === "add" || v.action === "update");
  const rest = r.videos.filter((v) => !(v.action === "add" || v.action === "update"));
  $("embedMsg").textContent = rest.length ? "Not now: " + rest.map((v) => `${baseName(v.video)} (${v.reason})`).join("; ") : "";
  if (!todo.length) { $("embedIntro").textContent = "Nothing to put inside here."; $("embedBtn").hidden = true; return; }
  const total = todo.reduce((n, v) => n + v.size, 0);
  const biggest = Math.max(...todo.map((v) => v.size));
  $("embedIntro").textContent = `${plural(todo.length, "film")} (${sizeText(total)}) get their notes inside as a subtitle `
    + `track called "Context Notes". Nothing is re-encoded and nothing is sent to Claude. Each film is rewritten as a `
    + `new file first, checked, then swapped in; your original is kept in its context-notes folder until you delete `
    + `it. It needs about ${sizeText(biggest)} free while it works. `
    + `About ${minsText(todo.reduce((n, v) => n + (v.seconds_low || 0), 0))} to `
    + `${minsText(todo.reduce((n, v) => n + (v.seconds_high || 0), 0))} on this NAS, estimated from its speed: each film `
    + `is read and rewritten whole. No Claude or API calls are made.`;
  const converting = todo.filter((v) => v.convert).length;
  if (converting) $("embedIntro").textContent += ` ${plural(converting, "MP4 film")} become MKV first; each .mp4 is kept in context-notes/originals.`;
  $("embedList").replaceChildren(...todo.map((v) => el("li", {},
    el("p", { class: "tidyvideo" }, baseName(v.video)),
    el("p", { class: "tidyfiles" }, `${v.convert ? "Converts to MKV, then adds the notes" : v.action === "update" ? "Replaces the earlier notes inside" : "Adds the notes"} · ${sizeText(v.size)}`))));
  $("embedDefaultRow").hidden = false;
  $("embedBtn").disabled = false;
  $("embedBtn").focus();
}
async function doEmbed() {
  $("embedBtn").disabled = true;
  const r = await api("/api/embed", { ...embedTarget(), go: true, default: $("embedDefault").checked });
  if (r.error) { $("embedMsg").textContent = r.error; $("embedMsg").className = "msg bad"; $("embedBtn").disabled = false; return; }
  $("embed").close();
  embedding = true;
  $("log").dataset.fresh = "yes";
  startPolling(true);
}

