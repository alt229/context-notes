// ---------------------------------------------------------------- start
for (const d of document.querySelectorAll("dialog")) {
  d.querySelector("[data-close]").addEventListener("click", () => d.close());
}
$("settingsBtn").addEventListener("click", async () => { await reloadInfo(); $("settings").showModal(); });
$("bannerKeyBtn").addEventListener("click", async () => {
  await reloadInfo();
  $("settings").showModal();
  (onPlan() ? $("claudeCheckBtn") : $("keyInput")).focus();
});
$("saveKeyBtn").addEventListener("click", saveKey);
$("keyInput").addEventListener("keydown", (e) => { if (e.key === "Enter") saveKey(); });
$("testKeyBtn").addEventListener("click", testKey);
$("saveOsBtn").addEventListener("click", saveOs);
$("saveCreditBtn").addEventListener("click", saveCredit);
$("creditInput").addEventListener("keydown", (e) => { if (e.key === "Enter") saveCredit(); });
$("apiMeter").addEventListener("click", async () => { await reloadInfo(); $("settings").showModal(); $("creditInput").focus(); });
$("sessionMeter").addEventListener("click", refreshPlan);
$("installVlcBtn").addEventListener("click", installVlc);
$("tidyBtn").addEventListener("click", doTidy);
$("tidyNo").addEventListener("click", () => $("tidy").close());
$("embedBtn").addEventListener("click", doEmbed);
$("embedNo").addEventListener("click", () => $("embed").close());
$("embedConvert").addEventListener("change", listEmbed);
$("dangerBtn").addEventListener("click", openDanger);
$("backupsGo").addEventListener("click", backupsGo);
$("redoGo").addEventListener("click", redoGo);
$("rebuildGo").addEventListener("click", rebuildGo);
$("rebuildNo").addEventListener("click", () => $("rebuild").close());
$("d_save").addEventListener("click", saveDefaults);
$("d_offline").addEventListener("change", () => { $("d_download_subs").disabled = $("d_offline").checked; });
$("c_save").addEventListener("click", saveClaude);
$("claudeCheckBtn").addEventListener("click", checkClaude);
$("claudeLoginBtn").addEventListener("click", startClaudeLogin);
$("claudeLoginDone").addEventListener("click", finishClaudeLogin);
$("claudeLoginCode").addEventListener("keydown", (e) => { if (e.key === "Enter") finishClaudeLogin(); });
$("claudeLoginCancel").addEventListener("click", cancelClaudeLogin);
$("claudeLoginCopy").addEventListener("click", copyLoginLink);
$("claudeLogoutBtn").addEventListener("click", claudeLogout);
$("d_api_fallback").addEventListener("change", () => { $("d_api_fallback_usd").disabled = !$("d_api_fallback").checked; });
$("api_fallback").addEventListener("change", showFallback);
$("d_reset").addEventListener("click", resetDefaults);
$("pickFile").addEventListener("click", () => pick("file"));
$("pickFolder").addEventListener("click", () => pick("folder"));
$("browseBtn").addEventListener("click", openBrowser);
$("useFolderBtn").addEventListener("click", () => { $("browser").close(); setPath(browsing); });
$("path").addEventListener("change", () => refresh());
$("path").addEventListener("keydown", (e) => { if (e.key === "Enter") refresh(); });
$("note_background").addEventListener("change", showOpacity);
for (const id of ["recursive", "film_language", "subs_language", "show_subs", "limit", "refine", "redo", "spw",
                  "note_background", "opacity"]) {
  $(id).addEventListener("change", () => refresh());
}
$("runBtn").addEventListener("click", run);
$("cancelBtn").addEventListener("click", cancel);

(async () => {
  if (!(await reloadInfo())) return;
  fillLanguages();
  applySettings();
  showOpacity();
  if (info.running) {
    await refresh();
    $("log").dataset.fresh = "yes";
    startPolling(true);
    return;
  }
  refresh();
})();
