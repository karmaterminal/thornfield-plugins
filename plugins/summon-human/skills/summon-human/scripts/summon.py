#!/usr/bin/env python3
"""summon-human: ask a frond-alarm repository to phone its human, then read what happened.

    summon.py check
    summon.py submit "TEXT" [--ask QUESTION]... [--line CODE] [--dry-run] [--request-id ID]
                     [--no-wake] [--allow-pending]
    summon.py status (ISSUE | --request-id ID) [--wait SECONDS]

Every command also takes --repo OWNER/NAME (default $FROND_ALARM_REPO, else
karmaterminal/frond-alarm) and --json.

A request is an issue in that repository, written byte for byte as its submit.sh writes it: the
title `[call] REQUEST_ID`, the label `call-request`, and a body holding the `frond-call-v1` marker
and fenced JSON with sorted keys. The alarm's own worker reads the issue, decides and dials; this
script only files the issue, sends the optional wake, and reads back the labels and comments that
the worker wrote, figs's answers to any questions among them.

The only credential is the caller's own GitHub token: $FROND_ALARM_TOKEN, $GH_TOKEN, $GITHUB_TOKEN
or `gh auth token`, in that order. It is sent only to api.github.com and never printed.
Standard library only.

Exit codes: 0 done; 1 GitHub could not be read or written, or no such request; 2 refused, nothing
was filed; 3 filed but not queued, and closed again; 4 unknown whether the issue was filed; 5 still
pending.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

API = "https://api.github.com"
DEFAULT_REPO = "karmaterminal/frond-alarm"
WORKER = "github-actions[bot]"  # the login of the alarm workflow's own token
LABEL = "call-request"
MARKER = "<!-- frond-call-v1 -->"
DEFAULT_LINE = "707"  # submit.sh's default
SOURCE = "prince_manual"  # the alarm takes its other source, outage, only from its own seat watcher
MAX_TEXT = 240
MAX_QUESTIONS, MAX_QUESTION = 3, 120
SPEAKABLE = re.compile(r"[A-Za-z0-9 .,;:!?'()/-]+")
REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{6,80}")
LINE = re.compile(r"[0-9]{3}")
REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
MAX_PAGES = 10
POLL_SECONDS = 30
QUEUED_HINT_MIN = 10

OK, GITHUB_ERROR, REFUSED, NOT_QUEUED, UNKNOWN, PENDING = 0, 1, 2, 3, 4, 5

# Terminal labels, in the order the worker can set them; the first one present wins.
OUTCOMES = ("answered", "not-answered", "outcome-unknown", "uncertain", "failed", "dry-run",
            "duplicate", "rejected")
ANSWER_LABELS = ("has-answers", "answers-pending", "answers-unavailable")
WORKER_LABELS = set(OUTCOMES) | {"dialing", "accepted"} | set(ANSWER_LABELS)
ANSWER_PREFIXES = ("answers:", "answers (reconciled):")  # the worker's comments holding figs's answers
ACK = re.compile(r"^acknowledged: (yes|no|unknown|pending)$", re.M)
# Comments the alarm's worker reads from any author: one from someone else can hold a request in
# flight, close it as uncertain, or point the answers the worker posts at another call.
ALARM_READS = ("lease", "intent", "accepted")
LOOKALIKES = ("outcome", "answers", "rejected", "duplicate", "uncertain", "failed", "dry")
# What each state means, and what to do next. The skill's outcome table says the same.
STATES = {
    "answered": ("a human turn, not a voicemail system, is in the call's transcript, so figs very "
                 "likely heard it. That is the transcript's evidence, not proof that the phone rang.",
                 "follow up in the room with the details the call could not carry."),
    "not-answered": ("the phone company or the voice provider reported no answer, busy or "
                     "canceled: figs did not pick up.",
                     "do not refile at once. @-mention figs in the room; if you still want figs "
                     "after the alarm's 10-minute cooldown, file one new request."),
    "outcome-unknown": ("the provider accepted the call, but nothing shows how it ended: "
                        "voicemail suspected, a silent call, or no result in time. It may have rung.",
                        "treat it as possibly heard. Say in the room that a call may have reached "
                        "figs. Do not refile at once; if figs has not come after the alarm's "
                        "10-minute cooldown and you still want figs, file one new request."),
    "uncertain": ("the call may or may not have been placed. The alarm never redials it.",
                  "treat it as possibly heard. Say in the room that a call may have reached figs. "
                  "Do not refile at once; if figs has not come after the alarm's 10-minute "
                  "cooldown and you still want figs, file one new request."),
    "failed": ("nothing was sent: the provider refused the call, or the alarm could not resolve "
               "the number to call or read its own copy of the request.",
               "figs was not called. Tell the room, which can look at the alarm; filing again "
               "will most likely fail the same way."),
    "dry-run": ("a dry run: the alarm processed the request and placed no call.",
                "nothing, if you asked for a dry run."),
    "duplicate": ("another issue holds this request_id, and that one is the request.",
                  "read the canonical issue instead."),
    "rejected": ("the alarm refused the request, and the worker's comment says why. Nothing was "
                 "sent.",
                 "fix what the comment names, then submit again with a new request id."),
    "closed-without-outcome": ("someone closed the request before the alarm recorded an outcome.",
                               "treat it as unknown: figs may or may not have been called."),
    "not-queued": ("the issue has no call-request label, so the alarm never sees it.",
                   "nothing will happen. File again from an account that can label issues there."),
    "accepted": ("the provider accepted the call. Accepted is not rang: the outcome follows, "
                 "usually within 3 minutes.",
                 "wait: run status again with --wait."),
    "in-flight": ("the alarm's worker holds the request and is placing the call.",
                  "wait: run status again with --wait."),
    "queued": ("filed and waiting for the alarm's worker, which runs on a wake and every 5 "
               "minutes.",
               "wait: run status again with --wait."),
}
LIVE_OFF = ("the alarm ran a live request as a dry run, which it does while its live switch is "
            "off, so figs was NOT called.",
            "reach figs another way, and tell the room that the alarm is not live.")
# Where the answers to a request's questions stand. The skill's answers table says the same.
ANSWERS = {
    "not-asked": ("no questions were asked.", "nothing."),
    "waiting": ("the call has not ended, so there are no answers yet.", "wait: run status again with --wait."),
    "pending": ("the call is over, but the voice provider's call analysis, which holds figs's answers, "
                "has not arrived. The alarm keeps checking for up to 24 hours.",
                "run status again later. Don't file again to ask the same questions."),
    "received": ("the alarm posted figs's answers on the issue, as the provider's speech recognition "
                 "heard them.",
                 "quote them as heard, and say so, when you act on them."),
    "unavailable": ("the provider's call analysis never arrived, so the alarm gave up on the answers.",
                    "ask figs in the room."),
    "none": ("no answers will come: the call ended without them, or there was no call.",
             "go by the outcome above, and ask figs in the room if you still need to know."),
}


class Stop(Exception):
    """End the command with an exit code and one message; `extra` goes into --json output."""

    def __init__(self, code: int, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def decode(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        return text


def http(method: str, url: str, token: str, body=None, accept="application/vnd.github+json"):
    """(status, data). status None is a transport error or timeout: a write may or may not have
    happened."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "authorization": f"Bearer {token}", "accept": accept,
        "x-github-api-version": "2022-11-28", "user-agent": "summon-human"})
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, decode(r.read())
    except urllib.error.HTTPError as e:
        return e.code, decode(e.read())
    except OSError as e:  # URLError, timeouts, resets
        return None, {"message": f"transport error ({type(e).__name__})"}


