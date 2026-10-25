"use strict";
// One shared namespace. Each file below is a function that runs at once: it takes what it needs from CN and adds
// its own functions to it. Nothing else becomes a global, and no file needs to know which other files exist.
const CN = {};

// Small helpers: finding elements, making elements, remembering things, and wording.
(() => {
  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function el(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) e.append(kid instanceof Node ? kid : String(kid));
    return e;
  }

  // Remembered in the browser between visits (the chosen path and the options). Losing it is fine.
  const store = {
    get(k, d) { try { const v = localStorage.getItem("context-notes." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("context-notes." + k, JSON.stringify(v)); } catch { /* not kept: fine */ } },
  };

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const baseName = (p) => (p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
  const stem = (name) => name.replace(/\.[^.]+$/, "");
  function clock(s) {
    s = Math.max(0, Math.round(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(sec).padStart(2, "0")}`;
  }
  function money(usd) {
    if (usd == null) return null;
    return usd < 0.01 ? "less than a cent" : `about $${usd.toFixed(2)}`;
  }

  Object.assign(CN, { $, sleep, el, store, plural, baseName, stem, clock, money });
})();
