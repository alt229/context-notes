#!/usr/bin/env python3
"""
sending.py - what the generate and refine steps share about sending their parts to Claude:

- Sender: where the requests go. On the "plan" route (the default) each one goes through Claude Code on your Claude
  plan (claude_code.py), with no API credits; on the "api" route, to the API (claude_api.py). When the plan can't go
  on (Claude Code missing or signed out, the plan's usage limit, or the 5-hour session at 90%), the run moves to API
  credits only if that's allowed: up to --api-fallback dollars for the run (Settings: "Use API credits when the plan
  runs out"), or after a yes to the question that shows what the rest would cost. With nobody to ask (--yes, no
  terminal) and no allowance, it stops, keeping what was written.
- estimate(): after a step's "Plan:" line, the credit note and the estimate the app is told.
- confirm(): ask before anything is sent (or stop, when nobody can be asked and --yes wasn't given).
- send_parts(): send the parts one at a time. Before each, check the credit (usage.guard); after each, the step
  reads the reply and saves, then the cost line is shown (usage.report). Whenever the run stops early (out of
  credit, an API error, the plan's limit, Ctrl-C or the app's Cancel), the step keeps what was written first.

Each step plans its own parts and reads its own replies (generate_notes.py, refine_notes.py); this is the loop
between.
"""
import sys

import claude_api
import claude_code
import prompts
import usage


def cost_words(cost, on_plan):
    """The end of a "Plan:" line: what it costs."""
    if on_plan:
        return ", on your Claude plan through Claude Code (no API credits)."
    return f", roughly ${cost:.2f} in API credits." if cost is not None else "."


def estimate(step, cost, limit, on_plan=False, **fields):
    """The credit note under the "Plan:" line and the `estimate` event (`fields`, then the cost, limit and balance).
    On the plan the cost is what it would be in API credits (for the question if the plan runs out), and the
    session reading is shown instead of the credit. Returns what one request is expected to cost in API credits,
    for usage.guard and the API-credit allowance."""
    requests = fields.get("requests")
    if on_plan:
        s = usage.session()
        if s is not None:
            print("  " + usage.session_line(s))
        bal = usage.balance()
        prompts.event("estimate", step=step, **fields, route="plan", cost_usd=None,
                      api_cost_usd=None if cost is None else round(cost, 4), limit=limit,
                      balance_usd=None if bal is None else bal["balance_usd"])
    else:
        bal = usage.plan_note(cost)
        prompts.event("estimate", step=step, **fields, cost_usd=None if cost is None else round(cost, 4), limit=limit,
                      balance_usd=None if bal is None else bal["balance_usd"])
    return None if cost is None or not requests else cost / requests


def confirm(assume_yes, question, id, unattended, cancelled):
    """Ask `question` before sending. Exits with `unattended` when there's nobody to ask, `cancelled` on a no."""
    if assume_yes:
        return
    if not prompts.interactive():
        sys.exit(unattended)
    if not prompts.confirm(question, id=id):
        sys.exit(cancelled)


