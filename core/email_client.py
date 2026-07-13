"""
Email reader over IMAP — read and filter your inbox with almost no setup.

Uses Python's built-in imaplib (no extra dependencies) and a Gmail App
Password (or any IMAP account). For Gmail we use the X-GM-RAW extension so
you get Gmail's full search syntax for filtering:
    from:boss is:unread, subject:invoice after:2026/01/01, has:attachment …

Read-only: the mailbox is opened in readonly mode, so nothing can be
deleted or marked. Configure in Settings → Email.
"""

import email
import imaplib
import re
import smtplib
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

import config as cfg
from core.logger import get_logger

log = get_logger("email")


def configured() -> bool:
    return bool((cfg.get("email_address") or "").strip() and
                (cfg.get("email_app_password") or "").strip())


def _conn():
    host = (cfg.get("email_imap_host") or "imap.gmail.com").strip()
    addr = (cfg.get("email_address") or "").strip()
    pw = (cfg.get("email_app_password") or "").strip()
    if not addr or not pw:
        raise RuntimeError("Email isn't set up — add your address and app "
                           "password in Settings → Email.")
    M = imaplib.IMAP4_SSL(host)
    M.login(addr, pw)
    return M


def _dec(raw) -> str:
    if raw is None:
        return ""
    out = []
    for part, enc in decode_header(raw):
        if isinstance(part, bytes):
            try:
                out.append(part.decode(enc or "utf-8", errors="replace"))
            except Exception:
                out.append(part.decode("utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out)


def _is_gmail() -> bool:
    return "gmail" in (cfg.get("email_imap_host") or "imap.gmail.com").lower()


def _search(M, query=None, unread=False):
    if query:
        if _is_gmail():
            typ, data = M.search(None, "X-GM-RAW", f'"{query}"')
        else:
            typ, data = M.search(None, "TEXT", f'"{query}"')
    elif unread:
        typ, data = M.search(None, "UNSEEN")
    else:
        typ, data = M.search(None, "ALL")
    if typ != "OK":
        return []
    return data[0].split()


def list_messages(query=None, unread=False, limit=10) -> str:
    try:
        M = _conn()
    except Exception as e:
        return str(e)
    try:
        M.select("INBOX", readonly=True)
        ids = _search(M, query=query, unread=unread)
        if not ids:
            return "No matching emails."
        ids = ids[-limit:][::-1]
        header = ("🔍 Filter: " + query) if query else ("📧 Unread" if unread else "📧 Inbox")
        lines = [f"{header} ({len(ids)}):"]
        for i in ids:
            typ, d = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not d or not d[0]:
                continue
            msg = email.message_from_bytes(d[0][1])
            frm = _dec(msg.get("From", ""))[:38]
            subj = _dec(msg.get("Subject", "(no subject)"))[:52]
            date = _dec(msg.get("Date", ""))[:16]
            num = i.decode() if isinstance(i, bytes) else str(i)
            lines.append(f"  [{num}] {date} — {frm}: {subj}")
        lines.append("\n(Use [EMAIL: read | <number>] to open one.)")
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"Email list: {e}")
        return f"Email error: {e}"
    finally:
        try: M.logout()
        except Exception: pass


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
                    "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
        return "(no plain-text body)"
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return str(msg.get_payload())[:2000]


def read_message(num: str) -> str:
    try:
        M = _conn()
    except Exception as e:
        return str(e)
    try:
        M.select("INBOX", readonly=True)
        num = re.sub(r"\D", "", str(num))
        if not num:
            return "Give the message number from the list."
        typ, d = M.fetch(num.encode(), "(BODY.PEEK[])")
        if typ != "OK" or not d or not d[0]:
            return f"Couldn't fetch message {num}."
        msg = email.message_from_bytes(d[0][1])
        body = _body(msg)
        return (f"From: {_dec(msg.get('From'))}\n"
                f"Date: {_dec(msg.get('Date'))}\n"
                f"Subject: {_dec(msg.get('Subject'))}\n\n{body[:2500]}")
    except Exception as e:
        return f"Email error: {e}"
    finally:
        try: M.logout()
        except Exception: pass


def send_email(to: str, subject: str, body: str) -> str:
    addr = (cfg.get("email_address") or "").strip()
    pw = (cfg.get("email_app_password") or "").strip()
    host = (cfg.get("email_smtp_host") or "smtp.gmail.com").strip()
    if not addr or not pw:
        return "Email isn't set up — add your address and app password in Settings."
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, 587, timeout=30) as s:
            s.starttls()
            s.login(addr, pw)
            s.send_message(msg)
        log.info(f"Email sent to {to}")
        return f"✅ Email sent to {to}"
    except Exception as e:
        return f"Send failed: {e}"


def handle(arg: str) -> str:
    parts = [p.strip() for p in (arg or "").split("|")]
    cmd = parts[0].lower() if parts and parts[0] else "unread"
    if cmd in ("unread", "new"):
        return list_messages(unread=True)
    if cmd in ("inbox", "recent", "list"):
        return list_messages()
    if cmd in ("search", "filter", "find") and len(parts) > 1:
        return list_messages(query=parts[1])
    if cmd == "read" and len(parts) > 1:
        return read_message(parts[1])
    if cmd in ("send", "draft"):
        # split carefully so the body may contain '|'
        seg = [p.strip() for p in (arg or "").split("|", 3)]
        if len(seg) < 4:
            return "To send: [EMAIL: send | to@addr | subject | body]"
        _, to, subject, body = seg
        if cmd == "draft":
            return (f"Draft (not sent):\nTo: {to}\nSubject: {subject}\n\n{body}")
        # Park for explicit confirmation before actually sending.
        from core import confirm
        confirm.set_pending("email", (to, subject, body),
                            f"send email to {to}")
        return (f"⚠️ CONFIRM — send this email?\nTo: {to}\nSubject: {subject}\n\n"
                f"{body[:500]}\n\nReply 'yes' to send or 'no' to cancel.")
    return ("EMAIL usage: [EMAIL: unread] · [EMAIL: inbox] · "
            "[EMAIL: search | from:boss is:unread] · [EMAIL: read | <number>] · "
            "[EMAIL: send | to | subject | body]")


def test_connection() -> tuple:
    try:
        M = _conn()
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "ALL")
        n = len(data[0].split()) if typ == "OK" else 0
        M.logout()
        return True, f"✓ Connected — {n} messages in inbox"
    except imaplib.IMAP4.error as e:
        return False, f"✗ Login failed — check address & app password ({str(e)[:60]})"
    except Exception as e:
        return False, f"✗ {str(e)[:80]}"
