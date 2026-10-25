// The Details log: every line the run prints.
(() => {
  const { $ } = CN;

  function log(line) {
    const pre = $("log");
    if (pre.dataset.fresh !== "no") { pre.textContent = ""; pre.dataset.fresh = "no"; }
    pre.append(line + "\n");
    pre.scrollTop = pre.scrollHeight;
  }

  CN.log = log;
})();
