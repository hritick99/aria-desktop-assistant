"""Gmail plugin. See plugins/README.md for setup."""
import os, base64, email
PLUGIN_NAME="gmail"; PLUGIN_DESCRIPTION="Gmail — read, draft, send emails"
TOOL_TAG_PATTERN=r'\[GMAIL:([^\]]+)\]'
TOOL_DESCRIPTION="""
[GMAIL: unread]                         → List unread emails
[GMAIL: inbox]                          → List inbox
[GMAIL: read | message_id_prefix]       → Read full email
[GMAIL: draft | to | subject | body]    → Create draft
[GMAIL: send | to | subject | body]     → Send email
"""
CONFIG_DIR=os.path.join(os.path.expanduser("~"),".desktop_assistant")
CREDS_FILE=os.path.join(CONFIG_DIR,"credentials.json"); TOKEN_FILE=os.path.join(CONFIG_DIR,"gmail_token.json")
SCOPES=["https://www.googleapis.com/auth/gmail.readonly","https://www.googleapis.com/auth/gmail.compose"]

def _svc():
    from google.oauth2.credentials import Credentials; from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow; from googleapiclient.discovery import build
    creds=None
    if os.path.exists(TOKEN_FILE): creds=Credentials.from_authorized_user_file(TOKEN_FILE,SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE): raise RuntimeError(f"credentials.json missing at {CREDS_FILE}")
            creds=InstalledAppFlow.from_client_secrets_file(CREDS_FILE,SCOPES).run_local_server(port=0)
        with open(TOKEN_FILE,"w") as f: f.write(creds.to_json())
    return build("gmail","v1",credentials=creds)

def execute(arg):
    parts=[p.strip() for p in arg.split("|")]; cmd=parts[0].lower()
    try: svc=_svc()
    except Exception as e: return str(e)
    if cmd in ("unread","inbox"):
        q="is:unread" if cmd=="unread" else "in:inbox"
        res=svc.users().messages().list(userId="me",q=q,maxResults=10).execute()
        msgs=res.get("messages",[])
        if not msgs: return "No messages."
        lines=[f"📧 {cmd.title()} ({len(msgs)}):"]
        for m in msgs:
            hdr=svc.users().messages().get(userId="me",id=m["id"],format="metadata",
                metadataHeaders=["From","Subject","Date"]).execute()
            h={x["name"]:x["value"] for x in hdr["payload"]["headers"]}
            lines.append(f"  [{m['id'][:8]}] {h.get('Date','')[:16]} — {h.get('From','')[:35]}: {h.get('Subject','')[:50]}")
        return "\n".join(lines)
    elif cmd=="read" and len(parts)>1:
        res=svc.users().messages().list(userId="me",maxResults=20).execute()
        fid=parts[1]
        for m in res.get("messages",[]): 
            if m["id"].startswith(parts[1]): fid=m["id"]; break
        msg=svc.users().messages().get(userId="me",id=fid,format="full").execute()
        h={x["name"]:x["value"] for x in msg["payload"]["headers"]}
        body=_body(msg["payload"])
        return f"From: {h.get('From')}\nDate: {h.get('Date')}\nSubject: {h.get('Subject')}\n\n{body[:2000]}"
    elif cmd in ("draft","send") and len(parts)>=4:
        msg=email.message.EmailMessage(); msg["To"]=parts[1]; msg["Subject"]=parts[2]; msg.set_content(parts[3])
        raw=base64.urlsafe_b64encode(msg.as_bytes()).decode()
        if cmd=="draft":
            d=svc.users().drafts().create(userId="me",body={"message":{"raw":raw}}).execute()
            return f"✅ Draft created (ID:{d['id'][:12]})"
        else:
            svc.users().messages().send(userId="me",body={"raw":raw}).execute()
            return f"✅ Email sent to {parts[1]}"
    return "Unknown Gmail command."

def _body(payload):
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8",errors="replace")
    for part in payload.get("parts",[]):
        if part.get("mimeType")=="text/plain" and part["body"].get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8",errors="replace")
    return "(no body)"
def on_load(): pass
