#!/usr/bin/env python3
"""report.py - tables, ASCII charts and CSV for a bench.py run (adds quality columns if judge.py has been run).

    python3 bench/report.py --out bench-out [--max-wrong-pct 10]

Writes <out>/report.md, results.csv and results.json and prints the report.
"valuable" = a note the judge rated accurate or minor AND useful (use >= 2), excluding notes that only explain the
subtitle file's wrong-language wording. The frontier lists cells nobody beats on both cost and valuable notes, among
cells whose wrong-note rate is at most --max-wrong-pct.
"""
import argparse
import csv
import json
from pathlib import Path

ORDER = {"low": 0, "medium": 1, "default": 1, "high": 2, "xhigh": 3, "max": 4}
MODEL_ORDER = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def mmss(s):
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


def bar(v, vmax, width=34):
    n = int(round(width * v / vmax)) if vmax else 0
    return "#" * n


def collect(out):
    out = Path(out)
    judge = load(out / "judge-results.json") if (out / "judge-results.json").exists() else None
    rows = []
    for d in sorted((out / "runs").iterdir()):
        if not (d / "cell.json").exists():
            continue
        c = load(d / "cell.json")
        g, r = c.get("generate") or {}, c.get("refine") or {}
        if c["status"] != "done":
            continue
        model, effort = d.name.split("__")[0], c["effort"] or "default"
        if c.get("refine_model"):       # hybrid: generate model+effort, then refine model+effort
            model += "+" + c["refine_model"].replace("claude-", "").split("-")[0]
            effort += "/" + (c.get("refine_effort") or "default")
        row = {"cell": d.name, "model": model, "effort": effort,
               "tag": c.get("tag", ""), "gen_notes": g.get("notes"), "final_notes": r.get("notes", g.get("notes")),
               "refine_added": r.get("added"), "tokens_in": g.get("in", 0) + r.get("in", 0),
               "tokens_out": g.get("out", 0) + r.get("out", 0),
               "cost": (g.get("cost") or 0) + (r.get("cost") or 0),
               "api_seconds": g.get("api_seconds", 0) + r.get("api_seconds", 0),
               "truncated": g.get("truncated", 0) + r.get("truncated", 0)}
        if judge and d.name in judge["summary"]:
            a = judge["summary"][d.name]["all"]
            n = max(a["notes"], 1)
            row.update(judged=a["notes"], accurate=a["accurate"], minor=a["minor"], wrong=a["wrong"],
                       wrong_pct=100 * a["wrong"] / n, accurate_pct=100 * a["accurate"] / n,
                       use_mean=a["use_mean"], use3=a["use3"], valuable=a["valuable"], ko=a["ko"],
                       valuable_per_dollar=a["valuable"] / row["cost"] if row["cost"] else 0)
        rows.append(row)
    rows.sort(key=lambda r: (MODEL_ORDER.get(r["model"], 9), ORDER.get(r["effort"], 9), r["tag"]))
    return rows, judge


def frontier(rows, max_wrong):
    ok = [r for r in rows if "valuable" in r and r["wrong_pct"] <= max_wrong]
    return [r for r in ok if not any((o["cost"] <= r["cost"] and o["valuable"] >= r["valuable"]) and
                                     (o["cost"] < r["cost"] or o["valuable"] > r["valuable"]) for o in ok)]


HC_WORDS = ("histor", "cultur", "period", "trivia")
LANG_WORDS = ("idiom", "slang", "english", "wordplay", "archaic", "register", "dialect", "translation", "word", "pun",
              "insult", "language", "oath")


def bucket(i):
    """history/culture, language, visual or other, from the writer's own category label."""
    c = (i.get("category") or "").lower()
    if any(k in c for k in HC_WORDS):
        return "history/culture"
    if i.get("kind") == "visual":
        return "visual"
    if "background" in c:
        return "history/culture"
    if any(k in c for k in LANG_WORDS):
        return "language"
    return "other"


def by_type(judge):
    """{cell: {bucket: [valuable, use3]}} from judge-results.json's per-note list (empty for older judge files)."""
    out = {}
    for cell, items in (judge.get("notes") or {}).items():
        d = {b: [0, 0] for b in ("history/culture", "language", "other", "visual")}
        for i in items:
            if i["acc"] in ("accurate", "minor") and i["use"] >= 2 and not i.get("ko"):
                d[bucket(i)][0] += 1
                d[bucket(i)][1] += i["use"] == 3
        out[cell] = d
    return out


