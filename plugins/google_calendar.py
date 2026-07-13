"""Google Calendar plugin. See plugins/README.md for setup."""
import os
from datetime import datetime, timedelta, timezone

PLUGIN_NAME        = "google_calendar"
PLUGIN_DESCRIPTION = "Google Calendar — view and create events"
TOOL_TAG_PATTERN   = r'\[CALENDAR:([^\]]+)\]'
TOOL_DESCRIPTION   = """
[CALENDAR: list today]   → Today's events
[CALENDAR: list week]    → This week's events
[CALENDAR: list tomorrow] → Tomorrow's events
[CALENDAR: add | title | YYYY-MM-DD HH:MM | duration_mins]  → Create event
"""
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".desktop_assistant")
CREDS_FILE = os.path.join(CONFIG_DIR, "credentials.json")
TOKEN_FILE = os.path.join(CONFIG_DIR, "calendar_token.json")
SCOPES     = ["https://www.googleapis.com/auth/calendar"]

def _svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    creds = None
    if os.path.exists(TOKEN_FILE): creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE): raise RuntimeError(f"credentials.json not found at {CREDS_FILE}")
            creds = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES).run_local_server(port=0)
        with open(TOKEN_FILE,"w") as f: f.write(creds.to_json())
    return build("calendar","v3",credentials=creds)

def execute(arg):
    parts = [p.strip() for p in arg.split("|")]; cmd = parts[0].lower()
    try: svc = _svc()
    except Exception as e: return str(e)
    now = datetime.now(timezone.utc)
    def _list(start,end,label):
        res = svc.events().list(calendarId="primary",timeMin=start,timeMax=end,
                                singleEvents=True,orderBy="startTime").execute()
        evts = res.get("items",[])
        if not evts: return f"{label}: No events."
        lines = [f"📅 {label}:"]
        for e in evts:
            t = e["start"].get("dateTime",e["start"].get("date",""))
            if "T" in t: t = datetime.fromisoformat(t).strftime("%H:%M")
            lines.append(f"  • {t} — {e.get('summary','Untitled')}")
        return "\n".join(lines)
    if "today" in cmd or (cmd=="list" and len(parts)==1):
        return _list(now.replace(hour=0,minute=0,second=0).isoformat(),now.replace(hour=23,minute=59,second=59).isoformat(),"Today")
    elif "week" in cmd:
        return _list(now.isoformat(),(now+timedelta(days=7)).isoformat(),"This week")
    elif "tomorrow" in cmd:
        t=(now+timedelta(days=1)); return _list(t.replace(hour=0,minute=0,second=0).isoformat(),t.replace(hour=23,minute=59,second=59).isoformat(),"Tomorrow")
    elif cmd=="add" and len(parts)>=3:
        try: start_dt=datetime.strptime(parts[2].strip(),"%Y-%m-%d %H:%M")
        except: return "Invalid datetime. Use: YYYY-MM-DD HH:MM"
        dur=int(parts[3]) if len(parts)>3 else 60
        event={"summary":parts[1],"start":{"dateTime":start_dt.strftime("%Y-%m-%dT%H:%M:00"),"timeZone":"Asia/Kolkata"},
               "end":{"dateTime":(start_dt+timedelta(minutes=dur)).strftime("%Y-%m-%dT%H:%M:00"),"timeZone":"Asia/Kolkata"}}
        c=svc.events().insert(calendarId="primary",body=event).execute()
        return f"✅ Created: '{parts[1]}' on {parts[2]} ({dur}min)\n{c.get('htmlLink','')}"
    return "Unknown calendar command."
def on_load(): pass