class Sender:
    """One step's requests, on the plan or the API (see the top of this file). Call it with a message and the number
    of requests left (this one included); it returns the reply in the API's shape. `folders`: what Claude Code may
    open with its Read tool (the contact sheets); `workdir`: the folder it runs in (the notes'), never this repo."""

    def __init__(self, step, model, route="api", fallback_usd=0.0, effort=None, max_tokens=claude_api.MAX_TOKENS,
                 timeout=300, key_file=None, api_url=claude_api.API_URL, assume_yes=False, workdir=None, folders=()):
        self.step, self.model, self.effort, self.max_tokens, self.timeout = step, model, effort, max_tokens, timeout
        self.key_file, self.api_url, self.assume_yes = key_file, api_url, assume_yes
        self.workdir, self.folders = workdir, list(folders)
        self.route = route
        self.fallback_usd = float(fallback_usd or 0)
        self.allowance = None            # API dollars this run may use after leaving the plan; None: no limit of ours
        self.blocked = None              # why Claude Code can't be used, found before anything was sent
        self.approved = False            # yes to the question about API credits (so it isn't asked twice)
        self.key = None
        self.system = None
        self.per_request_usd = None      # one request in API credits, from the estimate
        self.plan_requests = 0           # answered on the plan (for the closing line)

    @property
    def on_plan(self):
        """Whether the requests are going (or are meant to go) on the plan, with no API credit."""
        return self.route == "plan" and self.blocked is None

    def ready(self, estimate_only=False):
        """Before the estimate. On the API: the key now, so a missing one stops before any local work. On the plan:
        can Claude Code be used here? When it can't, the estimate is given in API credits and confirm() decides."""
        if self.route == "api":
            if not estimate_only:
                self.key = claude_api.load_key(self.key_file)
            return
        problem = claude_code.problem()
        if problem:
            self.blocked = problem
            print(f"Claude Code can't be used here, so this can't go on your Claude plan: {problem}")

    def confirm(self, requests, question, id, unattended, cancelled, plan_question=None):
        """The question before sending. When Claude Code can't be used, first what to do about that (API credits,
        if allowed); a yes to that question is the yes to this one."""
        if self.blocked:
            self.leave_plan(self.blocked, requests, before=True)
            if self.approved:
                return
        confirm(self.assume_yes, plan_question if self.on_plan and plan_question else question, id, unattended,
                cancelled)

    def leave_plan(self, reason, left, before=False):
        """The plan can't go on: carry on with API credits if that's allowed, else stop (sys.exit, after which the
        step keeps what was written)."""
        rest = None if self.per_request_usd is None else self.per_request_usd * left
        rest_words = (f" The {left} request{'s' if left != 1 else ''} left would cost about {usage.money(rest)}."
                      if rest is not None else "")
        bal = usage.balance()
        bal_words = f" About {usage.money(max(bal['balance_usd'], 0))} of API credit is left." if bal else ""
        room = self.fallback_usd - usage.run_api_spent() if self.fallback_usd > 0 else 0.0
        stop = (f"Stopped{'' if before else ' before the next request'}: what was written is kept. Run the same "
                f"command again when the plan has room (it picks up where this stopped), or allow API credits for "
                f"when the plan runs out: Settings, Claude, or --api-fallback 5.")
        if not before:
            print()                              # the part's line is still open
        if room > 0 and self.per_request_usd is None:   # an allowance can't be kept to without a price
            room = 0.0
            used_up_why = (f" The allowance for API credits can't be kept to, because the price of {self.model} isn't "
                           f"known here.")
        else:
            used_up_why = None
        if room <= 0 and usage.api_approved_for_run():  # a yes earlier in this run (an earlier step) still holds
            print(f"  {reason} Carrying on with API credits, as you said earlier in this run." + rest_words, flush=True)
            self.approved = True
            self.allowance = None
        elif room > 0:
            self.allowance = self.fallback_usd
            print(f"  {reason} Carrying on with API credits, up to {usage.money(self.fallback_usd)} for this run"
                  + (f" ({usage.money(room)} of it left)" if room < self.fallback_usd - 0.005 else "") + "."
                  + rest_words, flush=True)
        else:
            used_up = used_up_why or (f" The {usage.money(self.fallback_usd)} of API credit allowed for this run is "
                                      f"used up." if self.fallback_usd > 0 else "")
            if self.assume_yes or not prompts.interactive():
                sys.exit(f"{reason}{used_up} {stop}")
            if not prompts.confirm(f"{reason}{used_up} Carry on with API credits instead?{rest_words}{bal_words}",
                                   id="plan.fallback"):
                sys.exit(f"{reason} {stop}")
            self.approved = True
            self.allowance = None
            usage.approve_api_for_run()
        self.route, self.blocked = "api", None
        self.key = claude_api.load_key(self.key_file)
        usage.set_per_request(self.per_request_usd)
        prompts.event("route", step=self.step, route="api", reason=reason, allowance_usd=self.allowance)
        if not before:
            halt = usage.guard(self.assume_yes)  # the credit check send_parts made was for the plan
            if halt:
                sys.exit(halt)
            print("  this part with API credits ...", end=" ", flush=True)

    def within_allowance(self):
        """Before each API request after leaving the plan: stop (or ask) at the run's allowance."""
        if self.allowance is None:
            return
        spent, nxt = usage.run_api_spent(), usage.next_cost() or self.per_request_usd or 0.0
        if spent + nxt <= self.allowance + 1e-9:
            return
        text = (f"This run has used about {usage.money(spent)} of API credits, and the next request (about "
                f"{usage.money(nxt)}) would go past the {usage.money(self.allowance)} allowed for it.")
        print()
        if self.assume_yes or not prompts.interactive():
            sys.exit(f"{text} Stopped: what was written is kept. Run the same command again to pick up, with a "
                     f"higher --api-fallback (or Settings, Claude) if you want it to go on with API credits.")
        if not prompts.confirm(text + " Carry on anyway?", id="plan.allowance"):
            sys.exit(f"{text} Stopped: what was written is kept; run the same command again to pick up.")
        self.allowance = None
        print("  carrying on ...", end=" ", flush=True)

    def __call__(self, message, left=1):
        if self.route == "plan":
            full = usage.session_full()
            if full:
                self.leave_plan(full + " Stopping before the plan's limit.", left)
            else:
                try:
                    reply = claude_code.call(self.model, self.system, message, effort=self.effort,
                                             workdir=self.workdir, folders=self.folders,
                                             timeout=claude_code.TIMEOUT if self.folders else 600)
                    self.plan_requests += 1
                    return reply
                except claude_code.CantGoOn as e:
                    self.leave_plan(str(e), left)
        self.within_allowance()
        return claude_api.call_api(self.key, self.model, self.system, message, self.api_url, timeout=self.timeout,
                                   max_tokens=self.max_tokens, effort=self.effort)