def message(data) -> str:
    text = data.get("message") if isinstance(data, dict) else data
    return re.sub(r"\s+", " ", str(text or ""))[:160]


def find_token() -> tuple[str, str]:
    for var in ("FROND_ALARM_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var, "").strip():
            return os.environ[var].strip(), var
    gh = shutil.which("gh")
    if gh:
        try:
            r = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            r = None
        if r is not None and r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip(), "gh auth token"
    raise Stop(REFUSED, "no GitHub token: set FROND_ALARM_TOKEN (or GH_TOKEN), or log in with gh")


class GitHub:
    def __init__(self, repo: str, token: str, transport=None):
        self.repo, self.token, self.transport = repo, token, transport or http

    def call(self, method: str, path: str, body=None, accept="application/vnd.github+json"):
        return self.transport(method, API + path, self.token, body, accept)

    def read(self, path: str, accept="application/vnd.github+json"):
        st, data = self.call("GET", path, accept=accept)
        if st != 200:
            raise Stop(GITHUB_ERROR, f"GitHub answered {st} to GET {path.split('?')[0]}: {message(data)}")
        return data

    def paged(self, path: str) -> list:
        """Every page, or an error: never a silently short list."""
        out = []
        for page in range(1, MAX_PAGES + 1):
            items = self.read(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            if not isinstance(items, list):
                raise Stop(GITHUB_ERROR, f"GitHub returned no list for {path.split('?')[0]}")
            out += items
            if len(items) < 100:
                return out
        raise Stop(GITHUB_ERROR, f"more than {MAX_PAGES * 100} items at {path.split('?')[0]}; "
                                 "refusing a partial view (look the request up by issue number)")

    def login(self) -> str:
        user = self.read("/user")
        if not isinstance(user, dict) or not user.get("login"):
            raise Stop(GITHUB_ERROR, "GitHub did not say who this token belongs to")
        return user["login"]

    def callers(self) -> dict:
        """The alarm's princes.json, as its validate.py reads it: GitHub login -> {"prince": the name a
        request's `from` must equal, "spoken": how the call announces it, "own_voice": whether it has a
        voice of its own}. A bare string entry, the older format, is both names."""
        data = self.read(f"/repos/{self.repo}/contents/princes.json", accept="application/vnd.github.raw+json")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = None
        if not isinstance(data, dict):
            raise Stop(GITHUB_ERROR, f"{self.repo}'s princes.json is not a JSON object")
        out = {}
        for login, entry in data.items():
            if isinstance(entry, str):
                entry = {"prince": entry}
            if login.startswith("_") or not isinstance(entry, dict) or not isinstance(entry.get("prince"), str) \
                    or not entry["prince"]:
                continue
            spoken = entry.get("spoken")
            out[login] = {"prince": entry["prince"], "spoken": spoken if isinstance(spoken, str) and spoken
                          else entry["prince"], "own_voice": bool(entry.get("voice_id"))}
        return out

    def can_label(self):
        """False only when the repository's `permissions` show neither triage nor more; None when they
        aren't shown. GitHub's API documents push access for labels on a new issue, so submit checks
        the label again after filing."""
        repo = self.read(f"/repos/{self.repo}")
        perms = repo.get("permissions") if isinstance(repo, dict) else None
        if not isinstance(perms, dict):
            return None
        return any(perms.get(k) for k in ("triage", "push", "maintain", "admin"))

    def requests(self, state: str) -> list:
        items = self.paged(f"/repos/{self.repo}/issues?labels={LABEL}&state={state}&sort=created&direction=asc")
        return [i for i in items if "pull_request" not in i]


def request_body(request_id: str, source: str, caller: str, text: str, line: str, dry_run: bool,
                 questions=()) -> str:
    """The issue body, byte for byte as the alarm's submit.sh writes it."""
    req = {"request_id": request_id, "source": source, "from": caller, "text": text, "line": line,
           "dry_run": dry_run}
    if questions:
        req["questions"] = list(questions)
    return MARKER + "\n```json\n" + json.dumps(req, sort_keys=True) + "\n```"


def body_request(body) -> dict | None:
    """The JSON object in an issue body (a ```json fence around it allowed), as the alarm reads it."""
    text = (body or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def spoken_problems(what: str, words: str, limit: int) -> list:
    """What the alarm would reject in words it speaks (the text, or a question), plus words with no
    letter or digit in them, which the alarm would speak as noise."""
    if not words.strip():
        return [f"{what} is blank"]
    out = []
    if len(words) > limit:
        out.append(f"{what} is {len(words)} characters; the limit is {limit}")
    if not SPEAKABLE.fullmatch(words):
        bad = "".join(sorted({c for c in words if not SPEAKABLE.fullmatch(c)}))
        out.append(f"{what} has characters the alarm will not speak: {bad!r} (use letters, digits, "
                   "spaces and . , ; : ! ? ' ( ) / - only)")
    elif not re.search(r"[A-Za-z0-9]", words):
        out.append(f"{what} has no words")
    return out


def problems(text: str, line: str, request_id: str, questions=()) -> list:
    """What the alarm would reject, checked before anything is filed."""
    out = spoken_problems("the text", text, MAX_TEXT)
    if len(questions) > MAX_QUESTIONS:
        out.append(f"--ask was given {len(questions)} times; the alarm takes at most {MAX_QUESTIONS} questions")
    for i, question in enumerate(questions, 1):
        out += spoken_problems(f"question {i}", question, MAX_QUESTION)
    if not LINE.fullmatch(line):
        out.append(f"--line {line!r} is not a three-digit line code")
    if not REQUEST_ID.fullmatch(request_id):
        out.append("--request-id must be 6 to 80 characters of letters, digits and . _ : -")
    return out


def names(labels) -> set:
    return {lb["name"] if isinstance(lb, dict) else str(lb) for lb in labels or []}


def first_line(text: str, limit: int = 300) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= limit else line[:limit] + "…"


def parse_time(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def ack_of(body: str):
    """The `acknowledged:` value in one of the worker's answers comments, or None."""
    m = ACK.search(body or "")
    return m.group(1) if m else None


def assess(issue: dict, comments: list, events: list | None, now: datetime, worker: str = WORKER) -> dict:
    """Where a request and the answers to its questions stand, from the labels and comments the
    alarm's worker wrote.

    Labels anyone else added and comments anyone else wrote are reported as warnings and never
    read as the outcome: anyone with access to the alarm's repository can comment there."""
    labels = names(issue.get("labels"))
    added_by = {}
    for e in events or []:
        if e.get("event") == "labeled":
            added_by[(e.get("label") or {}).get("name")] = (e.get("actor") or {}).get("login")
    warnings = []
    untrusted = set()
    if events is None:
        warnings.append("who added each label could not be checked")
    else:
        for lb in sorted(labels & WORKER_LABELS):
            if added_by.get(lb) != worker:
                untrusted.add(lb)
                warnings.append(f"label {lb} was added by {added_by.get(lb) or 'someone'}, not the alarm's "
                                "worker: ignored")
    trusted = labels - untrusted
    said = [c for c in comments if (c.get("user") or {}).get("login") == worker]
    for c in comments:
        if c in said:
            continue
        word = ((c.get("body") or "").split(None, 1) or [""])[0].rstrip(":").lower()
        who = (c.get("user") or {}).get("login") or "someone"
        kind = f"{'an' if word[:1] in 'aeiou' else 'a'} {word!r} comment by {who}"
        if word in ALARM_READS:
            warnings.append(f"{kind} is not from the alarm's worker. The alarm reads such comments from "
                            "anyone, so its outcome and any answers may be wrong; tell its maintainers")
        elif word in LOOKALIKES:
            warnings.append(f"{kind} is not from the alarm's worker: ignored")
    starts = lambda prefix: any((c.get("body") or "").startswith(prefix) for c in said)  # noqa: E731
    request = body_request(issue.get("body")) or {}
    outcome = next((lb for lb in OUTCOMES if lb in trusted), None)
    if outcome:
        state = outcome
    elif issue.get("state") == "closed":
        state = "closed-without-outcome"
    elif LABEL not in labels:
        state = "not-queued"
    elif "accepted" in trusted or starts("accepted:"):
        state = "accepted"
    elif "dialing" in trusted or starts("lease ") or starts("intent:"):
        state = "in-flight"
    else:
        state = "queued"
    live = bool(request) and request.get("dry_run", False) is False  # the alarm reads a missing dry_run as live
    meaning, step = LIVE_OFF if state == "dry-run" and live else STATES[state]
    asked = request.get("questions") if isinstance(request.get("questions"), list) else []
    replies = [c for c in said if (c.get("body") or "").startswith(ANSWER_PREFIXES)]
    settled = [c for c in replies if ack_of(c.get("body")) != "pending"]  # not the placeholders
    if not asked:
        answers = "not-asked"  # a settled comment then carries only the acknowledgement
    elif settled:
        answers = "received"
    elif "answers-unavailable" in trusted:
        answers = "unavailable"
    elif "answers-pending" in trusted and issue.get("state") == "open":  # the alarm reconciles open issues only
        answers = "pending"
    elif state in ("queued", "in-flight", "accepted"):
        answers = "waiting"
    else:
        answers = "none"
    if state == "queued" and issue.get("created_at"):
        waited = int((now - parse_time(issue["created_at"])).total_seconds() // 60)
        if waited >= QUEUED_HINT_MIN:
            meaning += (f" It has waited {waited} minutes: the alarm's cooldown or hourly cap is holding it, "
                        "or the worker is not running.")
    return {
        "issue": issue.get("number"), "url": issue.get("html_url"), "request_id": request.get("request_id"),
        "dry_run": request.get("dry_run"), "open": issue.get("state") == "open", "state": state,
        "terminal": state not in ("queued", "in-flight", "accepted") and answers != "pending",
        "meaning": meaning, "next": step, "labels": sorted(labels),
        "worker_said": [{"at": c.get("created_at"), "text": first_line(c.get("body"))}
                        for c in said if c not in replies],
        "questions": asked, "answers_state": answers, "answers_meaning": ANSWERS[answers][0],
        "answers_next": ANSWERS[answers][1], "answers": [c.get("body") for c in settled],
        "acknowledged": ack_of(settled[-1].get("body")) if settled else None,
        "other_comments": len(comments) - len(said), "warnings": warnings,
    }


def emit(a, data: dict, lines: list) -> None:
    if a.json:
        print(json.dumps(data, indent=1, sort_keys=True))
    else:
        print("\n".join(lines))


def this_script() -> str:
    return os.path.abspath(__file__)


def cmd_check(a, gh: GitHub) -> int:
    who = gh.login()
    caller = gh.callers().get(who)
    labels_ok = gh.can_label()
    ready = bool(caller) and labels_ok is not False
    data = {"repo": gh.repo, "token": a.token_source, "login": who, "caller": caller and caller["prince"],
            "announced_as": caller and caller["spoken"], "own_voice": caller and caller["own_voice"],
            "can_label": labels_ok, "ready": ready}
    voice = "in a voice of its own" if caller and caller["own_voice"] else "in the alarm's default voice"
    emit(a, data, [
        f"repo: {gh.repo}",
        f"token: from {a.token_source}",
        f"login: {who}",
        f"caller: {caller['prince']}, announced as {caller['spoken']}, {voice}" if caller else
        f"caller: none: {who} is not in {gh.repo}'s princes.json, so the alarm rejects its requests",
        {True: "labels: yes, the call-request label will stick",
         False: f"labels: no: {who} can't label issues in {gh.repo} (it needs write access there)",
         None: "labels: not shown for this token; submit checks the label after filing"}[labels_ok],
        f"ready: {'yes' if ready else 'no'}",
    ])
    return OK if ready else REFUSED


def cmd_submit(a, gh: GitHub) -> int:
    request_id = a.request_id or str(uuid.uuid4())
    questions = a.ask or []
    found = problems(a.text, a.line, request_id, questions)
    if found:
        raise Stop(REFUSED, "not filed: " + "; ".join(found))
    who = gh.login()
    caller = gh.callers().get(who)
    if not caller:
        raise Stop(REFUSED, f"not filed: {who} is not a caller in {gh.repo}'s princes.json, so the alarm would "
                            "reject the request")
    if gh.can_label() is False:
        raise Stop(REFUSED, f"not filed: {who} can't label issues in {gh.repo} (it needs write access there), "
                            f"so GitHub would drop the {LABEL} label and the alarm would never see the request")
    guard_pending = not a.dry_run and not a.allow_pending
    listing = gh.requests("all" if a.request_id else "open") if a.request_id or guard_pending else []
    if a.request_id:
        same = sorted(i["number"] for i in listing
                      if (body_request(i.get("body")) or {}).get("request_id") == request_id)
        if same:
            raise Stop(REFUSED, f"not filed: request_id {request_id} is already filed as #{same[0]}; read it with "
                                "status instead of filing again", issue=same[0])
    if guard_pending:
        mine = sorted(i["number"] for i in listing if i.get("state") == "open"
                      and (i.get("user") or {}).get("login") == who
                      and (body_request(i.get("body")) or {}).get("dry_run") is not True)
        if mine:
            raise Stop(REFUSED, f"not filed: you already have an open request, #{mine[0]}; read it with status, "
                                "or pass --allow-pending to file another", issue=mine[0])
    body = request_body(request_id, SOURCE, caller["prince"], a.text, a.line, a.dry_run, questions)
    st, issue = gh.call("POST", f"/repos/{gh.repo}/issues",
                        {"title": f"[call] {request_id}", "body": body, "labels": [LABEL]})
    number = issue.get("number") if isinstance(issue, dict) else None
    if st is None or st >= 500 or (st in (200, 201) and not isinstance(number, int)):
        raise Stop(UNKNOWN, f"unknown: GitHub did not confirm the issue ({st}: {message(issue)}). It may exist: run "
                            f"`status --request-id {request_id}` before anything else, and never file it again "
                            "under a new id", request_id=request_id)
    if st not in (200, 201):
        raise Stop(REFUSED, f"not filed: GitHub refused the issue ({st}: {message(issue)})")
    url = issue.get("html_url")
    if LABEL not in names(issue.get("labels")):
        note = (f"not queued: GitHub dropped the {LABEL} label, because the filing account can't label issues "
                "here, so the alarm will never see this request. Closed by summon-human.")
        cst, _ = gh.call("POST", f"/repos/{gh.repo}/issues/{number}/comments", {"body": note})
        pst, _ = gh.call("PATCH", f"/repos/{gh.repo}/issues/{number}", {"state": "closed"})
        closed = pst == 200
        raise Stop(NOT_QUEUED, f"not queued: GitHub filed #{number} but dropped the {LABEL} label, because {who} "
                               f"can't label issues in {gh.repo}. The alarm will never see it. "
                               + ("It is closed again." if closed else f"Close #{number} by hand."),
                   issue=number, url=url, request_id=request_id, closed=closed, commented=cst == 201)
    if a.no_wake:
        wake = "skipped"
    else:
        wst, wres = gh.call("POST", f"/repos/{gh.repo}/dispatches", {
            "event_type": "frond-call", "client_payload": {"issue_number": str(number), "request_id": request_id}})
        wake = "sent" if wst == 204 else f"not sent ({wst}: {message(wres)})"
    follow = f"python3 {this_script()} status {number} --wait 540"
    emit(a, {"result": "queued", "issue": number, "url": url, "request_id": request_id,
             "dry_run": a.dry_run, "questions": len(questions), "wake": wake, "next": follow}, [
        f"queued: {url} (request_id {request_id}{', dry run' if a.dry_run else ''})",
        *([f"questions: {len(questions)}; figs's answers come back on the issue, and status shows them"]
          if questions else []),
        f"wake: {wake}" + ("" if wake == "sent" else "; the alarm's 5-minute schedule picks the request up"),
        f"next: {follow}",
    ])
    return OK


def locate(a, gh: GitHub) -> int:
    if a.issue is not None:
        return a.issue
    same = sorted(i["number"] for i in gh.requests("all")
                  if (body_request(i.get("body")) or {}).get("request_id") == a.request_id)
    if not same:
        raise Stop(GITHUB_ERROR, f"no request with request_id {a.request_id} in {gh.repo}")
    return same[0]  # the alarm's rule: the lowest issue number holding a request_id is the request


def read_request(gh: GitHub, number: int, now: datetime) -> dict:
    issue = gh.read(f"/repos/{gh.repo}/issues/{number}")
    if not isinstance(issue, dict) or "pull_request" in issue:
        raise Stop(GITHUB_ERROR, f"#{number} in {gh.repo} is not an issue")
    comments = gh.paged(f"/repos/{gh.repo}/issues/{number}/comments")
    try:
        events = gh.paged(f"/repos/{gh.repo}/issues/{number}/events")
    except Stop:
        events = None
    return assess(issue, comments, events, now)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cmd_status(a, gh: GitHub) -> int:
    number = locate(a, gh)
    deadline = time.monotonic() + max(0, a.wait)
    view = read_request(gh, number, utcnow())
    while not view["terminal"] and time.monotonic() < deadline:
        time.sleep(max(0.0, min(POLL_SECONDS, deadline - time.monotonic())))
        view = read_request(gh, number, utcnow())
    lines = [f"#{view['issue']} {view['request_id'] or '(no request_id)'}: {view['state']}"
             f"{'' if view['terminal'] else ' (still pending)'}",
             f"meaning: {view['meaning']}", f"next: {view['next']}"]
    if view["questions"]:
        lines.append(f"answers: {view['answers_state']}: {view['answers_meaning']} Next: {view['answers_next']}")
    if view["acknowledged"]:
        lines.append(f"acknowledged: {view['acknowledged']} (the voice provider's reading of the call)")
    if view["worker_said"]:
        lines.append("the alarm's worker said:")
        lines += [f"  {c['at']} {c['text']}" for c in view["worker_said"]]
    if view["answers"]:
        lines.append("what the alarm heard from figs:")
        lines += ["  " + line for line in view["answers"][-1].splitlines()]
    if view["other_comments"]:
        lines.append(f"{view['other_comments']} other comment(s), not from the worker, not shown")
    lines += [f"warning: {w}" for w in view["warnings"]]
    if view["url"]:
        lines.append(f"url: {view['url']}")
    emit(a, view, lines)
    return OK if view["terminal"] else PENDING


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="summon.py", description="Ask frond-alarm to phone figs, and read what happened.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=os.environ.get("FROND_ALARM_REPO") or DEFAULT_REPO,
                        help="the alarm's repository, OWNER/NAME (default %(default)s)")
    common.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", parents=[common], help="who you are to the alarm; files nothing")
    s = sub.add_parser("submit", parents=[common], help="file one request (the alarm then phones figs)")
    s.add_argument("text", help=f"what the call says after announcing you; at most {MAX_TEXT} characters")
    s.add_argument("--ask", action="append", metavar="QUESTION",
                   help=f"a question for figs, asked on the call: up to {MAX_QUESTIONS}, each at most {MAX_QUESTION} "
                        "characters. The answers come back on the issue")
    s.add_argument("--line", default=DEFAULT_LINE, help="the alarm's line code (default: the alarm's default line)")
    s.add_argument("--dry-run", action="store_true", help="the alarm processes it fully and places no call")
    s.add_argument("--request-id", help="your own id, 6-80 of A-Za-z0-9._:- (default: a new UUID)")
    s.add_argument("--no-wake", action="store_true", help="skip the wake; the alarm's 5-minute schedule picks it up")
    s.add_argument("--allow-pending", action="store_true",
                   help="file even though you have an open request that is not a dry run")
    t = sub.add_parser("status", parents=[common], help="where a request stands")
    t.add_argument("issue", nargs="?", type=int, help="the request's issue number")
    t.add_argument("--request-id", help="find the request by its request_id instead")
    t.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                   help="poll every 30 s until the request reaches an outcome, and its answers if it asked "
                        "questions, or SECONDS pass")
    return p


def main(argv=None, transport=None) -> int:
    p = parser()
    a = p.parse_args(argv)
    if a.cmd == "status" and (a.issue is None) == (a.request_id is None):
        p.error("status takes either an issue number or --request-id")
    try:
        if not REPO.fullmatch(a.repo):
            raise Stop(REFUSED, f"--repo {a.repo!r} is not OWNER/NAME")
        token, a.token_source = find_token()
        gh = GitHub(a.repo, token, transport)
        return {"check": cmd_check, "submit": cmd_submit, "status": cmd_status}[a.cmd](a, gh)
    except Stop as e:
        if a.json:
            print(json.dumps({"result": "error", "exit": e.code, "message": e.message, **e.extra},
                             indent=1, sort_keys=True))
        else:
            print(e.message, file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
