// The list of videos: what each one's state is, how it's described, and its Open in VLC / Show in folder buttons
// (or, when the app runs on another computer, its path as text to copy).
(() => {
  const { $, el, api, plural, clock, STATES, state } = CN;

  function stateOf(v) {
    if (v.done) return "ready";
    if (v.notes_stopped || v.refined === "stopped") return "stopped";
    return "todo";
  }
  function describe(v) {
    let notes;
    if (v.notes) {
      notes = plural(v.notes, "note") + (v.limit ? ` for the first ${clock(v.limit)}` : "");
      if (v.refined === "yes") notes += ", with the frames looked at";
      if (v.refined === "stopped") notes += "; looking at the frames stopped part-way";
    } else notes = v.notes_stopped ? "Writing the notes stopped part-way" : "No notes yet";
    const subs = v.subtitles ? `Subtitles: ${v.subtitles}` : "No subtitles beside it yet; it will look inside the video, then online";
    return `${notes}. ${subs}.`;
  }
  function renderVideos() {
    const { videos } = state;
    const list = $("videoList");
    list.replaceChildren();
    $("videosEmpty").hidden = videos.length > 0;
    for (const v of videos) {
      const acts = [];
      const hosted = !!(state.info && state.info.hosted);
      if (hosted) {
        if (v.path) acts.push(el("span", { class: "path" }, v.path));
      } else if (v.state === "ready" || (v.ass && v.state !== "working")) {
        acts.push(el("button", { type: "button", class: "btn", onclick: () => openVlc(v) }, "Open in VLC"));
        acts.push(el("button", { type: "button", class: "btn quiet", onclick: () => reveal(v) }, "Show in folder"));
      }
      list.append(el("li", {},
        el("div", { class: "name" }, v.name),
        el("div", { class: `state ${v.state}` }, v.stateText || STATES[v.state]),
        el("div", { class: "meta" }, v.reason ? v.reason : describe(v)),
        acts.length ? el("div", { class: "acts" }, acts) : null));
    }
    $("titleField").hidden = videos.length > 1;
    CN.updateRunButton();
  }

  async function openVlc(v) {
    const r = await api("/api/vlc/open", { path: v.path });
    if (!r.ok) CN.note("left", "VLC", r.message || r.error || "Couldn't open VLC.");
    else if (state.info && !state.info.vlc.some((x) => x.installed)) CN.note("left", "VLC", "Opening it in VLC. To see the notes there, install the VLC extension in Settings.");
  }
  async function reveal(v) {
    const r = await api("/api/reveal", { path: v.path });
    if (!r.ok) CN.note("left", "Folder", r.message || r.error || "Couldn't open the folder.");
  }

  Object.assign(CN, { stateOf, describe, renderVideos, openVlc, reveal });
})();
