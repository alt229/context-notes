// ---------------------------------------------------------------- choosing a film or folder
async function pick(kind) {
  const btn = $(kind === "folder" ? "pickFolder" : "pickFile");
  btn.disabled = true;
  $("pathHint").classList.remove("bad");
  $("pathHint").textContent = "The file dialog is open. It may be behind this window.";
  const r = await api("/api/pick", { kind });
  btn.disabled = false;
  $("pathHint").textContent = "";
  if (r.path) setPath(r.path);
  else if (r.no_dialog) { $("pathHint").textContent = r.error; openBrowser(); }
  else if (r.error) { $("pathHint").textContent = r.error; $("pathHint").classList.add("bad"); }
}

let browsing = "";
async function openBrowser() {
  $("browser").showModal();
  await loadDir($("path").value.trim());
}
async function loadDir(path) {
  const r = await api(`/api/browse?path=${encodeURIComponent(path || "")}`);
  if (r.error && !r.path) { $("browseError").hidden = false; $("browseError").textContent = r.error; return; }
  browsing = r.path;
  $("where").textContent = r.path;
  $("browseError").hidden = !r.error;
  $("browseError").textContent = r.error || "";
  $("upBtn").disabled = !r.parent;
  $("upBtn").onclick = () => loadDir(r.parent);
  $("places").replaceChildren(...(r.places || []).map((p) =>
    el("button", { type: "button", class: "btn", onclick: () => loadDir(p.path) }, p.label)));
  const items = [
    ...r.dirs.map((d) => el("li", {}, el("button", { type: "button", onclick: () => loadDir(d.path) }, d.name, el("span", { class: "kind" }, "folder")))),
    ...r.videos.map((v) => el("li", {}, el("button", { type: "button", onclick: () => { $("browser").close(); setPath(v.path); } }, v.name, el("span", { class: "kind" }, "video")))),
  ];
  if (!items.length) items.push(el("li", {}, el("p", { class: "empty" }, "No folders or videos here.")));
  $("entries").replaceChildren(...items);
}

