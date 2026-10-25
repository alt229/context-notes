// Wording tables and what the page knows right now. Components read and change `CN.state` directly.
(() => {
  const MODELS = { "claude-opus-5-5": "Claude Opus", "claude-sonnet-5-5": "Claude Sonnet" };
  const TASKS = { soundtrack: "Listening to the soundtrack", frames: "Pulling frames", transcribe: "Recognising speech",
                  generate: "Writing notes", refine: "Looking at the frames" };
  const STATES = { ready: "Ready", todo: "To do", stopped: "Stopped part-way", working: "Working on it", problem: "Stopped" };
  const STEPS = ["subtitles", "sync", "generate", "refine", "alignment", "done"];

  const state = {
    info: null,          // the answer to /api/info: key, OpenSubtitles, VLC, system
    videos: [],          // the rows of the video list, each with a `state`
    job: { next: 0 },    // how far through the run's items the page has read
    lastEstimate: null,  // the latest `estimate` event, shown with the "send?" question
    polling: false,      // whether poll() is in its loop
    running: false,      // whether a run is on
    asking: false,       // whether a question is waiting on the left note
    keepNote: false,     // keep the left note when the screen is redrawn (after a run ends)
    browsing: "",        // the folder shown in the file browser dialog
  };

  // What stops Claude from writing notes right now, as a sentence for the screen; null when nothing does.
  function blocker(info) {
    if (!info) return null;
    if (info.backend === "claude-code") {
      return info.claude_code.installed ? null
        : "Claude Code isn't installed on this computer. Install it and sign in, or choose your API key in Settings. It's only needed when Claude writes notes.";
    }
    return info.key.found ? null : "Add your Anthropic API key in Settings. It's only needed when Claude writes notes.";
  }

  Object.assign(CN, { MODELS, TASKS, STATES, STEPS, state, blocker });
})();
