"""GitHub plugin. Add github_token and github_username to config.json."""
import requests as req
PLUGIN_NAME="github"; PLUGIN_DESCRIPTION="GitHub — PRs, issues, commits, notifications"
TOOL_TAG_PATTERN=r'\[GITHUB:([^\]]+)\]'
TOOL_DESCRIPTION="""
[GITHUB: prs]                               → Your open PRs
[GITHUB: issues | owner/repo]               → Open issues
[GITHUB: commits | owner/repo]              → Latest commits
[GITHUB: notifications]                     → Notifications
[GITHUB: create issue | owner/repo | title | body]  → Create issue
[GITHUB: repos]                             → Your repos
[GITHUB: profile]                           → Your profile
"""
import config as cfg

def _h(): 
    t=cfg.get("github_token")
    if not t: raise RuntimeError("Set github_token in ~/.desktop_assistant/config.json")
    return {"Authorization":f"token {t}","Accept":"application/vnd.github.v3+json"}

def _get(url,params=None):
    r=req.get(url,headers=_h(),params=params,timeout=15); r.raise_for_status(); return r.json()

def execute(arg):
    parts=[p.strip() for p in arg.split("|")]; cmd=parts[0].lower()
    try:
        if cmd=="prs":
            u=cfg.get("github_username") or ""
            q=f"type:pr state:open author:{u}" if u else "type:pr state:open"
            d=_get("https://api.github.com/search/issues",{"q":q,"per_page":10})
            items=d.get("items",[])
            if not items: return "No open PRs."
            return "🔀 Open PRs:\n"+"\n".join(f"  #{i['number']} {i['title'][:60]}\n  {i['html_url']}" for i in items)
        elif cmd=="issues" and len(parts)>1:
            d=_get(f"https://api.github.com/repos/{parts[1]}/issues",{"state":"open","per_page":15})
            return f"🐛 Issues in {parts[1]}:\n"+"\n".join(f"  #{i['number']} {i['title'][:60]}" for i in d if "pull_request" not in i)
        elif cmd=="commits" and len(parts)>1:
            d=_get(f"https://api.github.com/repos/{parts[1]}/commits",{"per_page":10})
            return f"📝 Commits in {parts[1]}:\n"+"\n".join(f"  [{c['sha'][:7]}] {c['commit']['message'].split(chr(10))[0][:60]}" for c in d)
        elif cmd=="notifications":
            d=_get("https://api.github.com/notifications",{"per_page":15})
            if not d: return "No notifications."
            return "🔔 Notifications:\n"+"\n".join(f"  [{n['reason']}] {n['repository']['full_name']}: {n['subject']['title'][:50]}" for n in d)
        elif cmd=="create issue" and len(parts)>=3:
            body_text=parts[3] if len(parts)>3 else ""
            r=req.post(f"https://api.github.com/repos/{parts[1]}/issues",headers=_h(),
                json={"title":parts[2],"body":body_text},timeout=15); r.raise_for_status()
            i=r.json(); return f"✅ Issue #{i['number']}: {parts[2]}\n{i['html_url']}"
        elif cmd=="repos":
            d=_get("https://api.github.com/user/repos",{"sort":"updated","per_page":15})
            return "📦 Repos:\n"+"\n".join(f"  {r['full_name']} [{r.get('language') or ''}] ⭐{r.get('stargazers_count',0)}" for r in d)
        elif cmd=="profile":
            u=cfg.get("github_username") or ""
            d=_get(f"https://api.github.com/users/{u}" if u else "https://api.github.com/user")
            return f"👤 @{d['login']}\n  Repos: {d.get('public_repos',0)}  Followers: {d.get('followers',0)}\n  Bio: {d.get('bio') or 'N/A'}"
        return "Unknown GitHub command."
    except RuntimeError as e: return str(e)
    except req.HTTPError as e: return f"GitHub API error: {e.response.status_code}"
    except Exception as e: return f"GitHub error: {e}"
def on_load(): pass
