// Choosing a film or folder: the path box, the system file dialogs, and the page's own file browser dialog.
(() => {
  const { $, el, api, state } = CN;

  let statusSeq = 0;
  async function refresh() {
    const o = CN.options();
    const seq = ++statusSeq;
    if (!o.path) { state.videos = []; CN.renderVideos(); CN.idleScreen(); return; }
    $("pathHint").classList.remove("bad");
    const slow = setTimeout(() => { if (seq === statusSeq) $("pathHint").textContent = "Looking…"; }, 350);
    const r = await api("/api/status", o);
    clearTimeout(slow);
    if (seq !== statusSeq) return;
    if (r.error) {
      state.videos = [];
      CN.renderVideos();
      $("pathHint").textContent = r.error;
      $("pathHint").classList.add("bad");
      CN.idleScreen();
      return;
    }
    $("pathHint").textContent = "";
    state.videos = r.videos.map((v) => ({ ...v, state: CN.stateOf(v) }));
    CN.renderVideos();
    CN.readyScreen();
  }
  function setPath(p) {
    $("path").value = p;
    CN.remember();
    state.keepNote = false;
    refresh();
  }

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

  async function openBrowser() {
    $("browser").showModal();
    await loadDir($("path").value.trim());
  }
  async function loadDir(path) {
    const r = await api(`/api/browse?path=${encodeURIComponent(path || "")}`);
    if (r.error && !r.path) { $("browseError").hidden = false; $("browseError").textContent = r.error; return; }
    state.browsing = r.path;
    $("where").textContent = r.path;
    $("browseError").hidden = !r.error;
    $("browseError").textContent = r.error || "";
    $("upBtn").disabled = !r.parent;
    $("upBtn").onclick = () => loadDir(r.parent);
    $("places").replaceChildren(...(r.places || []).map((p) =>
      el("button", { type: "button", class: "btn", onclick: () => loadDir(p.path) }, p.label)));
    const join = (name) => r.path.replace(/\/+$/, "") + "/" + name;
    const items = [
      ...r.dirs.map((d) => el("li", {}, el("button", { type: "button", onclick: () => loadDir(join(d)) }, d, el("span", { class: "kind" }, "folder")))),
      ...r.videos.map((v) => el("li", {}, el("button", { type: "button", onclick: () => { $("browser").close(); setPath(join(v)); } }, v, el("span", { class: "kind" }, "video")))),
    ];
    if (!items.length) items.push(el("li", {}, el("p", { class: "empty" }, "No folders or videos here.")));
    $("entries").replaceChildren(...items);
  }

  Object.assign(CN, { refresh, setPath, pick, openBrowser, loadDir });
})();
