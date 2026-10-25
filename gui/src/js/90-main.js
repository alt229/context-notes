// Wiring the buttons and fields to the components, then starting.
(() => {
  const { $, state } = CN;

  for (const d of document.querySelectorAll("dialog")) {
    d.querySelector("[data-close]").addEventListener("click", () => d.close());
  }
  $("settingsBtn").addEventListener("click", async () => { await CN.reloadInfo(); $("settings").showModal(); });
  $("bannerKeyBtn").addEventListener("click", async () => { await CN.reloadInfo(); $("settings").showModal(); $("keyInput").focus(); });
  for (const r of document.querySelectorAll("input[name=backend]")) r.addEventListener("change", CN.saveBackend);
  $("saveKeyBtn").addEventListener("click", CN.saveKey);
  $("keyInput").addEventListener("keydown", (e) => { if (e.key === "Enter") CN.saveKey(); });
  $("testKeyBtn").addEventListener("click", CN.testKey);
  $("saveOsBtn").addEventListener("click", CN.saveOs);
  $("installVlcBtn").addEventListener("click", CN.installVlc);
  $("pickFile").addEventListener("click", () => CN.pick("file"));
  $("pickFolder").addEventListener("click", () => CN.pick("folder"));
  $("browseBtn").addEventListener("click", CN.openBrowser);
  $("useFolderBtn").addEventListener("click", () => { $("browser").close(); CN.setPath(state.browsing); });
  $("path").addEventListener("change", () => { CN.remember(); CN.refresh(); });
  $("path").addEventListener("keydown", (e) => { if (e.key === "Enter") { CN.remember(); CN.refresh(); } });
  for (const id of ["recursive", "film_language", "subs_language", "limit", "refine", "redo"]) {
    $(id).addEventListener("change", () => { CN.remember(); CN.refresh(); });
  }
  for (const id of ["show_subs", "notes_language", "show", "check_alignment", "dense"]) $(id).addEventListener("change", CN.remember);
  for (const r of document.querySelectorAll("input[name=quality]")) r.addEventListener("change", CN.remember);
  $("runBtn").addEventListener("click", CN.run);
  $("cancelBtn").addEventListener("click", CN.cancel);

  (async () => {
    if (!(await CN.reloadInfo())) return;
    CN.fillLanguages();
    CN.restore();
    if (state.info.running) {
      await CN.refresh();
      $("log").dataset.fresh = "yes";
      CN.startPolling(true);
      return;
    }
    CN.refresh();
  })();
})();
