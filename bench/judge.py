#!/usr/bin/env python3
"""judge.py - blind quality judge for a bench.py run.

For each stretch of the film, the notes from EVERY cell are pooled, anonymised and shuffled, and one judge model
rates each note's accuracy and usefulness and groups notes that make the same point. Dialogue notes are judged against
the English subtitles; visual notes are judged against the actual contact sheets (video frames). Results go to
<out>/judge-results.json; bench/report.py turns them into tables.

    python3 bench/judge.py --out bench-out --english-subs film.en.aligned.srt --api-key-file ~/.config/context-notes/api-key
        [--judge-model claude-opus-5-5] [--judge-effort high] [--budget 165]   # re-run until it says "complete"

Caveats worth keeping in mind: the judge is itself a Claude model (notes are anonymised, but a judge can still favour
a familiar style), it sees frames at contact-sheet resolution only, and its knowledge of the film is not ground truth.
Treat differences of a few points as noise, and spot-check anything surprising.
"""
import argparse
import base64
import concurrent.futures as cf
import hashlib
import json
import pickle
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
import claude_api  # noqa: E402
import refine_notes as rn  # noqa: E402
import subtitles  # noqa: E402

COMMON = """You are an impartial judge of "pop-up context notes" written for viewers of the 1988 anime film Akira. The \
viewer is an English speaker watching the Japanese original with subtitles. Good notes explain what a non-native viewer \
would miss and are accurate.

You will see material for one stretch of the film and a pooled, shuffled list of candidate notes written by several \
different writers (anonymised; do not try to guess who wrote what). Judge every note on its own merits, using your own \
knowledge of the film, the manga and Japan.

For every note give:
- "acc": {acc_defs}
- "use": 1 = trivial, or obvious without the note; 2 = a helpful bit of context; 3 = genuinely illuminating (explains \
something this viewer would really miss, or adds real meaning).
- "cluster": a short id such as "c3"; notes that make essentially the same point share one id.
- "issue": one short phrase, ONLY when acc is not "accurate".
Then list up to 5 "missing" items: important points for this stretch that NO note covers.

Reply with JSON only, no commentary: {{"notes":[{{"id":"n1","acc":"accurate","use":2,"cluster":"c1","issue":""}}],\
"missing":[{{"t":"m:ss","point":"..."}}]}}. Include every note id exactly once."""

ACC_SPEECH = ('"accurate" (every claim is true and fits the dialogue), "minor" (mostly right, with a small slip, '
              'overreach or shaky detail), "wrong" (a significant claim is false, invented, or contradicts the film), '
              'or "unverifiable" (a specific claim you cannot confirm either way)')
ACC_VISUAL = ('"accurate" (what the note describes is visible in these frames, or is a well-established fact about the '
              'film), "minor" (broadly right but a detail is off or overstated), "wrong" (contradicted by the frames '
              'or the film), or "unverifiable" (not visible at this resolution and you cannot confirm it)')
SYSTEM_SPEECH = COMMON.format(acc_defs=ACC_SPEECH) + (
    "\n\nThe material is the English subtitles for the stretch, plus the second subtitle track the writers actually "
    "worked from. Note: that second track may be in a DIFFERENT language from the film's Japanese dialogue (for example "
    "a Korean translation). Add one more field to every note, \"ko\": true if the note is mainly about wording that "
    "exists only in that second track (a Korean word, idiom or phrasing, rather than the film's Japanese dialogue, "
    "plot or culture), otherwise false. Judge \"acc\" on whether the note's claims are true; judge \"use\" for an English "
    "speaker watching the Japanese original with English subtitles, so a note that only explains the second "
    "language's wording is use 1.")
SYSTEM_SPEECH_ORIGINAL = COMMON.format(acc_defs=ACC_SPEECH) + (
    "\n\nThe material is the English subtitles for the stretch, plus the Japanese subtitle track the writers actually "
    "worked from: the film's original dialogue (it may include speaker labels and sound-effect cues in parentheses). "
    "Judge \"acc\" on whether the note's claims are true and fit the dialogue; judge \"use\" for an English speaker "
    "watching the Japanese original with English subtitles.")
