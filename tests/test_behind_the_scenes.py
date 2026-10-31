"""The Behind the Scenes track: the fact sheet (research.py), notes placed from it, spoilers, its own .ass, the
wrapper's --behind-the-scenes, and a second track inside the .mkv. Claude is always a stand-in (fake_claude.py, or
the fake API)."""
import json
import re
import subprocess

import pytest
from conftest import claude_calls, make_srt, message, needs_ffmpeg, place, run_cli

import claude_api
import context_notes as cn
import fake_claude as fake
import embed
import generate_notes as gn
import make_ass
import research
import settings
import usage
import workfiles


# ---------------------------------------------------------------- reading what comes back
def test_facts_are_read_from_the_tagged_block_even_after_talk_with_brackets():
    text = ('I looked at [the IMDb page] and two interviews.\n<facts>[{"fact": "A real scream.", "spoiler": "true", '
            '"when": "0:01:00"}, {"fact": ""}, {"text": "Old key"}]</facts>')
    raw, ok = research.parse_facts(text)
    assert ok and [r.get("fact", r.get("text")) for r in raw] == ["A real scream.", "", "Old key"]
    facts = [f for f in (research.clean_fact(r, duration=120) for r in raw) if f]
    assert facts[0] == {"fact": "A real scream.", "scene": "", "category": "Behind the scenes", "source": "",
                        "spoiler": True, "confidence": "high", "when": "0:01:00"}
    assert facts[1]["fact"] == "Old key" and len(facts) == 2
    assert research.parse_facts('Here you go:\n[{"fact": "No tags"}]')[0][0]["fact"] == "No tags"
    assert research.parse_facts("<facts>[]</facts>") == ([], True)                  # read: nothing worth a note
    assert research.parse_facts("Nothing found.") == ([], False)                     # not read: sent again
    # a mention of the tag after the block doesn't hide the facts in it
    after = '<facts>[{"fact": "Kept"}]</facts>\nAll the facts are in the <facts> block above.'
    assert research.parse_facts(after) == ([{"fact": "Kept"}], True)
    assert "when" not in research.clean_fact({"fact": "x", "when": "3:00:00"}, duration=600)     # past the end


def test_commentary_tracks_by_title_or_number():
    tracks = [{"n": 1, "title": "English 5.1"}, {"n": 2, "title": "Commentary with the director"},
              {"n": 3, "title": "Cast"}]
    assert [t["n"] for t in research.commentary_tracks(tracks)] == [2]
    assert research.commentary_tracks(tracks, "none") == []
    assert [t["n"] for t in research.commentary_tracks(tracks, "2,3")] == [2, 3]
    with pytest.raises(SystemExit, match="no track 7"):
        research.commentary_tracks(tracks, "7")
    assert research.target(228 * 60) == 91 and research.target(10 * 60) == research.MIN_FACTS


def test_fact_lines_give_the_id_spoiler_scene_and_source():
    facts = [{"id": 4, "fact": "It's a model.", "scene": "the castle", "category": "Effects", "source": "https://x",
              "spoiler": True, "confidence": "medium", "when": "0:12:00", "line": "Behold"}]
    line = research.fact_lines(facts)[0]
    assert line.startswith("[#4, Effects, at 0:12:00, SPOILER, medium confidence] It's a model.")
    assert 'Scene: the castle. Line: "Behold". (Source: https://x)' in line


# ---------------------------------------------------------------- the research step
@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    from test_refine_notes import make_video
    d = tmp_path_factory.mktemp("bts-clip")
    make_video(d / "film.mp4")
    return d / "film.mp4"


def a_film(tmp_path, clip, name="The Two Towers (2002)"):
    d = tmp_path / "Movies" / name
    d.mkdir(parents=True)
    video = place(clip, d / f"{name}.mp4")
    make_srt(video.with_suffix(".srt"), n=24)
    return video


