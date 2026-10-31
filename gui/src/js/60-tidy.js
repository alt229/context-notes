// ---------------------------------------------------------------- tidy (tidy.py)
function tidyTarget() { return { path: $("path").value.trim(), recursive: $("recursive").checked }; }
async function openTidy() {
  $("tidyIntro").textContent = "Looking…";
  $("tidyList").replaceChildren();
  $("tidyMsg").textContent = "";
  $("tidyMsg").className = "msg";
  $("tidyBtn").hidden = false;
  $("tidyBtn").disabled = true;
  $("tidyNo").textContent = "Not now";
  $("tidySubs").hidden = true;
  $("tidy").showModal();
  const r = await api("/api/tidy", tidyTarget());
  if (r.error) { $("tidyIntro").textContent = r.error; $("tidyBtn").hidden = true; return; }
  showDamagedSubs(r.subs || []);
  const items = r.videos.reduce((n, v) => n + v.items.length, 0);
  if (!items) { $("tidyIntro").textContent = "Nothing to tidy here."; $("tidyBtn").hidden = true; return; }
  $("tidyIntro").textContent = `${plural(items, "item")} for ${plural(r.videos.length, "video")} ${items === 1 ? "moves" : "move"} into a `
    + "context-notes folder beside the videos, one folder for each video. They're moved as they are: nothing is "
    + "changed or deleted, and the notes keep working. Beside each video stay the notes for VLC and Plex and its "
    + "subtitles.";
  $("tidyList").replaceChildren(...r.videos.map((v) => el("li", {},
    el("p", { class: "tidyvideo" }, baseName(v.video)),
    el("p", { class: "tidyfiles" }, v.items.map((i) => i.folder ? `${i.from}/ (becomes ${i.to}/)`
      : i.to !== i.from ? `${i.from} (becomes ${i.to}: that name is taken)` : i.from).join(" · ")))));
  if (r.skipped.length) $("tidyMsg").textContent = "Staying where they are: "
    + r.skipped.map((s) => `${baseName(s.path)} (${s.reason})`).join("; ");
  $("tidyBtn").disabled = false;
  $("tidyBtn").focus();
}
// subcheck.py's findings (subs-check events): one entry per damaged file, each kind of damage with an example
function showDamagedSubs(subs) {
  $("tidySubs").hidden = !subs.length;
  $("tidySubsList").replaceChildren(...subs.map((s) => el("li", {},
    el("p", { class: "tidyvideo" }, `${baseName(s.video)}: ${s.where}`),
    el("p", { class: "tidyfiles" }, Object.entries(s.problems).map(([kind, p]) =>
      `${DAMAGE[kind] || kind}: ${p.count}${p.examples.length ? ` (e.g. ${p.examples[0]})` : ""}`).join(" · ")))));
}
const DAMAGE = {
  mangled: "mangled characters", lookalike: "look-alike letters", broken: "words broken by spaces",
  "l-for-I": "a small L for a capital I", unreadable: "unreadable characters", mislabeled: "mislabeled or corrupted",
};
async function doTidy() {
  $("tidyBtn").disabled = true;
  $("tidyMsg").className = "msg";
  $("tidyMsg").textContent = "Moving…";
  const r = await api("/api/tidy", { ...tidyTarget(), move: true });
  const d = r.done || { moved: 0, problems: [] };
  if (r.error) { $("tidyMsg").textContent = r.error; $("tidyMsg").className = "msg bad"; $("tidyBtn").disabled = false; return; }
  $("tidyMsg").textContent = `Moved ${plural(d.moved, "item")}.` + (d.problems.length ? " Left where they are: "
    + d.problems.map((p) => `${baseName(p.path)} (${p.reason})`).join("; ") : "");
  $("tidyMsg").className = d.problems.length ? "msg bad" : "msg ok";
  $("tidyBtn").hidden = true;
  $("tidyNo").textContent = "Done";
  refresh();
}