def render(rows, judge, max_wrong, limit=None):
    L = []
    judged = bool(judge)
    L.append(f"## Pipeline results (generate + refine, first {int(limit // 60) if limit else 45} min)\n")
    hdr = f"{'cell':22} {'cost':>6} {'api time':>8} {'notes':>5}"
    if judged:
        hdr += f" {'valuable':>8} {'acc%':>5} {'wrong':>5} {'use':>5} {'val/$':>6}"
    L.append(hdr)
    L.append("-" * len(hdr))
    for r in rows:
        line = f"{r['cell']:22} {'$%.2f' % r['cost']:>6} {mmss(r['api_seconds']):>8} {r['final_notes']:>5}"
        if judged and "valuable" in r:
            line += (f" {r['valuable']:>8} {r['accurate_pct']:>5.0f} {r['wrong']:>5} {r['use_mean']:>5.2f}"
                     f" {r['valuable_per_dollar']:>6.0f}")
        L.append(line)
    if judged:
        L.append("")
        L.append("acc% = notes the judge rated fully accurate; wrong = notes with a significant false claim; "
                 "use = mean usefulness (1-3);")
        L.append("valuable = accurate-or-minor and use>=2, not just explaining another language's wording; "
                 "val/$ = valuable per dollar.")
        vmax = max(r.get("valuable", 0) for r in rows)
        L.append("\n## Valuable notes (more is better)\n")
        for r in rows:
            L.append(f"{r['cell']:22} {bar(r.get('valuable', 0), vmax):34} {r.get('valuable', 0)}")
        cmax = max(r["cost"] for r in rows)
        L.append("\n## Cost, USD (less is better)\n")
        for r in rows:
            L.append(f"{r['cell']:22} {bar(r['cost'], cmax):34} ${r['cost']:.2f}")
        wmax = max(r["wrong_pct"] for r in rows)
        L.append("\n## Notes with a significant false claim, % of notes (less is better)\n")
        for r in rows:
            L.append(f"{r['cell']:22} {bar(r['wrong_pct'], wmax):34} {r['wrong_pct']:.0f}%")
        bt = by_type(judge)
        if bt:
            L.append("\n## Valuable notes by type (use-3 'illuminating' in brackets)\n")
            L.append(f"{'cell':22} {'history/culture':>16} {'language':>10} {'other speech':>13} {'visual':>8}")
            for r in rows:
                d = bt.get(r["cell"])
                if d:
                    L.append(f"{r['cell']:22} " + " ".join(
                        f"{str(d[b][0]) + ' (' + str(d[b][1]) + ')':>{w}}"
                        for b, w in (("history/culture", 16), ("language", 10), ("other", 13), ("visual", 8))))
            L.append("history/culture = cultural references, historical context, period detail, trivia and background; "
                     "language = idiom, slang, wordplay, archaic words, dialect, register (the writer's own category labels).")
        fr = frontier(rows, max_wrong)
        L.append(f"\n## Cost / value frontier (wrong-note rate <= {max_wrong:g}%)\n")
        L.append("Nothing else is both cheaper and gives at least as many valuable notes:")
        for r in sorted(fr, key=lambda r: r["cost"]):
            L.append(f"  {r['cell']:22} ${r['cost']:.2f}  {r['valuable']} valuable notes")
        reps = {}
        for r in rows:
            reps.setdefault((r["model"], r["effort"]), []).append(r)
        L.append("\n## Run-to-run noise (same settings, run twice)\n")
        for (m, e), rs in reps.items():
            if len(rs) > 1:
                L.append(f"  {m} {e}: valuable {[x['valuable'] for x in rs]}, notes {[x['final_notes'] for x in rs]}, "
                         f"wrong {[x['wrong'] for x in rs]}, cost {['$%.2f' % x['cost'] for x in rs]}")
        L.append(f"\nJudge: {judge['judge_model']} (effort {judge['judge_effort']}), blind, about ${judge['judge_cost']:.2f}.")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-wrong-pct", type=float, default=10.0)
    a = ap.parse_args()
    out = Path(a.out)
    rows, judge = collect(out)
    limits = [json.loads(p.read_text(encoding="utf-8")).get("limit") for p in sorted((out / "runs").glob("*/cell.json"))]
    text = render(rows, judge, a.max_wrong_pct, next((x for x in limits if x), None))
    (out / "report.md").write_text(text + "\n", encoding="utf-8")
    (out / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    keys = sorted({k for r in rows for k in r}, key=lambda k: list(rows[0]).index(k) if k in rows[0] else 99)
    with open(out / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(text)


if __name__ == "__main__":
    main()