@needs_ffmpeg
def test_research_on_the_plan_searches_the_web_and_nothing_else(tmp_path, clip, home, fake_claude):
    video = a_film(tmp_path, clip)
    r = run_cli("research.py", video, "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    sheet = json.loads(workfiles.facts_path(video).read_text())
    assert sheet["complete"] and [f["id"] for f in sheet["facts"]] == [1, 2, 3]
    assert sheet["title"] == "The Two Towers (2002)" and sheet["year"] == 2002 and sheet["video"] == video.name
    assert [f["spoiler"] for f in sheet["facts"]] == [False, True, False]
    assert workfiles.facts_path(video).parent == workfiles.folder(video)          # in its working folder
    call = claude_calls(fake_claude)[-1]
    assert call["argv"][call["argv"].index("--tools") + 1] == "WebSearch,WebFetch"
    assert call["argv"][call["argv"].index("--permission-mode") + 1] == "dontAsk"
    assert call["cwd"] == str(workfiles.folder(video)) and call["env"] == []
    assert "1 of them give away something later" in r.stdout

    calls = len(claude_calls(fake_claude))                                        # done: nothing more is sent
    r = run_cli("research.py", video, "--yes", cwd=tmp_path, home_dir=home)
    assert "already there (3 facts)" in r.stdout and len(claude_calls(fake_claude)) == calls
    r = run_cli("research.py", video, "--yes", "--again", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0 and "Kept the old fact sheet: facts-The Two Towers (2002).json.bak" in r.stdout


@needs_ffmpeg
def test_research_with_an_old_claude_code_stops_rather_than_ask_for_permission(tmp_path, clip, home, monkeypatch):
    video = a_film(tmp_path, clip)
    monkeypatch.setenv("FAKE_CLAUDE_HELP", "no-allowed-tools")
    r = run_cli("research.py", video, "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode != 0 and "too old to be allowed to search the web" in r.stdout + r.stderr
    assert not json.loads(workfiles.facts_path(video).read_text())["complete"]


def web_replies(n, body, headers):
    """The API: the search turn comes back paused once, then finished with the facts."""
    if n == 1:
        return 200, {**message("Searching."), "stop_reason": "pause_turn",
                     "usage": {"input_tokens": 20000, "output_tokens": 100,
                               "server_tool_use": {"web_search_requests": 3}}}
    return 200, {**message("<facts>" + json.dumps([{"fact": "Real scream.", "source": "https://x", "spoiler": False}])
                           + "</facts>"),
                 "usage": {"input_tokens": 30000, "output_tokens": 900, "server_tool_use": {"web_search_requests": 2}}}


@needs_ffmpeg
def test_research_with_api_credits_uses_the_web_search_tool_and_counts_the_searches(tmp_path, clip, api,
                                                                                   api_key_file, home, usage_dir):
    video = a_film(tmp_path, clip)
    api.responder = web_replies
    r = run_cli("research.py", video, "--yes", "--route", "api", "--model", "claude-opus-5-5", "--api-url", api.url,
                cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    first, second = (c["body"] for c in api.calls)
    assert first["tools"] == [{"type": "web_search_20250305", "name": "web_search",
                               "max_uses": claude_api.WEB_SEARCHES}]
    assert second["messages"][-1]["role"] == "assistant"                         # the paused turn, sent back
    assert "up to about $" in r.stdout and "up to 20 searches" in r.stdout
    ledger = [json.loads(line) for line in (usage_dir / "usage.jsonl").read_text().splitlines()]
    assert [round(e["usd"], 4) for e in ledger] == [round(20000 * 4e-6 + 100 * 20e-6 + 0.03, 4),
                                                    round(30000 * 4e-6 + 900 * 20e-6 + 0.02, 4)]
    assert json.loads(workfiles.facts_path(video).read_text())["facts"][0]["fact"] == "Real scream."


@needs_ffmpeg
def test_a_commentary_track_is_used_first_and_timed(tmp_path, clip, home, monkeypatch):
    video = a_film(tmp_path, clip)
    mkv = video.with_suffix(".mkv")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(video), "-map", "0:v", "-map", "0:a",
                    "-map", "1:a", "-c", "copy", "-metadata:s:a:1", "title=Commentary by the director",
                    str(mkv)], check=True)
    assert [t["title"] for t in research.audio_tracks(mkv)][1] == "Commentary by the director"
    monkeypatch.setattr(research, "_have_whisper", lambda: True)
    monkeypatch.setattr(research, "transcribe_commentary", lambda v, t, m=None: [
        {"s": 12.0, "e": 15.0, "t": "We shot this in one take."}, {"s": 40.0, "e": 44.0, "t": "That's my mum."}])
    research.research(mkv, model="claude-opus-5-5", route="plan", assume_yes=True)
    sheet = json.loads(workfiles.facts_path(mkv).read_text())
    assert sheet["commentary"] == [{"track": 2, "title": "Commentary by the director"}]
    first = sheet["facts"][:2]
    assert [f["when"] for f in first] == ["0:00:12", "0:00:40"]
    assert all(f["source"] == "Commentary: Commentary by the director" for f in first)
    assert sheet["done"] == ["commentary:2:1", "web"] and len(sheet["facts"]) == 5


# ---------------------------------------------------------------- notes from the sheet, and the build
def sheet_for(video):
    path = workfiles.facts_path(video)
    workfiles.make_dirs(path.parent)
    facts = [dict(f, id=k) for k, f in enumerate(fake.FACTS, 1)]
    path.write_text(json.dumps({"title": "T", "complete": True, "done": ["web"], "facts": facts}))
    return path


@needs_ffmpeg
def test_notes_are_written_only_from_the_sheet_and_built_into_their_own_file(tmp_path, clip, home, fake_claude):
    video = a_film(tmp_path, clip)
    sheet_for(video)
    srt = make_srt(video.with_suffix(".srt"), n=400, spacing=0.35, length=0.3)     # long enough for three parts
    r = run_cli("make_ass.py", srt, "--generate", "--behind-the-scenes", "--video", video, "--yes", "--title", "T",
                cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    notes_path = workfiles.bts_notes_path(video)
    spec = json.loads(notes_path.read_text())
    assert notes_path.name == "behind-the-scenes-The Two Towers (2002).json" and spec["track"] == gn.BTS
    told = [n for n in spec["notes"] if n["category"] != "About these notes"]
    assert sorted(n["fact"] for n in told) == [1, 2]                     # once each; #99 isn't on the sheet: left out
    assert "left out a note that tells no fact from the fact sheet" in r.stdout
    assert [n["spoiler"] for n in told] == [False, True]
    system = claude_calls(fake_claude)[0]["system"]
    assert "[#3, Effects" in system and "Use ONLY the fact sheet" in system
    assert "Facts already used in earlier notes (don't use them again): #1, #2" in claude_calls(fake_claude)[1]["prompt"]
    ass = video.parent / "The Two Towers (2002).behind-the-scenes.notes.ass"
    text = ass.read_text(encoding="utf-8-sig")
    assert "spoilers included" in text and "(spoiler)" in text and "Fact 2 told here" in text
    assert not video.with_suffix(".notes.ass").exists() and not video.with_suffix(".en.ass").exists()   # no Plex copy
    assert not workfiles.notes_path(video, srt).exists()                # the context notes are left alone

    r = run_cli("make_ass.py", srt, "--behind-the-scenes", "--video", video, "--spoilers", "leave-out",
                cwd=tmp_path, home_dir=home)
    text = ass.read_text(encoding="utf-8-sig")
    assert "Left out 1 note(s) marked as spoilers" in r.stdout
    assert "spoilers left out" in text and "Fact 2 told here" not in text and "Fact 1 told here" in text
    assert json.loads(notes_path.read_text())["spoilers"] == "leave-out"
    run_cli("make_ass.py", srt, "--behind-the-scenes", "--video", video, cwd=tmp_path, home_dir=home)
    assert "spoilers left out" in ass.read_text(encoding="utf-8-sig")        # the film's own choice is kept


def test_spoilers_ask_once_and_keep_the_answer(tmp_path, monkeypatch):
    notes = tmp_path / "behind-the-scenes-x.json"
    spec = {"notes": [{"text": "a", "spoiler": True}, {"text": "b"}]}
    notes.write_text(json.dumps(spec))
    monkeypatch.setattr(settings, "spoilers_default", lambda: "ask")
    asked = []
    monkeypatch.setattr(make_ass.prompts, "ask", lambda text, choices, default, auto, id: asked.append((id, default))
                        or "n")
    a = type("A", (), {"spoilers": None, "yes": False})()
    assert make_ass.spoiler_choice(a, spec, notes) == "leave-out" and asked == [("bts.spoilers", "y")]
    assert json.loads(notes.read_text())["spoilers"] == "leave-out"
    assert make_ass.spoiler_choice(a, spec, notes) == "leave-out" and len(asked) == 1     # kept: not asked again
    monkeypatch.setattr(settings, "spoilers_default", lambda: "include")
    fresh = {"notes": [{"text": "a", "spoiler": True}]}
    assert make_ass.spoiler_choice(a, fresh, notes) == "include" and "spoilers" not in fresh     # Settings: not kept


@needs_ffmpeg
def test_the_frames_step_places_facts_with_no_dialogue_and_adds_nothing_else(tmp_path, clip, home, fake_claude):
    video = a_film(tmp_path, clip)
    sheet_for(video)
    srt = video.with_suffix(".srt")
    run_cli("make_ass.py", srt, "--generate", "--behind-the-scenes", "--video", video, "--yes", cwd=tmp_path,
            home_dir=home)
    r = run_cli("make_ass.py", srt, "--refine", "--behind-the-scenes", "--video", video, "--yes", "--assume-synced",
                cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    notes = json.loads(workfiles.bts_notes_path(video).read_text())["notes"]
    placed = [n for n in notes if n.get("fact") == 3]
    assert len(placed) == 1 and placed[0]["kind"] == "visual"                   # once, in the first stretch only
    assert not any(n["text"] == "Not a fact from the sheet" for n in notes)
    frames = [c for c in claude_calls(fake_claude) if 'refine the "Behind the Scenes"' in c["system"]]
    assert "Facts not placed yet (add a note for any whose moment is in these frames): #3" in frames[0]["prompt"]
    assert "(none: every fact has a note)" in frames[-1]["prompt"]


# ---------------------------------------------------------------- the wrapper, and the film's own files
@needs_ffmpeg
def test_the_wrapper_makes_the_track_end_to_end_then_skips_it(tmp_path, clip, home, fake_claude):
    video = a_film(tmp_path, clip)
    r = run_cli("context_notes.py", video, "--behind-the-scenes", "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"$CN/research.py"' in r.stdout and "Ready: play" in r.stdout
    assert re.search(r'"\$CN/make_ass.py" .*--generate .*--behind-the-scenes --facts', r.stdout)
    assert (video.parent / "The Two Towers (2002).behind-the-scenes.notes.ass").exists()
    assert not video.with_suffix(".notes.ass").exists()
    kinds = [("research" if "You research" in c["system"] else "frames" if "You refine" in c["system"] else "notes")
             for c in claude_calls(fake_claude)]
    assert kinds[0] == "research" and "notes" in kinds and kinds[-1] == "frames"
    calls = len(kinds)
    r = run_cli("context_notes.py", video, "--behind-the-scenes", "--yes", cwd=tmp_path, home_dir=home)
    assert "Already done" in r.stdout and len(claude_calls(fake_claude)) == calls
    r = run_cli("context_notes.py", video, "--behind-the-scenes", "--status", cwd=tmp_path, home_dir=home)
    assert "[ done]" in r.stdout and "Behind the Scenes: 3 facts looked up" in r.stdout
    r = run_cli("context_notes.py", video, "--status", cwd=tmp_path, home_dir=home)
    assert "[to do]" in r.stdout and "no notes yet" in r.stdout                  # the context notes: not started
    # a new spoiler choice is a free rebuild
    r = run_cli("context_notes.py", video, "--behind-the-scenes", "--yes", "--spoilers", "leave-out", cwd=tmp_path,
                home_dir=home)
    assert "rebuilding" in r.stdout and len(claude_calls(fake_claude)) == calls
    assert "spoilers left out" in (video.parent / "The Two Towers (2002).behind-the-scenes.notes.ass").read_text(
        encoding="utf-8-sig")


def test_the_options_that_go_with_behind_the_scenes_are_refused_alone(tmp_path, home):
    r = run_cli("context_notes.py", tmp_path, "--spoilers", "include", cwd=tmp_path, home_dir=home)
    assert r.returncode == 2 and "go with --behind-the-scenes" in r.stderr


def test_tidy_moves_the_new_working_files_too(tmp_path):
    (tmp_path / "Film.mkv").write_bytes(b"x")
    for name in ("behind-the-scenes-Film.json", "facts-Film.json", "Film.behind-the-scenes.notes.ass"):
        (tmp_path / name).write_text("{}")
    plan, _ = workfiles.old_files(tmp_path)
    moving = sorted(p.name for p, _ in plan[tmp_path / "Film.mkv"])
    assert moving == ["behind-the-scenes-Film.json", "facts-Film.json"]          # the .ass stays, for players
    assert usage.film_name("behind-the-scenes-Film.json") == "Film" == usage.film_name("facts-Film.json")


def test_a_build_with_other_spoilers_than_the_film_has_counts_as_out_of_date(tmp_path):
    ass = tmp_path / "Film.behind-the-scenes.notes.ass"
    ass.write_text("[Script Info]\n; Look: build 2, background see-through, opacity 30%, 150 words a minute, spoilers "
                   "included\n", encoding="utf-8")
    assert cn.ass_look(ass)["spoilers"] == "include"
    opts = type("O", (), {"behind_the_scenes": True, "spoilers": "leave-out", "reading_speed": None,
                          "note_background": None, "note_opacity": None})()
    assert cn.wanted_look({"notes": []}, opts)["spoilers"] == "leave-out"
    opts.spoilers = None
    assert cn.wanted_spoilers({"spoilers": "leave-out"}, opts) == "leave-out"
    assert cn.wanted_spoilers({}, opts) == settings.spoilers_default()


# ---------------------------------------------------------------- inside the .mkv
@needs_ffmpeg
def test_both_tracks_go_inside_and_a_change_replaces_them_without_a_second_copy(tmp_path):
    from test_embed import ASS, make_clips
    clips = make_clips(tmp_path / "clips")
    video = tmp_path / "Film.mkv"
    video.write_bytes((clips / "disc.mkv").read_bytes())
    video.with_suffix(".notes.ass").write_text(ASS, encoding="utf-8-sig")
    bts_ass = workfiles.bts_ass_path(video)
    bts_ass.write_text(ASS.replace("A note", "A behind the scenes note"), encoding="utf-8-sig")
    state = embed.film_state(video)
    assert state["action"] == "add" and set(state["tracks"]) == {"context", workfiles.BTS}
    r = run_cli("embed.py", video, "--yes", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    info = embed.probe(video)
    subs = [embed.tag(s, "title") for s in info["streams"] if s["codec_type"] == "subtitle"]
    assert subs[-2:] == ["Context Notes", "Behind the Scenes"] and len(subs) == 3      # the disc's own track kept
    assert embed.tag(embed.notes_tracks(info, embed.BTS_TRACK)[0], "CONTEXT_NOTES_BTS_SHA1") == embed.sha1(bts_ass)
    assert embed.film_state(video)["action"] == "current"

    bts_ass.write_text(ASS.replace("A note", "Changed"), encoding="utf-8-sig")
    tracks = embed.film_state(video)["tracks"]
    assert {k: (t["action"], t["reason"]) for k, t in tracks.items()} == {"context": ("current", "already inside"),
                                                                          workfiles.BTS: ("update", "")}
    assert run_cli("embed.py", video, "--yes", cwd=tmp_path).returncode == 0
    info = embed.probe(video)
    assert len(embed.notes_tracks(info)) == 1 and len(embed.notes_tracks(info, embed.BTS_TRACK)) == 1
    assert embed.film_state(video)["action"] == "current"


# ---------------------------------------------------------------- the app
def test_the_app_passes_the_track_and_its_options_on(tmp_path):
    import app
    film = tmp_path / "Film.mkv"
    film.write_bytes(b"x")
    args = app.common_args({"path": str(film), "track": "behind-the-scenes", "spoilers": "leave-out",
                            "research_again": True})
    assert args[1:] == ["--behind-the-scenes", "--spoilers", "leave-out", "--research-again"]
    assert "--behind-the-scenes" not in app.common_args({"path": str(film), "track": "context", "spoilers": "ask"})
    with pytest.raises(app.BadRequest):
        app.common_args({"path": str(film), "track": "behind-the-scenes", "spoilers": "--yes"})
    assert settings.check("bts_spoilers", "ask") == "ask"
    with pytest.raises(ValueError):
        settings.check("bts_spoilers", "sometimes")


# ---------------------------------------------------------------- what the review found
@needs_ffmpeg
def test_an_unreadable_look_up_isnt_finished_and_is_sent_again(tmp_path, clip, home, fake_claude, monkeypatch):
    video = a_film(tmp_path, clip)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "garbage")
    r = run_cli("research.py", video, "--yes", cwd=tmp_path, home_dir=home)
    sheet = json.loads(workfiles.facts_path(video).read_text())
    assert r.returncode != 0 and not sheet["complete"] and sheet["done"] == [] and "couldn't read the reply" in r.stdout
    assert cn.facts_state(workfiles.facts_path(video))[0] == "partial"
    monkeypatch.delenv("FAKE_CLAUDE_MODE")
    calls = len(claude_calls(fake_claude))
    r = run_cli("research.py", video, "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0 and len(claude_calls(fake_claude)) == calls + 1
    assert json.loads(workfiles.facts_path(video).read_text())["complete"]


@needs_ffmpeg
def test_the_api_allowance_holds_for_the_web_search(tmp_path, clip, api, api_key_file, home, monkeypatch, usage_dir):
    """The plan's limit is reached: the allowance is checked against the web search's own estimate, not an average."""
    video = a_film(tmp_path, clip)
    api.responder = web_replies
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    r = run_cli("research.py", video, "--yes", "--route", "plan", "--api-fallback", "0.5", "--model",
                "claude-opus-5-5", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode != 0 and "would go past the $0.50 allowed" in r.stdout + r.stderr, r.stdout + r.stderr
    assert api.calls == []


@needs_ffmpeg
def test_a_paused_search_stops_at_the_allowance(tmp_path, clip, api, api_key_file, home, monkeypatch, usage_dir):
    video = a_film(tmp_path, clip)

    def costly(n, body, headers):              # each part costs $4, and it never finishes
        return 200, {**message("Still searching."), "stop_reason": "pause_turn",
                     "usage": {"input_tokens": 1000000, "output_tokens": 10, "server_tool_use": {"web_search_requests": 2}}}
    api.responder = costly
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    r = run_cli("research.py", video, "--yes", "--route", "plan", "--api-fallback", "4.5", "--model",
                "claude-opus-5-5", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode != 0 and "would go past the $4.50 allowed" in r.stdout + r.stderr, r.stdout + r.stderr
    assert len(api.calls) == 1                                                   # not sent on again
    assert api.calls[0]["body"]["tools"][0]["max_uses"] == claude_api.WEB_SEARCHES
    ledger = [json.loads(line) for line in (usage_dir / "usage.jsonl").read_text().splitlines()]
    assert len(ledger) == 1 and ledger[0]["usd"] > 4


def test_cache_tokens_are_counted_in_what_a_request_cost(usage_dir):
    claude_api._record_usage("claude-opus-5-5", {"usage": {"input_tokens": 100, "output_tokens": 1000,
                                                           "cache_creation_input_tokens": 10000,
                                                           "cache_read_input_tokens": 100000,
                                                           "server_tool_use": {"web_search_requests": 3}}})
    entry = json.loads((usage_dir / "usage.jsonl").read_text().splitlines()[-1])
    want = (100 + 1.25 * 10000 + 0.1 * 100000) * 4e-6 + 1000 * 20e-6 + 0.03
    assert abs(entry["usd"] - want) < 1e-6


@needs_ffmpeg
def test_a_stopped_research_again_is_picked_up_and_the_notes_follow(tmp_path, clip, home, fake_claude, monkeypatch):
    video = a_film(tmp_path, clip)
    args = (video, "--behind-the-scenes", "--yes", "--no-refine")
    assert run_cli("context_notes.py", *args, cwd=tmp_path, home_dir=home).returncode == 0
    first = json.loads(workfiles.facts_path(video).read_text())["made"]
    assert json.loads(workfiles.bts_notes_path(video).read_text())["facts_made"] == first
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    r = run_cli("context_notes.py", *args, "--research-again", cwd=tmp_path, home_dir=home)
    assert "Stopped at the look-up step" in r.stdout
    r = run_cli("context_notes.py", video, "--behind-the-scenes", "--status", cwd=tmp_path, home_dir=home)
    assert "[to do]" in r.stdout and "stopped part-way" in r.stdout
    monkeypatch.delenv("FAKE_CLAUDE_MODE")
    r = run_cli("context_notes.py", *args, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    made = json.loads(workfiles.facts_path(video).read_text())["made"]
    assert made != first and "written again from this one" in r.stdout
    assert json.loads(workfiles.bts_notes_path(video).read_text())["facts_made"] == made
    r = run_cli("context_notes.py", *args, cwd=tmp_path, home_dir=home)
    assert "Already done" in r.stdout


def test_ask_uses_the_films_answer_and_yes_to_all_takes_the_default(tmp_path, monkeypatch):
    notes = tmp_path / "behind-the-scenes-x.json"
    spec = {"spoilers": "leave-out", "notes": [{"text": "a", "spoiler": True}]}
    notes.write_text(json.dumps(spec))
    monkeypatch.setattr(make_ass.prompts, "ask", lambda *a, **k: pytest.fail("asked again"))
    a = type("A", (), {"spoilers": "ask", "yes": False})()
    assert make_ass.spoiler_choice(a, spec, notes) == "leave-out"
    import prompts
    assert prompts.YES_TO_ALL["bts.spoilers"] is None
    opts = type("O", (), {"behind_the_scenes": True, "spoilers": "ask"})()
    assert cn.wanted_spoilers({"spoilers": "leave-out"}, opts) == "leave-out"
    assert cn.wanted_spoilers({"spoilers": "ask"}, opts) is None                 # a hand-edited value is ignored
