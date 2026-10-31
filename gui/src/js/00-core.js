"use strict";
const KEY = new URLSearchParams(location.search).get("k") || "";
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

const store = {
  get(k, d) { try { const v = localStorage.getItem("context-notes." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("context-notes." + k, JSON.stringify(v)); } catch { /* not kept: fine */ } },
};

async function api(path, body) {
  const opts = body === undefined
    ? { headers: { "X-Key": KEY } }
    : { method: "POST", headers: { "X-Key": KEY, "Content-Type": "application/json" }, body: JSON.stringify(body) };
  try {
    const r = await fetch(path, opts);
    let data = {};
    try { data = await r.json(); } catch { /* not JSON */ }
    if (r.status === 403) data.error = "This page needs the address app.py printed. Open that one.";
    return data;
  } catch {
    return { error: "The app isn't answering. Is the window where you started it still open? Start it again with: python3 app.py", offline: true };
  }
}

const MODELS = { "claude-opus-5-5": "Claude Opus", "claude-sonnet-5-5": "Claude Sonnet" };
const TASKS = { soundtrack: "Listening to the soundtrack", frames: "Pulling frames", transcribe: "Recognising speech",
                generate: "Writing notes", refine: "Looking at the frames", embed: "Putting the notes inside",
                research: "Looking the film up" };
const STATES = { ready: "Ready", todo: "To do", rebuild: "Needs a rebuild", stopped: "Stopped part-way",
                 working: "Working on it", problem: "Stopped" };
const STEPS = ["subtitles", "sync", "research", "generate", "refine", "alignment", "done"];
const BTS = "behind-the-scenes";              // the Behind the Scenes track (workfiles.BTS)

let info = null;
let videos = [];
let job = { next: 0 };
let lastEstimate = null;
let polling = false;
let running = false;
let asking = false;
let embedding = false;          // the job running is embed.py, not a run
let keepNote = false;
let usageNow = null;             // what usage.py reports: the credit estimate, spending, and the plan's session

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const baseName = (p) => (p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
const stem = (name) => name.replace(/\.[^.]+$/, "");
function clock(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(sec).padStart(2, "0")}`;
}
const dollars = (usd) => (usd > 0 && usd < 0.005 ? "<$0.01" : `$${usd.toFixed(2)}`);   // same as usage.money
function money(usd) {
  if (usd == null) return null;
  return usd < 0.01 ? "less than a cent" : `about $${usd.toFixed(2)}`;
}

