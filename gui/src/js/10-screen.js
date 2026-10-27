// ---------------------------------------------------------------- the screen
function note(side, label, text, actions) {
  const box = $(side === "left" ? "noteLeft" : "noteRight");
  box.querySelector(".label").textContent = label;
  box.querySelector(".text").textContent = text;
  const acts = box.querySelector(".acts");
  if (acts) {
    acts.replaceChildren(...(actions || []));
    acts.hidden = !(actions && actions.length);
  }
  if (box.hidden) { box.hidden = false; box.classList.remove("show"); void box.offsetWidth; box.classList.add("show"); }
  return box;
}
function showScreen() {
  // Questions and progress appear on the screen at the top: make sure it's in view (Write the notes is far below).
  const screen = document.querySelector(".screen");
  const top = screen.getBoundingClientRect().top;
  if (top < 0 || top > window.innerHeight * 0.4) {
    const calm = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    screen.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  }
}
function hideNote(side) { $(side === "left" ? "noteLeft" : "noteRight").hidden = true; }
function title(t, sub) { $("title").textContent = t; $("titleSub").textContent = sub || ""; }
function subline(t) { $("subline").textContent = t || ""; }

function progress(ev) {
  const label = TASKS[ev.task] || ev.task;
  let text;
  if (ev.total == null) text = ev.text ? ev.text.charAt(0).toUpperCase() + ev.text.slice(1) : "Working…";
  else if (ev.unit === "requests") text = ev.done < ev.total ? `Request ${ev.done + 1} of ${ev.total}` : `All ${plural(ev.total, "request")} done`;
  else if (ev.unit === "seconds") text = `${clock(ev.done)} of ${clock(ev.total)}`;
  else if (ev.unit === "frames") text = `${ev.total} frames`;
  else text = `${ev.done} of ${ev.total}`;
  const box = note("right", label, text);
  const bar = box.querySelector(".bar");
  bar.classList.toggle("unknown", ev.total == null);
  bar.querySelector("span").style.width = ev.total ? `${Math.min(100, (100 * ev.done) / ev.total)}%` : "";
}

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

