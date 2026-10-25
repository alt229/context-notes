// The screen: the two notes, the title card, the subtitle line, and what they show when nothing is running.
(() => {
  const { $, plural, clock, stem, baseName, TASKS, state } = CN;

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

  function idleScreen() {
    title("Choose a film", "or a folder of episodes. Claude writes the notes, and they play in VLC.");
    hideNote("right");
    if (!state.keepNote) {
      if (CN.blocker(state.info)) note("left", "Before you start", CN.blocker(state.info));
      else note("left", "How it works", "Pick a film below. You choose how the notes are written, see the cost, and then Claude writes them. Nothing is sent until you say so.");
    }
    subline("");
  }
  function readyScreen() {
    const { videos, info } = state;
    const p = $("path").value.trim();
    const one = videos.length === 1;
    const ready = videos.filter((v) => v.state === "ready").length;
    const name = one ? stem(videos[0].name) : baseName(p);
    let sub;
    if (one) sub = videos[0].state === "ready" ? "Ready to watch." : videos[0].state === "stopped" ? "Stopped part-way; it can pick up from there." : "No notes yet.";
    else sub = `${plural(videos.length, "video")}: ${ready} ready, ${videos.length - ready} to do.`;
    title(name, sub);
    hideNote("right");
    if (!state.keepNote) {
      if (CN.blocker(info)) note("left", "Before you start", CN.blocker(info));
      else if (videos.length && ready === videos.length) note("left", "Ready", "Everything here has notes. Open a video in VLC from the list.");
      else note("left", "Next", "Choose how the notes are written, then press Write the notes. You'll see the cost first.");
    }
    subline("");
  }

  Object.assign(CN, { note, hideNote, title, subline, progress, idleScreen, readyScreen });
})();
