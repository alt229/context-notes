#!/usr/bin/env python3
"""bench.py - compare Claude models and effort settings on the context-notes pipeline.

Runs the same video through generate + refine once per (model, effort) "cell", each in its own folder,
and records tokens, cost, time and note statistics. Every API response is cached on disk, so the run can be
stopped and repeated at any point without paying for a request twice (and a crash loses nothing).

    python3 bench/bench.py run VIDEO --subs MAIN.srt --film-language jp --limit 45:00 \\
        --models claude-sonnet-5-5 claude-opus-5-5 --efforts low high --out bench-out
    python3 bench/bench.py status --out bench-out
    python3 bench/report.py --out bench-out          # tables, bars, CSV
    python3 bench/judge.py  --out bench-out          # optional blind quality judge

`--budget SECONDS` stops starting new API calls after that long and exits with code 3 ("run me again").
Use it where a single command can only live for a few minutes; leave it off (0) for one uninterrupted run.
Your normal notes files are never touched: everything lands under --out.
"""
import argparse
import contextlib
import hashlib
import io
import json
import pickle
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

SHORT = {"claude-haiku-4-5-20251001": "haiku", "claude-sonnet-5-5": "sonnet",
         "claude-opus-5-5": "opus", "claude-fable-5-1": "fable"}
MIN_REMAINING = 100          # default: don't START an API call with less than this many seconds of budget left


class Budget(Exception):
    """Out of time for this invocation; the finished API calls are cached, so run again."""


def short(model):
    return SHORT.get(model, re.sub(r"^claude-", "", model))


def supports_effort(model):
    return "haiku" not in model            # Haiku 4.5 answers HTTP 400 to output_config.effort


def cell_name(model, effort, tag="", refine=None):
    """refine = (model, effort) when the refine step uses a different model than generate (a 'hybrid' cell)."""
    base = f"{short(model)}__{effort or 'default'}"
    if refine:
        base += f"+{short(refine[0])}__{refine[1] or 'default'}"
    return base + (f"__{tag}" if tag else "")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def real_notes(spec):
    return [n for n in spec.get("notes", []) if n.get("category") != "About these notes"]


