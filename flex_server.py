#!/usr/bin/env python3
"""
Cookie-only Flex sniper for a VPS / SSH box. No Chrome, no captcha, no password.

  python3 flex_server.py 23L-0700 --cookie cookie.txt --new dl -p 3

If the session dies it mails SESSION expired and exits. Paste a new cookie and start again.
"""

from __future__ import annotations

import argparse
import html as htmlmod
import json
import random
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import config as _cfg
except ImportError:
    _cfg = None

BASE = "https://flexstudent.nu.edu.pk"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
LOG_FILE = ROOT / "flex_server.log"
EXIT_SESSION = 2

ROLL = ""
WATCH = []
WATCH_EXPLICIT = []
NEW_SHORTS = []
WANT_NEW = False
COOKIE_ARG = ""
SECTION = "BCS-7A"
INTERVAL = 4.0
MAIL_TO = ""
ACCOUNT_NAME = ""
ACCOUNT_MAIL = ""
LAST_ERROR_MAIL = {}
HOLD_SEEN_AT = 0.0
LAST_HOLD_MAIL = 0.0
HOLD_MAIL_EVERY = 3600.0
STARTED_AT = 0.0
LAST_HEALTH_MAIL = 0.0
LAST_COURSES = []
LAST_POLL_STATUS = "starting"
CODE_MAP = {}
SEEN_REGISTERED = set()
POLL_N = 0
REG_ATTEMPT_N = 0
LAST_TOKEN_DUMP = ""
SID = ""

DEFAULT_WATCH = ["dl", "ds", "se", "bi"]
DEFAULT_MAIL = "l230625@lhr.nu.edu.pk"
DEFAULT_POLL = 4.0
KNOWN_ELECTIVE_CODES = {
    "CS4112",
    "CS4118",
    "CS4032",
    "CS4048",
    "CS4063",
    "CS4085",
}


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def mail_cfg():
    return {
        "to": MAIL_TO or (getattr(_cfg, "MAIL_TO", "") if _cfg else ""),
        "frm": (getattr(_cfg, "MAIL_FROM", "") if _cfg else "")
        or "Flex sniper <beth.t@example.com>",
        "key": getattr(_cfg, "RESEND_API_KEY", "") if _cfg else "",
    }


def notify(subject: str, body: str, blocking: bool = False) -> None:
    cfg = mail_cfg()
    if not cfg["to"] or not cfg["key"]:
        log(f"MAIL skip (to={cfg['to']!r} key={'set' if cfg['key'] else 'missing'})  {subject}")
        return
    if blocking:
        _notify_send(subject, body, cfg)
        return
    threading.Thread(
        target=_notify_send, args=(subject, body, cfg), daemon=True, name="flex-mail"
    ).start()


