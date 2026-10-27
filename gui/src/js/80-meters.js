// ---------------------------------------------------------------- credit and session meters
async function loadUsage() {
  const r = await api("/api/usage");
  if (r.error) return;
  usageNow = r;
  renderMeters();
  renderCredit();
}
function ago(seconds) {
  const m = Math.round(seconds / 60);
  if (m < 90) return `${m} min`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} days`;
}
let refreshingPlan = false;
// One tiny request on the plan (Haiku, no tools; no API credits), only for the windows Claude Code reports back.
async function refreshPlan() {
  if (refreshingPlan) return;
  refreshingPlan = true;
  $("sessionMeterV").textContent = "checking…";
  const r = await api("/api/plan/refresh", {});
  refreshingPlan = false;
  if (r.usage) usageNow = r.usage;
  renderMeters();
  if (!r.ok) { $("sessionMeterV").textContent = "couldn't check"; $("sessionMeter").title = r.error || ""; }
}
function renderMeters() {
  const u = usageNow;
  const shown = !!u && !!(onPlan() || (info && info.key && info.key.found) || u.balance || (u.spent && u.spent.all > 0));
  $("meters").hidden = !shown;
  if (!shown) return;
  const bal = u.balance;
  let text;
  if (bal) text = `about ${dollars(Math.max(bal.balance_usd, 0))} left${bal.low ? " (low)" : ""}`;
  else if (u.spent.all > 0) text = `${dollars(u.spent.all)} spent · set your balance`;
  else text = "set your balance";
  $("apiMeterV").textContent = text;
  $("apiMeter").classList.toggle("low", !!(bal && bal.low));
  $("apiMeter").title = bal ? "An estimate: the balance you gave, less what this app has spent since. Click to change it."
    : "Anthropic can't tell programs your balance. Give it once and this counts down. Click to set it.";
  const w = u.session && u.session.five_hour;
  const wk = u.session && u.session.seven_day;
  const live = !!w && !w.reset_since && w.percent != null;
  const weekOk = !!wk && !wk.reset_since && wk.percent != null;
  $("sessionMeter").hidden = !(live || weekOk || onPlan());
  $("sessionMeter").title = "How much of your Claude plan is used, as Claude Code last said (its status line, or the "
    + "notes this app writes on the plan). Click for a fresh reading: one tiny request on your plan, no API credits.";
  if (live || weekOk) {
    const parts = [];
    if (live) {
      const when = w.resets_at ? new Date(w.resets_at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : null;
      parts.push(`${Math.round(w.percent)}% used` + (when ? ` · resets ${when}` : ""));
    }
    if (weekOk) parts.push(`week ${Math.round(wk.percent)}%`);
    if (u.session.age_s > 900) parts.push(`seen ${ago(u.session.age_s)} ago`);
    $("sessionMeterK").textContent = live ? "Plan session" : "Plan";
    $("sessionMeterV").textContent = parts.join(" · ");
  } else {
    $("sessionMeterK").textContent = "Plan";
    $("sessionMeterV").textContent = "no reading · click to check";
  }
  renderWeek();
}
function renderWeek() {
  const u = usageNow;
  if (!u) return;
  const sp = u.spent || {};
  const lines = [sp.week_requests
    ? `API calls: ${dollars(sp.week)} in ${plural(sp.week_requests, "request")} over the last 7 days (${dollars(sp.today)} today).`
    : "API calls: none through this app in the last 7 days."];
  const s = u.session;
  const wk = s && s.seven_day, w = s && s.five_hour;
  if (!s) lines.push("Claude plan: no reading yet. It appears once Claude Code's status line has run in this project (see the README).");
  else {
    if (w && !w.reset_since && w.percent != null) lines.push(`Claude plan, this session: ${Math.round(w.percent)}% used.`);
    if (wk && !wk.reset_since && wk.percent != null) lines.push(`Claude plan, this week: ${Math.round(wk.percent)}% of the weekly limit used.`);
    if (s.week) lines.push(`Sessions seen this week: ${s.week.sessions} (the busiest reached ${Math.round(s.week.busiest)}%).`);
  }
  $("weekList").replaceChildren(...lines.map((t) => el("li", {}, t)));
}
function renderCredit() {
  const u = usageNow;
  if (!u) return;
  const bal = u.balance;
  if (bal) {
    const when = new Date(bal.as_of).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    $("creditStatus").textContent = `About ${dollars(Math.max(bal.balance_usd, 0))} left. You gave ${dollars(bal.set_usd)} on ${when}, `
      + `and ${dollars(bal.spent_usd)} has been spent since. It warns below ${dollars(bal.low_usd)}.`;
  } else {
    $("creditStatus").textContent = "No balance given yet." + (u.spent.all > 0 ? ` ${dollars(u.spent.all)} has been spent through this app so far.` : "");
  }
}
async function saveCredit() {
  msg("creditMsg", "Saving…");
  const r = await api("/api/credit", { balance: $("creditInput").value, low: $("lowInput").value });
  msg("creditMsg", r.message || r.error, !!r.ok);
  if (r.ok) {
    $("creditInput").value = "";
    $("lowInput").value = "";
    usageNow = r.usage;
    renderMeters();
    renderCredit();
  }
}

