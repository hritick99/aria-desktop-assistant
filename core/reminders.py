"""Persistent scheduled reminders via APScheduler."""
import re, sqlite3
from datetime import datetime, date, timedelta
from typing import Callable, List, Optional
from core.logger import get_logger
from config import DB_PATH
log = get_logger("reminders")

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    SCHED_OK = True
except ImportError:
    SCHED_OK = False; log.warning("apscheduler not installed")

_REMINDER_RE = re.compile(
    r'\[\s*REMINDER:\s*([0-9]{1,2}:[0-9]{2}\s*(?:[ap]\.?m\.?)?)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\]', re.I)

def _conn():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def get_all_reminders():
    with _conn() as c: return c.execute("SELECT * FROM reminders WHERE active=1 ORDER BY remind_at").fetchall()

def save_reminder(title, remind_at, recurrence="once", days=""):
    with _conn() as c:
        # dedupe: same time + recurrence + title already active → reuse it
        row = c.execute(
            "SELECT id FROM reminders WHERE active=1 AND remind_at=? AND recurrence=? "
            "AND lower(title)=lower(?)", (remind_at, recurrence, title)).fetchone()
        if row: return row["id"]
        cur = c.execute("INSERT INTO reminders(title,remind_at,recurrence,days) VALUES(?,?,?,?)",
                        (title,remind_at,recurrence,days)); return cur.lastrowid

def delete_reminder(rid):
    with _conn() as c: c.execute("UPDATE reminders SET active=0 WHERE id=?", (rid,))

def _ensure_status_column():
    """Migration: reminders.status = '' | 'fired' | 'done'."""
    with _conn() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(reminders)")]
        if "status" not in cols:
            c.execute("ALTER TABLE reminders ADD COLUMN status TEXT DEFAULT ''")

def set_status(rid, status):
    with _conn() as c:
        c.execute("UPDATE reminders SET status=? WHERE id=?", (status, rid))

_MISSED_PREFIX = re.compile(r'^\(missed at [0-9:]+\)\s*', re.I)

def strip_missed(title: str) -> str:
    return _MISSED_PREFIX.sub("", title or "").strip()

def mark_done_by_title(title):
    """Flag the most recent reminder with this title as done.
    One-time reminders are closed; recurring ones stay scheduled."""
    clean = strip_missed(title)
    with _conn() as c:
        row = c.execute("SELECT id, recurrence FROM reminders WHERE lower(title)=lower(?) "
                        "ORDER BY id DESC LIMIT 1", (clean,)).fetchone()
        if not row:
            return False
        if row["recurrence"] == "once":
            c.execute("UPDATE reminders SET status='done', active=0 WHERE id=?", (row["id"],))
        else:
            c.execute("UPDATE reminders SET status='done' WHERE id=?", (row["id"],))
        return True

def parse_reminder_tag(text):
    m = _REMINDER_RE.search(text)
    if not m: return None
    time_str, recurrence, title = m.group(1).strip(), m.group(2).lower(), m.group(3).strip()
    title = re.sub(r'^\s*title\s*:\s*', '', title, flags=re.I).strip()
    if recurrence not in ("once", "daily", "weekdays"): recurrence = "once"
    try:
        clean = time_str.upper().replace(" ", "").replace(".", "")
        if "AM" in clean or "PM" in clean:
            t = datetime.strptime(clean, "%I:%M%p")
        else: t = datetime.strptime(clean, "%H:%M")
        hhmm = t.strftime("%H:%M")
    except: hhmm = time_str
    return {"title": title, "remind_at": hhmm, "recurrence": recurrence}

def find_by_title(title):
    """Fuzzy-match an ACTIVE reminder by title (exact, then substring)."""
    t = strip_missed(title).lower()
    with _conn() as c:
        rows = c.execute("SELECT * FROM reminders WHERE active=1 ORDER BY id DESC").fetchall()
    for r in rows:
        if r["title"].lower() == t: return r
    for r in rows:
        if t in r["title"].lower() or r["title"].lower() in t: return r
    return None