def _notify_send(subject: str, body: str, cfg: dict) -> None:
    payload = json.dumps(
        {"from": cfg["frm"], "to": [cfg["to"]], "subject": subject, "text": body}
    ).encode()
    headers = {
        "Authorization": "Bearer " + cfg["key"],
        "Content-Type": "application/json",
        "User-Agent": UA,
        "Accept": "application/json",
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
        log(f"MAIL sent → {cfg['to']}  {subject}  {raw[:120]}")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace") if e.fp else str(e)
        log(f"MAIL fail HTTP {e.code}: {err[:400]}")
    except Exception as e:
        log(f"MAIL fail: {e}")


def alert(title: str, details: str, blocking: bool = False) -> None:
    dest = mail_cfg()["to"] or "(mail not set)"
    who = ACCOUNT_NAME or "(name not scraped yet)"
    body = (
        f"Time: {ts()}\n"
        f"Account: {ROLL}\n"
        f"Name: {who}\n"
        f"Account mail: {ACCOUNT_MAIL or '-'}\n"
        f"Alert mail: {dest}\n"
        f"Watch: {', '.join(WATCH) if WATCH else '-'}\n"
        f"Section: {SECTION}\n"
        f"Mode: cookie-only (no Chrome, no captcha)\n"
        f"\n{details.strip()}\n"
    )
    notify(f"Flex | {title} | {ROLL}", body, blocking=blocking)


def alert_error_once(key: str, title: str, details: str, cooldown: float = 90.0) -> None:
    now = time.time()
    if now - LAST_ERROR_MAIL.get(key, 0) < cooldown:
        return
    LAST_ERROR_MAIL[key] = now
    alert(title, details)


def die_session(why: str) -> None:
    log(f"SESSION expired — {why}")
    try:
        alert(
            "SESSION expired",
            "Cookie is dead. This server script does NOT log in.\n"
            "SSH in, put a fresh ASP.NET_SessionId in the cookie file, start again.\n\n"
            f"Reason: {why}\n\n"
            f"{run_snapshot()}\n\n"
            f"{first_block_mail()}",
            blocking=True,
        )
    except Exception:
        pass
    sys.exit(EXIT_SESSION)


def scrape_profile(html: str) -> None:
    global ACCOUNT_NAME, ACCOUNT_MAIL
    m = re.search(
        r'm-topbar__username[\s\S]{0,200}?<span[^>]*>\s*([^<]+)', html or "", re.I
    )
    if m:
        ACCOUNT_NAME = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"Name:\s*</span>\s*<span>\s*([^<]+)", html or "", re.I)
    if m:
        ACCOUNT_NAME = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"Email:\s*</span>\s*<span>\s*([^<]+)", html or "", re.I)
    if m:
        ACCOUNT_MAIL = m.group(1).strip()


def course_label(c: dict) -> str:
    name = (c.get("name") or c.get("label") or "").strip()
    short = c.get("short") or ""
    cid = c.get("course_id") or ""
    bits = [name or short or cid]
    if short:
        bits.append(f"({short})")
    if cid:
        bits.append(f"courseidtd={cid}")
    return " ".join(bits)


