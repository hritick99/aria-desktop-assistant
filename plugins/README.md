# Plugins

Drop a `.py` file here → Aria loads it on next start.

## Plugin contract
```python
PLUGIN_NAME        = "my_plugin"
PLUGIN_DESCRIPTION = "What it does"
TOOL_TAG_PATTERN   = r'\[MYPLUGIN:([^\]]+)\]'
TOOL_DESCRIPTION   = "[MYPLUGIN: arg]  → Description"
def execute(arg: str) -> str: ...
def on_load(): pass    # optional
def on_unload(): pass  # optional
```

## Google setup (Calendar + Gmail)
1. https://console.cloud.google.com → New project
2. Enable: Google Calendar API, Gmail API
3. OAuth 2.0 Desktop credentials → download as `credentials.json`
4. Place at `~/.desktop_assistant/credentials.json`

## GitHub setup
Add to `~/.desktop_assistant/config.json`:
```json
{ "github_token": "ghp_...", "github_username": "hritick99" }
```
Get token: https://github.com/settings/tokens (scopes: repo, read:user, notifications)