def manage(arg: str, engine=None) -> str:
    """Chat-facing reminder management: [REMINDERS: list/done/delete/snooze | title | mins]."""
    parts = [p.strip() for p in (arg or "").split("|")]
    action = parts[0].lower() if parts and parts[0] else "list"
    if action in ("list", "show", "all"):
        rows = get_all_reminders()
        if not rows: return "No active reminders."
        return "Active reminders:\n" + "\n".join(
            f"- {r['remind_at']} ({r['recurrence']}): {r['title']}" for r in rows)
    title = parts[1] if len(parts) > 1 else ""
    if not title:
        return f"'{action}' needs a title: [REMINDERS: {action} | <title>]"
    row = find_by_title(title)
    if action in ("done", "complete", "completed", "finish"):
        if row:
            if row["recurrence"] == "once":
                set_status(row["id"], "done")
                if engine: engine.remove(row["id"])
                else: delete_reminder(row["id"])
            else:
                set_status(row["id"], "done")
            return f"✓ Marked done: {row['title']}"
        if mark_done_by_title(title):
            return f"✓ Marked done: {strip_missed(title)}"
        return f"No reminder matching '{title}'."
    if action in ("delete", "remove", "cancel"):
        if not row: return f"No active reminder matching '{title}'."
        if engine: engine.remove(row["id"])
        else: delete_reminder(row["id"])
        return f"Deleted reminder: {row['title']}"
    if action == "snooze":
        mins = 10
        if len(parts) > 2:
            digits = re.sub(r'\D', '', parts[2])
            if digits: mins = max(1, int(digits))
        name = row["title"] if row else strip_missed(title)
        if engine:
            engine.snooze(name, mins)
        else:
            t = (datetime.now() + timedelta(minutes=mins)).strftime("%H:%M")
            save_reminder(name, t, "once")
        return f"'{name}' snoozed — will fire again in {mins} min"
    return f"Unknown reminders action '{action}' — use list / done / delete / snooze."


class ReminderEngine:
    def __init__(self, on_reminder: Callable):
        self.on_reminder = on_reminder
        self._sched = None
        if not SCHED_OK: return
        self._sched = BackgroundScheduler(daemon=True)
        self._sched.start()
        _ensure_status_column()
        for row in get_all_reminders(): self._schedule(dict(row))
        log.info("Reminder engine started")

    def _schedule(self, row):
        if not self._sched: return
        try:
            h, m = map(int, row["remind_at"].split(":"))
            jid  = f"reminder_{row['id']}"
            rec  = row["recurrence"]
            if rec == "once":
                now = datetime.now()
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target <= now:
                    if self._was_meant_today(row, target):
                        # PC was off / Aria not running when it was due —
                        # deliver it late instead of silently deferring a day.
                        log.info(f"Missed reminder '{row['title']}' — delivering now")
                        self._sched.add_job(
                            self._fire, DateTrigger(run_date=now + timedelta(seconds=8)),
                            id=jid, replace_existing=True,
                            args=[row["id"], f"(missed at {row['remind_at']}) {row['title']}", False])
                        return
                    target += timedelta(days=1)
                self._sched.add_job(self._fire, DateTrigger(run_date=target),
                                    id=jid, replace_existing=True, args=[row["id"],row["title"],False])
            elif rec == "daily":
                self._sched.add_job(self._fire, CronTrigger(hour=h,minute=m),
                                    id=jid, replace_existing=True, args=[row["id"],row["title"],True])
            elif rec == "weekdays":
                self._sched.add_job(self._fire, CronTrigger(day_of_week="mon-fri",hour=h,minute=m),
                                    id=jid, replace_existing=True, args=[row["id"],row["title"],True])
        except Exception as e: log.error(f"Schedule error: {e}")

    def _was_meant_today(self, row, target) -> bool:
        """True if the reminder was created BEFORE its time today — i.e. the
        user meant today and we missed it (app wasn't running)."""
        try:
            import calendar
            created_utc = datetime.strptime(str(row.get("created_at", "")),
                                            "%Y-%m-%d %H:%M:%S")
            created_local = datetime.fromtimestamp(calendar.timegm(created_utc.timetuple()))
            return created_local <= target
        except Exception:
            return False

    def _fire(self, rid, title, recurring):
        if not recurring:
            # completed/deleted since scheduling → don't fire
            try:
                with _conn() as c:
                    row = c.execute("SELECT active FROM reminders WHERE id=?", (rid,)).fetchone()
                if row and not row["active"]:
                    return
            except Exception:
                pass
        self.on_reminder(title)
        try:
            from core import notify
            notify.push("⏰ Reminder", title, priority="high")
        except Exception as e:
            log.warning(f"Phone push: {e}")
        if not recurring:
            delete_reminder(rid)
            try: set_status(rid, "fired")
            except Exception: pass

    def snooze(self, title, minutes: int = 10):
        """Re-deliver this reminder in N minutes (persisted, survives restart)."""
        clean = strip_missed(title)
        t = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
        return self.add(clean, t, "once")

    def add(self, title, remind_at, recurrence="once"):
        rid = save_reminder(title, remind_at, recurrence)
        self._schedule({"id":rid,"title":title,"remind_at":remind_at,"recurrence":recurrence})
        return rid

    def remove(self, rid):
        delete_reminder(rid)
        if self._sched:
            try: self._sched.remove_job(f"reminder_{rid}")
            except: pass

    def shutdown(self):
        if self._sched: self._sched.shutdown(wait=False)