def used_line(sender, model, tin, tout):
    """The step's closing line about what it used. On the API alone it's as it always was; with requests on the plan,
    it says so, and gives dollars only for the ones that went to the API."""
    if not sender.plan_requests:
        actual = claude_api.cost(model, tin, tout)
        return f"Used {tin:,} input and {tout:,} output tokens" + (f" (about ${actual:.2f})." if actual is not None
                                                                   else ".")
    api = usage.run_totals()
    if not api["requests"]:
        return f"Used {tin:,} input and {tout:,} output tokens, on your Claude plan (no API credits)."
    return (f"Used {tin:,} input and {tout:,} output tokens: {sender.plan_requests} request(s) on your Claude plan, "
            f"{api['requests']} with API credits (about {usage.money(api['usd'])}).")


class Tokens:
    """The tokens a run has used so far, from each reply's `usage`."""

    def __init__(self):
        self.input = self.output = 0

    def add(self, reply):
        used = reply.get("usage", {})
        self.input += used.get("input_tokens", 0)
        self.output += used.get("output_tokens", 0)


def send_parts(run, jobs, send, step, done_before, assume_yes):
    """Send `jobs` in order. `run` is the step's own record of where it is:
      run.prepare(job) -> (the line printed before the request, the message to send),
      run.apply(job, reply) reads the reply, prints what it did and saves,
      run.keep() saves what there is when the run stops early (it's then stopped with the reason),
      run.tokens, a Tokens, counts what was used.
    `send(message, left)` makes the request (a Sender) and returns the reply; `left` counts this one. `done_before`:
    parts finished by an earlier run, so the app's progress counts from there."""
    total = done_before + len(jobs)
    try:
        for j, job in enumerate(jobs):
            stop = usage.guard(assume_yes)
            if stop:                             # about to run out of credit: keep what was paid for, then say so
                run.keep()
                sys.exit(stop)
            label, message = run.prepare(job)
            prompts.progress(step, done_before + j, total, "requests")    # before the line below (stays open)
            print(label, end=" ", flush=True)
            try:
                reply = send(message, len(jobs) - j)
            except SystemExit:                   # an API error, or the plan can't go on: keep what was written
                run.keep()
                raise
            run.tokens.add(reply)
            run.apply(job, reply)
            usage.report()                       # once the part is counted and saved, never before
    except KeyboardInterrupt:                    # Ctrl-C, or a GUI's Cancel, at any point: keep what was paid for
        run.keep()
        raise
    prompts.progress(step, total, total, "requests")