SYSTEM_SPEECH_SINGLE = COMMON.format(acc_defs=ACC_SPEECH) + (
    "\n\nThe material is the English subtitles for the stretch, which are also the dialogue the writers worked from "
    "(they may include speaker labels and sound-effect cues in parentheses). Judge \"acc\" on whether the note's claims "
    "are true and fit the dialogue and the film; judge \"use\" for the viewer described above.")
SYSTEM_VISUAL = COMMON.format(acc_defs=ACC_VISUAL) + (
    "\n\nThe material is contact sheets (grids of frames, each labelled with its timestamp and the subtitle shown) "
    "plus the English subtitles. The notes describe or explain what is ON SCREEN: text, props, staging, sight gags, "
    "background details, visual motifs.")


def adapt(system, a):
    """The prompts are written for Akira; swap in another film with --film-desc / --language / --knowledge
    (the defaults leave the text, and so the judge cache keys, exactly as they were)."""
    if getattr(a, "viewer", None):
        system = system.replace("an English speaker watching the Japanese original with subtitles", a.viewer)
    return (system.replace("the 1988 anime film Akira", a.film_desc)
            .replace("Japanese original", f"{a.language} original")
            .replace("the Japanese subtitle track", f"the {a.language} subtitle track")
            .replace("the film, the manga and Japan", a.knowledge))


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def mss(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def gather(out):
    cells = {}
    for d in sorted((out / "runs").iterdir()):
        if not (d / "cell.json").exists():
            continue
        cfg, spec = load(d / "cell.json"), load(d / "notes.json")
        cues = subtitles.parse_srt(cfg["subs"])
        times = rn.note_times(cues, spec["notes"], float(spec.get("video_offset", 0) or 0))
        items = []
        for k, n in enumerate(spec["notes"], 1):
            if n.get("category") == "About these notes" or times.get(k) is None:
                continue
            items.append({"cell": d.name, "t": times[k], "kind": n.get("kind", "speech"),
                          "category": n.get("category", ""), "text": n["text"]})
        cells[d.name] = items
    return cells, cfg


def build_windows(cells, cfg, out, english, span, korean=None):
    limit = float(cfg["limit"])
    eng = subtitles.parse_srt(english)
    kor = subtitles.parse_srt(korean or cfg["subs"])
    sheets = pickle.loads(Path(cfg["prep_pkl"]).read_bytes())["sheets"]
    wins = []
    for i, lo in enumerate(range(0, int(limit), span)):
        wins.append({"kind": "speech", "lo": float(lo), "hi": min(float(lo + span), limit), "sheets": []})
    for i in range(0, len(sheets), 2):
        pair = sheets[i:i + 2]
        hi = sheets[i + 2][1] if i + 2 < len(sheets) else limit
        wins.append({"kind": "visual", "lo": pair[0][1], "hi": float(hi), "sheets": pair})
    for w_i, w in enumerate(wins):
        pool = [n for items in cells.values() for n in items if n["kind"] == w["kind"] and w["lo"] <= n["t"] < w["hi"]]
        random.Random(f"{w['kind']}-{w_i}").shuffle(pool)
        w["notes"] = [dict(n, id=f"n{j}") for j, n in enumerate(pool, 1)]
        w["subs"] = [c for c in eng if w["lo"] - 15 <= c["start"] < w["hi"] + 5]
        w["subs2"] = [c for c in kor if w["lo"] - 15 <= c["start"] < w["hi"] + 5]
        w["key"] = f"{w['kind']}-{int(w['lo'])}"
    return [w for w in wins if w["notes"]]


def user_content(w):
    subs = "\n".join(f"[{mss(c['start'])}] {' / '.join(c['text'].split(chr(10)))}" for c in w["subs"]) or "(no dialogue)"
    notes = "\n".join(f"{n['id']} [{mss(n['t'])}] ({n['category']}) {n['text']}" for n in w["notes"])
    second = ""
    if w["kind"] == "speech" and not w.get("single"):
        second = "\n\nSecond subtitle track (what the writers saw):\n" + "\n".join(
            f"[{mss(c['start'])}] {' / '.join(c['text'].split(chr(10)))}" for c in w["subs2"])
    text = (f"Stretch: {mss(w['lo'])} to {mss(w['hi'])}\n\nEnglish subtitles:\n{subs}{second}\n\n"
            f"Candidate notes:\n{notes}")
    if not w["sheets"]:
        return text
    blocks = []
    for path, t0, t1 in w["sheets"]:
        blocks.append({"type": "text", "text": f"Contact sheet: frames from {mss(t0)} to {mss(t1)}"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(Path(path).read_bytes()).decode()}})
    blocks.append({"type": "text", "text": text})
    return blocks


