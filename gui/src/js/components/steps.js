// The numbered steps of a run.
(() => {
  const { $, STEPS } = CN;

  function resetSteps(alignment) {
    const ol = $("steps");
    ol.hidden = false;
    for (const li of ol.children) {
      li.className = "";
      li.hidden = li.dataset.step === "alignment" && !alignment;
    }
  }
  function step(name) {
    if (name === "build") name = "done";
    const at = STEPS.indexOf(name);
    if (at < 0) return;
    for (const li of $("steps").children) {
      const i = STEPS.indexOf(li.dataset.step);
      if (li.dataset.step === "alignment" && name === "alignment") li.hidden = false;
      if (i < at) li.className = li.classList.contains("active") || li.classList.contains("done") ? "done" : "skipped";
      else if (i === at) li.className = name === "done" ? "done" : "active";
    }
  }

  Object.assign(CN, { resetSteps, step });
})();