def uptime_str() -> str:
    if STARTED_AT <= 0:
        return "just started"
    elapsed = max(0.0, time.time() - STARTED_AT)
    h = int(elapsed // 3600)
    m = int((elapsed % 3600) // 60)
    s = int(elapsed % 60)
    return f"{h}h {m}m {s}s"


def run_snapshot() -> str:
    return "\n".join(
        [
            "Mode: cookie-only VPS (no Chrome / captcha)",
            f"Watch list you typed: {', '.join(WATCH_EXPLICIT) or '(none)'}",
            (
                "--new: YES. Unknown first-section electives registered FIRST, then your list."
                if WANT_NEW
                else "--new: no"
            ),
            f"New courses seen this run: {', '.join(NEW_SHORTS) or '(none yet)'}",
            f"Register order: {', '.join(WATCH) or '(waiting)'}",
            f"Preferred section: {SECTION} (else first open section)",
            f"Poll every: {INTERVAL:g}s",
            f"Polls: {POLL_N}   register attempts: {REG_ATTEMPT_N}",
            f"Uptime: {uptime_str()}",
            f"Last poll status: {LAST_POLL_STATUS}",
            f"Cookie file: {cookie_path().name}",
        ]
    )


def course_card(c: dict) -> str:
    if not c:
        return "  (course not on page)"
    opts = c.get("options") or []
    opt_s = ", ".join(lab for _, lab in opts) or "(none — usually FULL)"
    if c.get("registered"):
        state = "REGISTERED"
    elif c.get("full") or not (c.get("token") or c.get("options")):
        state = "FULL / no seats"
    else:
        state = "SEATS OPEN"
    tok = (c.get("token") or "")[:18]
    tok = (tok + "…") if c.get("token") else "(no checkbox)"
    return (
        f"  {c.get('code') or '?'}  {c.get('name') or '?'}\n"
        f"    short={c.get('short') or '-'}  courseidtd={c.get('course_id') or '-'}\n"
        f"    state={state}  zone={c.get('zone')}\n"
        f"    open sections: {opt_s}\n"
        f"    checkbox: {tok}"
    )


def first_block_mail(courses: list | None = None) -> str:
    courses = LAST_COURSES if courses is None else courses
    above = [c for c in (courses or []) if c.get("zone") == "first"]
    if not above:
        return "First block (above Improvement): not scraped yet."
    lines = ["First block (above Improvement — only this is sniped):"]
    for c in above:
        lines.append(course_card(c))
    return "\n".join(lines)


def maybe_hourly_drop_reminder(courses: list[dict]) -> None:
    """Hourly DROP mail only if a first-section elective is already registered.

    Core/4-course loads must not trigger this — only a held elective that can
    block registering another watched elective.
    """
    global HOLD_SEEN_AT, LAST_HOLD_MAIL
    holding = [
        c for c in courses if c.get("registered") and is_safe_elective(c)
    ]
    by_short = {c["short"]: c for c in courses if c.get("short")}
    waiting = []
    for short in WATCH:
        c = by_short.get(short)
        if not c or not c.get("registered"):
            waiting.append(short)
    if not holding or not waiting:
        HOLD_SEEN_AT = 0.0
        LAST_HOLD_MAIL = 0.0
        return
    now = time.time()
    if HOLD_SEEN_AT <= 0:
        HOLD_SEEN_AT = now
        return
    if LAST_HOLD_MAIL and now - LAST_HOLD_MAIL < HOLD_MAIL_EVERY:
        return
    if not LAST_HOLD_MAIL and now - HOLD_SEEN_AT < HOLD_MAIL_EVERY:
        return
    LAST_HOLD_MAIL = now
    holding_lines = "\n".join(f"  - {course_label(c)}" for c in holding)
    wait_lines = "\n".join(
        f"  - {course_label(by_short[s]) if s in by_short else s}" for s in waiting
    )
    hours = int((now - HOLD_SEEN_AT) // 3600) or 1
    log(f"HOLD REMINDER #{hours}h — drop to free a slot")
    alert(
        "DROP to enroll",
        "An elective is already enrolled; Flex may block another register.\n\n"
        f"Holding elective(s):\n{holding_lines}\n\nStill waiting:\n{wait_lines}\n\n"
        f"{run_snapshot()}\n\n{first_block_mail(courses)}",
        blocking=True,
    )


def maybe_hourly_health() -> None:
    global LAST_HEALTH_MAIL, STARTED_AT
    now = time.time()
    if STARTED_AT <= 0:
        STARTED_AT = now
    first = LAST_HEALTH_MAIL == 0
    since = now - LAST_HEALTH_MAIL if LAST_HEALTH_MAIL else 0
    if not first and since < HOLD_MAIL_EVERY:
        return
    LAST_HEALTH_MAIL = now
    elapsed = now - STARTED_AT
    hours = int(elapsed // 3600)
    mins = int((elapsed % 3600) // 60)
    by_short = {c["short"]: c for c in LAST_COURSES if c.get("short")}
    lines = []
    for short in WATCH:
        c = by_short.get(short)
        if not c:
            lines.append(f"  - {short}: not on registration page yet")
            continue
        if c.get("registered"):
            state = "REGISTERED"
        elif c.get("full") or not (c.get("token") or c.get("options")):
            state = "FULL (waiting for a seat)"
        else:
            state = "SEATS open"
        lines.append(f"  - {course_label(c)}: {state}")
    looking = "\n".join(lines) if lines else "  - " + ", ".join(WATCH)
    extra_new = ""
    if WANT_NEW and not NEW_SHORTS:
        extra_new = "\nStill waiting for a NEW first-section elective (not DL/DS/SE/WP).\n"
    log(f"HEALTH {'start' if first else str(hours)+'h'} — {','.join(WATCH) or 'NEW'}")
    alert(
        "STARTED health" if first else "HEALTH running",
        f"Cookie-only sniper is running.{extra_new}\nLooking for:\n{looking}\n\n"
        f"Uptime: {hours}h {mins}m\n\n{run_snapshot()}\n\n{first_block_mail()}",
        blocking=True,
    )


def cookie_path() -> Path:
    if COOKIE_ARG:
        p = Path(COOKIE_ARG).expanduser()
        if p.is_file() or ("/" in COOKIE_ARG or "\\" in COOKIE_ARG):
            return p.resolve() if p.exists() else p
    return ROOT / f"cookie_{ROLL.replace('-', '')}.txt"


def load_cookie() -> str:
    if COOKIE_ARG:
        p = Path(COOKIE_ARG).expanduser()
        if p.is_file():
            return p.read_text().strip().split()[0] if p.read_text().strip() else ""
        if "/" not in COOKIE_ARG and "\\" not in COOKIE_ARG:
            return COOKIE_ARG.strip()
    p = cookie_path()
    if not p.exists():
        return ""
    text = p.read_text().strip()
    return text.split()[0] if text else ""


def http(url: str, sid: str | None = None, data: bytes | None = None, referer: str | None = None):
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if sid:
        headers["Cookie"] = f"ASP.NET_SessionId={sid}"
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["X-Requested-With"] = "XMLHttpRequest"
    if referer:
        headers["Referer"] = referer
        headers["Origin"] = BASE
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data is not None else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return e.code, e.headers.get("Location") or url, body


def looks_logged_in(html: str, url: str) -> bool:
    if "/Login" in (url or ""):
        return False
    if re.search(r'name=["\']password["\']', html, re.I):
        return False
    if "Object moved" in html and "/Login" in html:
        return False
    return True


def session_alive(sid: str) -> bool:
    if not sid:
        return False
    code, url, html = http(BASE + "/", sid)
    if not (code == 200 and looks_logged_in(html, url)):
        return False
    if ROLL and ROLL not in html:
        return False
    scrape_profile(html)
    return True


def dump_from(s: str) -> str:
    m = re.search(r"CourseRegistration(?:BS)?\?dump=([^\"'&\s]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"[?&]dump=([^\"'&\s]+)", s)
    return m.group(1) if m else ""


def get_reg_page(sid: str) -> tuple[str, str]:
    _, url, home = http(BASE + "/", sid)
    dump = dump_from(url) or dump_from(home)
    q = f"?dump={dump}" if dump else ""
    _, url, html = http(BASE + "/Student/CourseRegistrationBS" + q, sid)
    return url, html


def course_shorthand(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name or "")
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:2].lower()
    return (words[0][0] + words[1][0]).lower()


def _scrape_rows(html: str, zone: str) -> list[dict]:
    courses = []
    for m in re.finditer(
        r'<tr[^>]*?(?:title="([^"]*)")?[^>]*>(.*?)</tr>', html or "", re.I | re.S
    ):
        title = htmlmod.unescape(m.group(1) or "")
        chunk = m.group(2)
        code_m = re.search(
            r'name="CourseId"[^>]*courseidtd="(\d+)"[^>]*>\s*([^<]+)'
            r'|courseidtd="(\d+)"[^>]*>\s*([^<]+)',
            chunk,
            re.I | re.S,
        )
        if not code_m:
            continue
        course_id = (code_m.group(1) or code_m.group(3) or "").strip()
        label = htmlmod.unescape(
            re.sub(r"\s+", " ", (code_m.group(2) or code_m.group(4) or ""))
        ).strip()
        if not course_id:
            continue
        split = re.match(r"^([A-Z]{2,}\d+)\s*[-–]\s*(.+)$", label)
        catalog = split.group(1).upper() if split else ""
        name = split.group(2).strip() if split else (label or title)
        short = course_shorthand(name)
        registered = "Not Registered" not in chunk and re.search(r"Registered", chunk)
        full = bool(re.search(r"No Seats Available|Sections Full", chunk, re.I))
        box = re.search(
            r'class="RegisterChkbox"[^>]*value="([^"]+)"|'
            r'value="([^"]+)"[^>]*class="RegisterChkbox"',
            chunk,
        )
        token = (box.group(1) or box.group(2) or "") if box else ""
        opts = [
            (oid, htmlmod.unescape(lab).strip())
            for oid, lab in re.findall(
                r'<option[^>]*id="([^"]+)"[^>]*>([^<]*)</option>', chunk, re.I
            )
        ]
        elective = bool(re.search(r">\s*Elective\s*<", chunk, re.I))
        core = bool(re.search(r">\s*Core\s*<", chunk, re.I))
        improvement = zone == "improvement" or bool(
            re.search(r"Improvement Course", chunk, re.I)
        )
        sel = re.search(
            r'<select[^>]*courseid="(\d+)"[^>]*class="[^"]*section',
            chunk,
            re.I,
        )
        if sel and not course_id:
            course_id = sel.group(1)
        courses.append(
            {
                "course_id": course_id,
                "code": catalog,
                "label": label,
                "name": name,
                "short": short,
                "registered": bool(registered),
                "full": full,
                "token": token,
                "options": opts,
                "elective": elective,
                "core": core,
                "zone": zone,
                "improvement": improvement,
            }
        )
    return courses


def split_improvement(page: str) -> tuple[str, str]:
    m = re.search(r"Improv(?:e)?ment\s+Courses", page or "", re.I)
    if not m:
        return page or "", ""
    return page[: m.start()], page[m.start() :]


def scrape_courses(page: str) -> list[dict]:
    first, rest = split_improvement(page)
    return _scrape_rows(first, "first") + _scrape_rows(rest, "improvement")


def is_safe_elective(c: dict) -> bool:
    if not c or c.get("zone") != "first":
        return False
    if c.get("improvement") or c.get("core") or not c.get("elective"):
        return False
    return True


def is_new_elective(c: dict) -> bool:
    if not is_safe_elective(c):
        return False
    code = (c.get("code") or "").upper()
    if code and code in KNOWN_ELECTIVE_CODES:
        return False
    if not code and c.get("short") in ("dl", "ds", "se", "wp", "nl", "ml"):
        return False
    return True


def is_watched(c: dict) -> bool:
    if not is_safe_elective(c):
        return False
    if WANT_NEW and is_new_elective(c):
        return True
    if c.get("short") and c["short"] in WATCH_EXPLICIT:
        return True
    return False


def rebuild_watch() -> None:
    global WATCH
    seen = []
    for s in NEW_SHORTS + WATCH_EXPLICIT:
        if s and s not in seen:
            seen.append(s)
    WATCH = seen


def absorb_new_electives(courses: list[dict]) -> None:
    global NEW_SHORTS
    if not WANT_NEW:
        return
    found = [c for c in courses if is_new_elective(c)]
    shorts = []
    for c in found:
        s = c.get("short") or c.get("code") or c.get("course_id")
        if s and s not in shorts:
            shorts.append(s)
    if shorts == NEW_SHORTS:
        rebuild_watch()
        return
    added = [s for s in shorts if s not in NEW_SHORTS]
    NEW_SHORTS = shorts
    rebuild_watch()
    if not added:
        return
    cards = []
    for c in found:
        tag = c.get("short") or c.get("code") or c.get("course_id")
        if tag in added:
            cards.append(course_card(c))
    log("NEW ELECTIVE(S) in first section:\n" + "\n".join(cards))
    seats = [
        c
        for c in found
        if (c.get("short") or c.get("code") or c.get("course_id")) in added
        and not c.get("full")
        and (c.get("token") or c.get("options"))
        and not c.get("registered")
    ]
    seat_note = (
        "At least one NEW course has seats — registered FIRST this poll."
        if seats
        else "NEW course(s) on the page but FULL. Will register when a seat opens."
    )
    alert(
        "NEW elective",
        "New first-section elective(s) (not core, not Improvement, not DL/DS/SE/WP).\n"
        "These are watched FIRST, then your typed list.\n\n"
        f"{seat_note}\n\n" + "\n".join(cards) + f"\n\n{run_snapshot()}\n\n{first_block_mail()}",
        blocking=True,
    )


def pick_token(course: dict) -> tuple[str, str]:
    cid = course["course_id"]
    suffix = "_" + cid
    if SECTION:
        for oid, label in course["options"]:
            if SECTION.upper() in label.upper() and oid.endswith(suffix):
                return oid, label
        for oid, label in course["options"]:
            if SECTION.upper() in label.upper():
                tok = oid if oid.endswith(suffix) else (oid + suffix if "_" not in oid else oid)
                return tok, label
    if course["token"] and course["token"].endswith(suffix):
        lab = course["options"][0][1] if course["options"] else SECTION
        return course["token"], lab
    for oid, label in course["options"]:
        if oid.endswith(suffix):
            return oid, label
    if course["token"]:
        lab = course["options"][0][1] if course["options"] else SECTION
        return course["token"], lab
    if course["options"]:
        return course["options"][0]
    return "", ""


def post_register(sid: str, dump: str, token: str, section: str) -> tuple[bool, bool]:
    body = urllib.parse.urlencode({"RegisterChkbox": token, "section": section}).encode()
    ref = BASE + "/Student/CourseRegistrationBS?dump=" + (dump or "")
    code, url, html = http(BASE + "/Student/RegisterCoursesBS", sid, data=body, referer=ref)
    logged_out = "/Login" in url or ("Object moved" in html and "/Login" in html)
    return (not logged_out) and code in (200, 302), logged_out


def refresh_code_map(courses: list[dict]) -> None:
    global CODE_MAP
    new = {c["short"]: c["course_id"] for c in courses if c["short"] in WATCH}
    if new != CODE_MAP and new:
        CODE_MAP = new
        parts = [f"{s}→{CODE_MAP[s]}" for s in WATCH if s in CODE_MAP]
        missing = [s for s in WATCH if s not in CODE_MAP]
        msg = "COURSE IDS (courseidtd) " + " ".join(parts)
        if missing:
            msg += "  (not on page yet: " + ",".join(missing) + ")"
        log(msg)


def log_elective_tokens(courses: list[dict]) -> None:
    global LAST_TOKEN_DUMP
    above = [c for c in courses if c.get("zone") == "first"]
    below = [c for c in courses if c.get("zone") != "first"]
    lines = ["  -- ABOVE Improvement (sniped) --"]
    for c in above:
        opts = c.get("options") or []
        opt_s = " | ".join(f"{lab}={oid}" for oid, lab in opts) if opts else "(no section options)"
        state = "REGISTERED" if c.get("registered") else ("FULL" if c.get("full") else "SEATS")
        lines.append(
            f"  {c['short'] or '?':<4} {c.get('label') or c.get('name')}  "
            f"courseidtd={c['course_id']}  {state}\n"
            f"       options={opt_s}"
        )
    lines.append("  -- BELOW Improvement (ignored) --")
    if not below:
        lines.append("  (none)")
    for c in below:
        lines.append(f"  SKIP {c.get('code') or '?'} {c.get('name')}  courseidtd={c.get('course_id')}")
    blob = "\n".join(lines)
    if blob == LAST_TOKEN_DUMP:
        return
    LAST_TOKEN_DUMP = blob
    log("ELECTIVE TOKENS\n" + blob)


def run() -> None:
    global POLL_N, REG_ATTEMPT_N, STARTED_AT, LAST_COURSES, LAST_POLL_STATUS, SID
    STARTED_AT = time.time()
    LAST_POLL_STATUS = "starting"
    SID = load_cookie()
    if not SID:
        die_session("no cookie — pass --cookie file or put cookie_<roll>.txt here")
    if not session_alive(SID):
        die_session("cookie not valid for this roll (Flex bounced or wrong account)")
    log(f"COOKIE ok {SID[:12]}…  file={cookie_path().name}")
    watch_msg = ",".join(WATCH) if WATCH else "(no extra shorts)"
    prio = "  +NEW first" if WANT_NEW else ""
    log(f"WATCH {watch_msg}{prio}  section={SECTION}  POLL={INTERVAL:g}s")
    log(f"MAIL Resend → {mail_cfg()['to']}" if mail_cfg()["key"] else "MAIL off")
    alert(
        "STARTED",
        "Cookie-only sniper started on this server.\n"
        "No Chrome. If the cookie dies you get SESSION expired mail and this process stops.\n\n"
        f"Cookie: {SID[:12]}…  file={cookie_path().name}\n\n"
        f"{run_snapshot()}",
        blocking=True,
    )

    while True:
        POLL_N += 1
        maybe_hourly_health()
        try:
            url, page = get_reg_page(SID)
            scrape_profile(page)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            LAST_POLL_STATUS = f"fetch error: {e}"
            log(f"POLL #{POLL_N} fetch error: {e}")
            alert_error_once(
                "poll_fetch",
                "ERROR poll fetch",
                f"{e}\n\n{traceback.format_exc()[-1500:]}",
            )
            time.sleep(INTERVAL)
            continue
        if not looks_logged_in(page, url):
            die_session("registration page bounced to /Login")

        if re.search(r"Offering not complete", page, re.I):
            LAST_POLL_STATUS = "offering not complete"
            log(f"POLL #{POLL_N} offering not complete — retry in {INTERVAL:g}s")
            time.sleep(INTERVAL)
            continue

        try:
            courses = scrape_courses(page)
            LAST_COURSES = courses
            LAST_POLL_STATUS = "ok"
            refresh_code_map(courses)
            log_elective_tokens(courses)
            absorb_new_electives(courses)
            maybe_hourly_drop_reminder(courses)

            targets = [c for c in courses if is_watched(c)]
            targets.sort(key=lambda c: (0 if is_new_elective(c) else 1, c.get("short") or ""))
            if not targets:
                if WANT_NEW and not NEW_SHORTS and not WATCH_EXPLICIT:
                    log(f"POLL #{POLL_N} NEW=waiting — retry in {INTERVAL:g}s")
                else:
                    log(f"POLL #{POLL_N} no watched first-section electives")
                time.sleep(INTERVAL + random.uniform(0, 0.4))
                continue

            dump = dump_from(url) or dump_from(page)
            holding = []
            seat_bits = []
            for c in targets:
                if c["registered"]:
                    holding.append(f"{c['short']}({c['course_id']})")
                    seat_bits.append(f"{c['short']}=REGISTERED({c['course_id']})")
                elif c["full"] or not (c["token"] or c["options"]):
                    seat_bits.append(f"{c['short']}=FULL({c['course_id']})")
                else:
                    secs = ",".join(lab for _, lab in c["options"]) or "open"
                    seat_bits.append(f"{c['short']}=SEATS({c['course_id']}:{secs})")

            now_unreg = {c["course_id"] for c in targets if not c["registered"]}
            for cid in sorted(SEEN_REGISTERED & now_unreg):
                short = next((c["short"] for c in targets if c["course_id"] == cid), cid)
                cdrop = next((x for x in targets if x["course_id"] == cid), None)
                log(f"DROPPED {short} courseidtd={cid}")
                alert(
                    "DROPPED",
                    "Watched/new course is no longer registered. Will register again if seats.\n\n"
                    f"{course_card(cdrop) if cdrop else f'  short={short}  courseidtd={cid}'}\n\n"
                    f"{run_snapshot()}\n\n{first_block_mail()}",
                    blocking=True,
                )
                SEEN_REGISTERED.discard(cid)

            new_bit = ""
            if WANT_NEW:
                new_bit = f"NEW={','.join(NEW_SHORTS)}  " if NEW_SHORTS else "NEW=waiting  "
            hold_msg = "  HOLDING " + ", ".join(holding) if holding else ""
            log(f"POLL #{POLL_N}  {new_bit}" + "  ".join(seat_bits) + hold_msg)

            for c in targets:
                key = c["course_id"]
                if c.get("zone") != "first" or c.get("improvement"):
                    log(
                        f"REGISTER BLOCKED below Improvement line: "
                        f"{c.get('code')} {c.get('name')}"
                    )
                    continue
                if not is_safe_elective(c):
                    log(
                        f"REGISTER BLOCKED {c.get('code')} {c.get('short')} "
                        f"zone={c.get('zone')} core={c.get('core')} "
                        f"(never register Improvement/core)"
                    )
                    continue
                if c["registered"]:
                    SEEN_REGISTERED.add(key)
                    continue
                if c["full"] or not (c["token"] or c["options"]):
                    continue
                token, sec = pick_token(c)
                if not token or not token.endswith("_" + key):
                    log(f"REGISTER skip {c['short']} courseidtd={key} (bad token)")
                    continue
                REG_ATTEMPT_N += 1
                log(
                    f"REGISTER attempt #{REG_ATTEMPT_N}  {c['short']}  "
                    f"courseidtd={key}  section={sec or SECTION}"
                )
                ok, logged_out = post_register(SID, dump, token, sec or SECTION)
                if logged_out:
                    die_session("register POST bounced to /Login")
                if ok:
                    SEEN_REGISTERED.add(key)
                    log(f"REGISTER ok #{REG_ATTEMPT_N} {c['short']} {c['name']}")
                    why = (
                        "NEW (unknown first-section — first)"
                        if is_new_elective(c)
                        else "your watch list"
                    )
                    alert(
                        "REGISTERED",
                        f"Register POST succeeded.\n\nWhy: {why}\n"
                        f"Attempt: #{REG_ATTEMPT_N}\nSection: {sec or SECTION}\n\n"
                        f"{course_card(c)}\n\n{run_snapshot()}\n\n{first_block_mail()}",
                        blocking=True,
                    )
                else:
                    log(f"REGISTER fail #{REG_ATTEMPT_N} {c['short']}")
                    alert_error_once(
                        f"regfail_{key}",
                        "ERROR register failed",
                        f"Attempt #{REG_ATTEMPT_N}\nSection: {sec or SECTION}\n\n"
                        f"{course_card(c)}\n\n{run_snapshot()}",
                    )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            LAST_POLL_STATUS = f"poll error: {e}"
            log(f"POLL #{POLL_N} error: {e}")
            alert_error_once("poll_body", "ERROR poll", f"{e}\n\n{traceback.format_exc()[-1500:]}")

        time.sleep(INTERVAL + random.uniform(0, 0.4))


def main() -> None:
    global ROLL, WATCH, WATCH_EXPLICIT, SECTION, INTERVAL, MAIL_TO, WANT_NEW, COOKIE_ARG
    ap = argparse.ArgumentParser(
        description="Cookie-only Flex sniper. No Chrome. Mail on session expire."
    )
    ap.add_argument("roll", help="23L-0700")
    ap.add_argument("shorthands", nargs="*", help="dl ds se  (with --new: extra shorts)")
    ap.add_argument("--cookie", default="", help="cookie file or raw ASP.NET_SessionId")
    ap.add_argument("--new", action="store_true", help="watch unknown first-section electives first")
    ap.add_argument("--section", default="BCS-7A")
    ap.add_argument("-p", "--poll", dest="poll", type=float, default=DEFAULT_POLL)
    ap.add_argument("-m", "--mail", default="")
    # allow: ... --cookie file --new dl -p 3  (dl after flags)
    args = ap.parse_intermixed_args()
    ROLL = args.roll.strip()
    WANT_NEW = bool(args.new)
    COOKIE_ARG = (args.cookie or "").strip()
    typed = [s.strip().lower() for s in (args.shorthands or [])]
    if WANT_NEW:
        WATCH_EXPLICIT = typed
        WATCH = list(typed)
    else:
        WATCH_EXPLICIT = typed or list(DEFAULT_WATCH)
        WATCH = list(WATCH_EXPLICIT)
    SECTION = args.section
    INTERVAL = max(1.0, args.poll)
    MAIL_TO = args.mail.strip() or (getattr(_cfg, "MAIL_TO", "") if _cfg else "") or DEFAULT_MAIL
    try:
        run()
    except KeyboardInterrupt:
        log("stopped")
    except SystemExit:
        raise
    except Exception as e:
        log(f"CRASH: {e}")
        alert("ERROR crash", f"{e}\n\n{traceback.format_exc()[-2000:]}\n\n{run_snapshot()}", blocking=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
