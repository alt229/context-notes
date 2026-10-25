// The options form: reading it (for /api/status and /api/run), remembering it between visits, and the language lists.
(() => {
  const { $, el, store, state } = CN;

  function options() {
    return {
      path: $("path").value.trim(), recursive: $("recursive").checked,
      quality: document.querySelector("input[name=quality]:checked").value,
      film_language: $("film_language").value, refine: $("refine").checked, limit: $("limit").value.trim(),
      subs_language: $("subs_language").value, show_subs: $("show_subs").value,
      notes_language: $("notes_language").value.trim(), show: $("show").value.trim(),
      title: state.videos.length === 1 ? $("titleInput").value.trim() : "",
      check_alignment: $("check_alignment").checked, frames: $("dense").checked ? "dense" : "keyframes",
      redo: $("redo").checked,
    };
  }
  const REMEMBERED = ["recursive", "film_language", "refine", "limit", "subs_language", "show_subs", "notes_language",
                      "show", "check_alignment", "dense", "redo"];
  function remember() {
    const o = {};
    for (const id of REMEMBERED) o[id] = $(id).type === "checkbox" ? $(id).checked : $(id).value;
    o.quality = document.querySelector("input[name=quality]:checked").value;
    store.set("options", o);
    store.set("path", $("path").value.trim());
  }
  function restore() {
    const o = store.get("options", {});
    for (const id of REMEMBERED) {
      if (!(id in o)) continue;
      if ($(id).type === "checkbox") $(id).checked = !!o[id]; else $(id).value = o[id];
    }
    const q = document.querySelector(`input[name=quality][value="${o.quality}"]`);
    if (q) q.checked = true;
    $("path").value = store.get("path", "");
  }

  function fillLanguages() {
    for (const id of ["film_language", "subs_language", "show_subs"]) {
      const sel = $(id);
      for (const l of state.info.languages) sel.append(el("option", { value: l.code }, l.name));
    }
  }

  Object.assign(CN, { options, REMEMBERED, remember, restore, fillLanguages });
})();
