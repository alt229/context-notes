// Talking to app.py. Every request carries the key from the page's address; the answer is always an object,
// with an `error` when something went wrong (including the app not answering at all).
(() => {
  const KEY = new URLSearchParams(location.search).get("k") || "";

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

  CN.api = api;
  CN.key = KEY;               // for links that can't send a header, such as a download
})();