# ------------------------------------------------------------------ one cell (runs in its own process)
def unit(cell_dir, budget, min_remaining=MIN_REMAINING):
    cell_dir = Path(cell_dir)
    cfg = load(cell_dir / "cell.json")
    import analyze
    import claude_api
    import generate_notes as gn
    import refine_notes as rn

    deadline = time.time() + budget if budget else None
    cache = cell_dir / "api-cache"
    cache.mkdir(exist_ok=True)
    tally = {"secs": 0.0, "calls": 0}
    real = claude_api.call_api

    def cached(key, model, system, user, url=claude_api.API_URL, timeout=300, max_tokens=claude_api.MAX_TOKENS, effort=None):
        h = hashlib.sha256(json.dumps([model, system, user, max_tokens, effort], sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()[:24]
        f = cache / f"{h}.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
        else:
            if deadline and time.time() + min_remaining > deadline:
                raise Budget()
            t = time.time()
            r = real(key, model, system, user, url, timeout, max_tokens, effort)
            r["_secs"] = round(time.time() - t, 2)
            f.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        tally["secs"] += r.get("_secs", 0)
        tally["calls"] += 1
        return r

    claude_api.call_api = cached
    pkl = Path(cfg["prep_pkl"])

    def fake_analyze(cues, video, frames_mode="keyframes", fallback_offset=0.0, say=print, limit=None):
        say("  (using the video analysis computed once for the whole benchmark)")
        return pickle.loads(pkl.read_bytes())

    analyze.analyze_video = fake_analyze
    rn.unique_backup = lambda p: Path(str(p) + ".pre-refine")      # replays must not litter backups

    notes = cell_dir / "notes.json"
    gen_done = cell_dir / "notes.generated.json"

    def step(name, fn, model=None):
        tally.update(secs=0.0, calls=0)
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fn()
        except Budget:
            return "incomplete", None
        except SystemExit as e:
            cfg["status"] = "error"
            cfg["error"] = f"{name}: {e.code}"
            cfg["error_tail"] = buf.getvalue()[-600:]
            save(cell_dir / "cell.json", cfg)
            return "error", None
        out = buf.getvalue()
        (cell_dir / f"{name}.log").write_text(out, encoding="utf-8")
        u = re.search(r"Used ([\d,]+) input and ([\d,]+) output tokens", out)
        tin, tout = (int(u.group(1).replace(",", "")), int(u.group(2).replace(",", ""))) if u else (0, 0)
        problems = [ln.strip()[2:] for ln in out.splitlines() if ln.startswith("  ! ")]
        m = {"in": tin, "out": tout, "cost": claude_api.cost(model or cfg["model"], tin, tout),
             "api_seconds": round(tally["secs"], 1), "calls": tally["calls"], "problems": problems,
             "truncated": sum("cut off" in p for p in problems)}
        return "ok", (m, out)

    src = cfg.get("generate_from")
    if src and "generate" in cfg["steps"] and not cfg.get("generate"):
        # hybrid cell: its generate step is, by construction, another cell's generate step. Reuse that output
        # (waiting for it if it is still running) so the API call is neither repeated nor paid for twice.
        sdir = cell_dir.parent / src
        while True:
            scfg = load(sdir / "cell.json") if (sdir / "cell.json").exists() else {}
            if scfg.get("generate") and (sdir / "notes.generated.json").exists():
                break
            if scfg.get("status") == "error":
                cfg["status"], cfg["error"] = "error", f"generate source {src} failed"
                save(cell_dir / "cell.json", cfg)
                return "error"
            if deadline and time.time() + 20 > deadline:
                return "incomplete"
            time.sleep(3)
        shutil.copyfile(sdir / "notes.generated.json", notes)
        shutil.copyfile(sdir / "notes.generated.json", gen_done)
        cfg["generate"] = dict(scfg["generate"], shared_from=src)
        save(cell_dir / "cell.json", cfg)

    if "generate" in cfg["steps"] and not cfg.get("generate"):
        kw = dict(model=cfg["model"], title=cfg["title"], assume_yes=True, key_file=cfg["key_file"],
                  film_language=cfg["film_language"], limit=cfg["limit"], max_tokens=cfg["max_tokens"]["generate"])
        if cfg["effort"]:
            kw["effort"] = cfg["effort"]
        state, res = step("generate", lambda: gn.generate(cfg["subs"], notes, **kw), cfg["model"])
        if state != "ok":
            return state
        m, _ = res
        spec = load(notes)
        m["notes"] = len(real_notes(spec))
        cfg["generate"] = m
        gen_done.write_text(notes.read_text(encoding="utf-8"), encoding="utf-8")
        save(cell_dir / "cell.json", cfg)

    if "refine" in cfg["steps"] and not cfg.get("refine"):
        rmodel = cfg.get("refine_model") or cfg["model"]
        reffort = cfg.get("refine_effort") if cfg.get("refine_model") else cfg["effort"]
        kw = dict(model=rmodel, frames="keyframes", title=cfg["title"], assume_yes=True, key_file=cfg["key_file"],
                  assume_synced=True, film_language=cfg["film_language"], limit=cfg["limit"],
                  max_tokens=cfg["max_tokens"]["refine"])
        if reffort:
            kw["effort"] = reffort
        before = len(real_notes(load(notes)))
        state, res = step("refine", lambda: rn.refine(cfg["subs"], notes, cfg["video"], **kw), rmodel)
        if state != "ok":
            return state
        m, out = res
        r = re.search(r"^Refined .*?: (\d+) added, (\d+) revised, (\d+) retimed, (\d+) dropped", out, re.M)
        if r:
            m.update(added=int(r.group(1)), revised=int(r.group(2)), retimed=int(r.group(3)), dropped=int(r.group(4)))
        m["notes_before"] = before
        m["notes"] = len(real_notes(load(notes)))
        cfg["refine"] = m
        save(cell_dir / "cell.json", cfg)

    cfg["status"] = "done"
    save(cell_dir / "cell.json", cfg)
    return "done"


def progress(cell_dir):
    cfg = load(Path(cell_dir) / "cell.json")
    n = len(list((Path(cell_dir) / "api-cache").glob("*.json"))) if (Path(cell_dir) / "api-cache").exists() else 0
    gen = cfg.get("generate")
    state = cfg["status"]
    if state != "done" and state != "error":
        state = "refining" if gen else "generating"
        if not cfg.get("generate") and n == 0:
            state = "pending"
    return cfg, state, n


# ------------------------------------------------------------------ video analysis, rebuilt from an existing run
def prep_reuse(analysis_dir, video, subs, limit, tail_dir):
    """What analyze.analyze_video(..., limit=limit) would return, rebuilt from the frames, contact sheets and
    soundtrack an earlier full run already left in `analysis_dir` (so nothing is decoded again and every cell
    sees exactly the frames the real pipeline saw). Keyframe times come from the file's packet flags; the
    resulting sheet names are checked against the ones on disk."""
    import analyze
    import numpy as np

    import subtitles
    import timecode
    analysis_dir, tail_dir = Path(analysis_dir), Path(tail_dir)
    cues = subtitles.limit_cues(subtitles.parse_srt(subs), limit)
    db = np.load(analysis_dir / "soundtrack.npy")[: int(round(limit * analyze.FPS_A))]
    sync = analyze.sync_check(db, cues, limit)
    constant = sync["offset"] is not None and "--align" not in sync["verdict"]
    measured = (0.0 if abs(sync["offset"]) < 0.25 else sync["offset"]) if constant else None
    offset = measured if measured is not None else 0.0
    moments = analyze.loud_moments(db, cues, offset)
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", f"%+{int(limit) + 60}",
                        "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True)
    keys = sorted(float(a) for a, _, b in (ln.partition(",") for ln in r.stdout.splitlines())
                  if a not in ("", "N/A") and "K" in b)
    picked, last = [], -1e9
    for t in (t for t in keys if t < limit):
        if t - last >= 1.5:
            picked.append(t)
            last = t
    sheets = []
    for i, k in enumerate(range(0, len(picked), 12)):
        chunk = picked[k:k + 12]
        name = analysis_dir / "sheets" / f"sheet_{i + 1:03d}_{timecode.hms(chunk[0]).replace(':', '.')}.jpg"
        if len(chunk) == 12 and name.exists():
            sheets.append((name, chunk[0], chunk[-1]))
        else:       # the last, shorter sheet: rebuild it from the stored frames so it stops at the limit
            frames = [(t, analysis_dir / "frames" / f"{keys.index(t) + 1:06d}.jpg") for t in chunk]
            assert all(f.exists() for _, f in frames), "stored frames don't line up with the keyframe times"
            made = analyze.contact_sheets(frames, cues, offset, tail_dir)
            sheets.extend(made)
    return {"duration": float(limit), "sync": sync, "offset_measured": measured, "offset": offset,
            "moments": moments, "sheets": sheets}


# ------------------------------------------------------------------ orchestration
def cmd_run(a):
    import subtitles
    import timecode
    out = Path(a.out).resolve()
    (out / "runs").mkdir(parents=True, exist_ok=True)
    video = Path(a.video).resolve()
    subs = Path(a.subs).resolve()
    limit = timecode.duration_arg(a.limit)
    started = time.time()

    prep = out / "_prep"
    prep.mkdir(exist_ok=True)
    link = prep / video.name
    if not link.exists():
        link.symlink_to(video)          # so the analysis folder is created here, not beside your real video
    pkl = prep / f"analysis-{int(limit)}s.pkl"
    if not pkl.exists():
        import analyze
        print(f"Preparing the video analysis for the first {timecode.fmt_limit(limit)} (once; all cells share it)...",
              flush=True)
        if a.reuse_analysis:
            an = prep_reuse(a.reuse_analysis, video, subs, limit, prep / "sheets-tail")
        else:
            cues = subtitles.parse_srt(subs)
            an = analyze.analyze_video(cues, link, "keyframes", fallback_offset=0.0, limit=limit)
        pkl.write_bytes(pickle.dumps(an))
        print(f"  done in {time.time() - started:.0f} s: {len(an['sheets'])} contact sheets", flush=True)

    wanted = []
    for m in a.models:
        for e in (a.efforts if supports_effort(m) else ["default"]):
            wanted.append((m, None if e == "default" else e, "", None))
    for spec in a.cell or []:
        # MODEL:EFFORT[:TAG]    or, for a different model in each step,    GENMODEL:GENEFFORT+REFMODEL:REFEFFORT[:TAG]
        left, plus, right = spec.partition("+")
        parts = left.split(":")
        refine = None
        tag = parts[2] if len(parts) > 2 else ""
        if plus:
            rp = right.split(":")
            refine = (rp[0], None if rp[1] == "default" else rp[1])
            tag = rp[2] if len(rp) > 2 else ""
        wanted.append((parts[0], None if parts[1] == "default" else parts[1], tag, refine))
    for model, effort, tag, refine in wanted:
        d = out / "runs" / cell_name(model, effort, tag, refine)
        plain = cell_name(model, effort)
        gen_from = plain if refine and ((out / "runs" / plain).exists() or
                                        any(cell_name(m2, e2, t2, r2) == plain for m2, e2, t2, r2 in wanted)) else None
        if not (d / "cell.json").exists():
            d.mkdir(parents=True, exist_ok=True)
            save(d / "cell.json", {
                "model": model, "effort": effort, "tag": tag, "status": "pending", "steps": a.steps,
                **({"refine_model": refine[0], "refine_effort": refine[1], "generate_from": gen_from} if refine else {}),
                "video": str(link), "subs": str(subs), "film_language": a.film_language, "limit": limit,
                "title": a.title, "key_file": str(Path(a.api_key_file).expanduser()) if a.api_key_file else None,
                "prep_pkl": str(pkl), "generate": None, "refine": None,
                "max_tokens": {"generate": a.max_tokens_generate, "refine": a.max_tokens_refine}})
    dirs = sorted(d for d in (out / "runs").iterdir() if (d / "cell.json").exists())
    todo = [d for d in dirs if load(d / "cell.json")["status"] not in ("done", "error")]
    if a.retry_errors:
        todo += [d for d in dirs if load(d / "cell.json")["status"] == "error"]
        for d in dirs:
            c = load(d / "cell.json")
            if c["status"] == "error":
                c["status"] = "pending"
                c.pop("error", None)
                save(d / "cell.json", c)

    running = []
    queue = list(todo)
    while queue or running:
        while queue and len(running) < a.parallel:
            d = queue.pop(0)
            left = max(a.budget - (time.time() - started), 1) if a.budget else 0
            p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_unit", str(d), "--budget", f"{left:.0f}",
                                  "--min-remaining", str(a.min_remaining)],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            running.append((d, p))
        time.sleep(1)
        for item in list(running):
            d, p = item
            if p.poll() is not None:
                text = p.stdout.read()
                if p.returncode not in (0, 3) and text.strip():
                    print(f"[{d.name}] crashed:\n{text[-800:]}", flush=True)
                running.remove(item)
    status(out)
    unfinished = [d for d in dirs if load(d / "cell.json")["status"] not in ("done", "error")]
    return 3 if unfinished else 0


def status(out):
    out = Path(out)
    rows = []
    for d in sorted((out / "runs").iterdir()):
        if not (d / "cell.json").exists():
            continue
        cfg, state, n = progress(d)
        g, r = cfg.get("generate") or {}, cfg.get("refine") or {}
        cost = (g.get("cost") or 0) + (r.get("cost") or 0)
        rows.append((d.name, state, n, g.get("notes", "-"), r.get("notes", "-"), f"${cost:.2f}" if g or r else "-",
                     cfg.get("error", "")))
    w = max([len(x[0]) for x in rows] + [4])
    print(f"{'cell':{w}}  {'state':10} {'cached calls':>12} {'gen notes':>9} {'final':>6} {'cost':>7}")
    for name, state, n, gn_, fn_, cost, err in rows:
        print(f"{name:{w}}  {state:10} {n:>12} {gn_!s:>9} {fn_!s:>6} {cost:>7}  {err}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run (or resume) the benchmark")
    r.add_argument("video")
    r.add_argument("--subs", required=True, help="the subtitle file the notes are written from")
    r.add_argument("--film-language")
    r.add_argument("--limit", default="45:00")
    r.add_argument("--models", nargs="*", default=[])
    r.add_argument("--efforts", nargs="*", default=["low", "high"])
    r.add_argument("--cell", nargs="*", metavar="MODEL:EFFORT[:TAG]",
                   help="extra single cells, e.g. claude-sonnet-5-5:low:rep2 (EFFORT may be 'default'); a different model "
                        "for each step: claude-sonnet-5-5:high+claude-opus-5-5:medium (generate+refine; reuses the "
                        "plain claude-sonnet-5-5:high cell's generate output when that cell is in the run)")
    r.add_argument("--out", required=True)
    r.add_argument("--title", default="Benchmark")
    r.add_argument("--steps", nargs="*", default=["generate", "refine"], choices=["generate", "refine"])
    r.add_argument("--parallel", type=int, default=4)
    r.add_argument("--budget", type=int, default=0, help="seconds; 0 = unlimited (see the top of this file)")
    r.add_argument("--max-tokens-generate", type=int, default=16000)
    r.add_argument("--max-tokens-refine", type=int, default=12000)
    r.add_argument("--api-key-file")
    r.add_argument("--retry-errors", action="store_true")
    r.add_argument("--reuse-analysis", metavar="DIR",
                   help="an existing '<video> analysis' folder from a full run: reuse its frames, sheets and soundtrack")
    r.add_argument("--min-remaining", type=int, default=MIN_REMAINING,
                   help="with --budget: don't start an API call with less than this many seconds left")
    s = sub.add_parser("status")
    s.add_argument("--out", required=True)
    u = sub.add_parser("_unit")
    u.add_argument("cell_dir")
    u.add_argument("--budget", type=float, default=0)
    u.add_argument("--min-remaining", type=float, default=MIN_REMAINING)
    a = ap.parse_args()
    if a.cmd == "run":
        sys.exit(cmd_run(a))
    if a.cmd == "status":
        status(a.out)
        return
    res = unit(a.cell_dir, a.budget, a.min_remaining)
    print(res)
    sys.exit(3 if res == "incomplete" else 0)


if __name__ == "__main__":
    main()