def parse_judgement(text):
    a, b = text.find("{"), text.rfind("}")
    try:
        d = json.loads(text[a:b + 1])
        return d if isinstance(d.get("notes"), list) else None
    except (ValueError, AttributeError):
        return None


def run_judge(a):
    out = Path(a.out).resolve()
    cells, cfg = gather(out)
    wins = build_windows(cells, cfg, out, a.english_subs, a.span, a.korean_subs)
    for w in wins:
        w["single"] = bool(a.single_track)
    cache = out / "judge-cache"
    cache.mkdir(exist_ok=True)
    key = claude_api.load_key(a.api_key_file)
    started = time.time()
    deadline = started + a.budget if a.budget else None

    def one(w):
        system = adapt(SYSTEM_VISUAL if w["kind"] == "visual" else (
            SYSTEM_SPEECH_SINGLE if a.single_track else
            SYSTEM_SPEECH_ORIGINAL if a.original_second_track else SYSTEM_SPEECH), a)
        content = user_content(w)
        h = hashlib.sha256(json.dumps([a.judge_model, a.judge_effort, system, content], sort_keys=True).encode()).hexdigest()[:24]
        f = cache / f"{w['key']}-{h}.json"
        if f.exists():
            return w["key"], json.loads(f.read_text(encoding="utf-8")), None
        if deadline and time.time() + a.min_remaining > deadline:
            return w["key"], None, "deferred"
        try:
            r = claude_api.call_api(key, a.judge_model, system, content, timeout=600, max_tokens=a.max_tokens,
                            effort=a.judge_effort)
        except BaseException as e:           # call_api exits the process on a hard API error
            return w["key"], None, f"error: {e}"
        text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        j = parse_judgement(text)
        res = {"judgement": j, "usage": r.get("usage", {}), "stop": r.get("stop_reason"), "raw": None if j else text}
        f.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        return w["key"], res, None

    results, pending, errors = {}, 0, []
    with cf.ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for k, res, err in ex.map(one, wins):
            if err == "deferred":
                pending += 1
            elif err:
                errors.append((k, err))
            else:
                results[k] = res
    for k, e in errors:
        print(f"  {k}: {e}")
    if pending or errors:
        print(f"{len(results)}/{len(wins)} windows judged; {pending} deferred. Run again to continue.")
        return 3
    # ---- score
    per = {c: {"speech": [], "visual": []} for c in cells}
    clusters = {}                                        # (window key, cluster) -> {cell: best (acc, use)}
    tin = tout = 0
    bad = []
    for w in wins:
        res = results[w["key"]]
        tin += res["usage"].get("input_tokens", 0)
        tout += res["usage"].get("output_tokens", 0)
        j = res["judgement"]
        if not j:
            bad.append(w["key"])
            continue
        by_id = {n["id"]: n for n in w["notes"]}
        for r in j["notes"]:
            n = by_id.get(r.get("id"))
            if not n:
                continue
            item = {"acc": r.get("acc"), "use": int(r.get("use") or 0), "issue": r.get("issue", ""), "t": n["t"],
                    "text": n["text"], "window": w["key"], "cluster": r.get("cluster"), "ko": bool(r.get("ko")),
                    "category": n.get("category", ""), "kind": w["kind"]}
            per[n["cell"]][w["kind"]].append(item)
            if item["acc"] in ("accurate", "minor") and item["use"] >= 2 and not item["ko"]:
                key = (w["key"], r.get("cluster"))
                clusters.setdefault(key, {}).setdefault(n["cell"], 0)
                clusters[key][n["cell"]] = max(item["use"], clusters[key][n["cell"]])
    summary = {}
    for c, kinds in per.items():
        s = {}
        for kind in ("speech", "visual", "all"):
            items = kinds["speech"] + kinds["visual"] if kind == "all" else kinds[kind]
            n = len(items) or 1
            cnt = lambda lab: sum(i["acc"] == lab for i in items)          # noqa: E731
            valuable = [i for i in items if i["acc"] in ("accurate", "minor") and i["use"] >= 2 and not i["ko"]]
            s[kind] = {"notes": len(items), "accurate": cnt("accurate"), "minor": cnt("minor"), "wrong": cnt("wrong"),
                       "unverifiable": cnt("unverifiable"), "use_mean": round(sum(i["use"] for i in items) / n, 2),
                       "use3": sum(i["use"] == 3 for i in items), "valuable": len(valuable),
                       "ko": sum(i["ko"] for i in items),
                       "wrong_not_ko": sum(i["acc"] == "wrong" and not i["ko"] for i in items)}
        for kind in ("speech", "visual", "all"):
            tot = [k for k in clusters if kind == "all" or k[0].startswith(kind)]
            s[kind]["clusters_covered"] = sum(1 for k in tot if c in clusters[k])
            s[kind]["clusters_total"] = len(tot)
        summary[c] = s
    save = {"judge_model": a.judge_model, "judge_effort": a.judge_effort, "windows": len(wins), "bad_windows": bad,
            "tokens_in": tin, "tokens_out": tout, "judge_cost": claude_api.cost(a.judge_model, tin, tout),
            "summary": summary,
            "notes": {c: v["speech"] + v["visual"] for c, v in per.items()},
            "wrong_notes": {c: [dict(i, kind=k) for k in ("speech", "visual") for i in v[k] if i["acc"] == "wrong"]
                            for c, v in per.items()},
            "missing": {w["key"]: results[w["key"]]["judgement"].get("missing", []) for w in wins
                        if results[w["key"]]["judgement"]}}
    (out / "judge-results.json").write_text(json.dumps(save, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"complete: {len(wins)} windows judged ({len(bad)} unreadable), judge cost about "
          f"${save['judge_cost']:.2f}. Wrote judge-results.json")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--english-subs", required=True, help="English subtitles timed to the video (for the judge)")
    ap.add_argument("--korean-subs", help="the subtitle file the writers worked from (default: the one in the run)")
    ap.add_argument("--original-second-track", action="store_true",
                    help="the writers' subtitles are the film's own language (e.g. real Japanese subs), so there is "
                         "no 'ko' flag to judge; use this instead of the default Korean-translation wording")
    ap.add_argument("--single-track", action="store_true",
                    help="the film is in English and the writers worked from the same English subtitles the judge "
                         "reads, so there is no second track")
    ap.add_argument("--viewer", help='who the notes are for, e.g. "a fluent English speaker who didn\'t grow up in the UK" '
                                     "(default: an English speaker watching the Japanese original with subtitles)")
    ap.add_argument("--film-desc", default="the 1988 anime film Akira",
                    help='what the judge is told the film is, e.g. "the 2001 French film Amélie"')
    ap.add_argument("--language", default="Japanese", help="the film's spoken language, in English")
    ap.add_argument("--knowledge", default="the film, the manga and Japan",
                    help='what the judge should draw on, e.g. "the film, French culture and Paris"')
    ap.add_argument("--api-key-file")
    ap.add_argument("--judge-model", default="claude-opus-5-5")
    ap.add_argument("--judge-effort", default="high")
    ap.add_argument("--span", type=int, default=240, help="seconds per dialogue window")
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--budget", type=int, default=0)
    ap.add_argument("--min-remaining", type=int, default=100)
    sys.exit(run_judge(ap.parse_args()))


if __name__ == "__main__":
    main()
