"""
LLM provider layer — unified streaming interface over multiple backends.

    Ollama  — local, private, slower (default fallback, and vision via llava)
    Groq    — ultra-fast LPU cloud inference (used for everyday speed)
    Claude  — Anthropic, strongest (reserved for genuinely hard queries)

The rest of Aria only calls `complete(...)`. Provider selection is automatic
(config `llm_backend`), respecting which API keys are present, and always
degrades to local Ollama on any error so the assistant never hard-fails.
"""

import json
import time

import requests

import config as cfg
from core.logger import get_logger

log = get_logger("llm")

OLLAMA, GROQ, CLAUDE = "ollama", "groq", "claude"
CLAUDE_CODE = "claude_code"   # Claude Pro subscription via the Claude Code CLI

# Providers that recently failed sit out for a while so every message
# doesn't pay the timeout/429 penalty. name -> unix ts when usable again.
_cooldown = {}


def _healthy(provider: str) -> bool:
    return _cooldown.get(provider, 0.0) <= time.time()


def _mark_down(provider: str, seconds: float):
    _cooldown[provider] = time.time() + seconds
    log.info(f"Provider '{provider}' on cooldown for {int(seconds)}s")


def _has(key: str) -> bool:
    v = cfg.get(key)
    return bool(v and str(v).strip())


def has_groq() -> bool:
    return _has("groq_api_key")


def has_claude() -> bool:
    return _has("claude_api_key")


def custom_providers() -> list:
    """User-added OpenAI-compatible providers: {name, base_url, api_key, model}."""
    out = []
    for p in cfg.get("custom_llms") or []:
        if p.get("name") and p.get("base_url") and str(p.get("api_key", "")).strip():
            out.append(p)
    return out


def _custom_by_name(name: str):
    for p in custom_providers():
        if p["name"].lower() == name.lower():
            return p
    return None


def select_provider(hard: bool, has_image: bool) -> str:
    """Decide which backend handles this call."""
    if has_image:
        return OLLAMA  # local vision (llava); cloud image handling differs
    backend = (cfg.get("llm_backend") or "auto").lower()
    if backend == CLAUDE_CODE:
        return CLAUDE_CODE
    if backend == GROQ:
        return GROQ if has_groq() else OLLAMA
    if backend == CLAUDE:
        return CLAUDE if has_claude() else OLLAMA
    if backend == OLLAMA:
        return OLLAMA
    if backend != "auto":                       # a custom provider by name
        return backend if _custom_by_name(backend) else OLLAMA
    # auto
    if hard and has_claude():
        return CLAUDE
    if has_groq():
        return GROQ
    custom = custom_providers()
    if custom:
        return custom[0]["name"].lower()
    if has_claude():
        return CLAUDE
    return OLLAMA


def _model_for(provider: str, fallback: str = None) -> str:
    if provider == GROQ:
        return cfg.get("groq_model") or "llama-3.3-70b-versatile"
    if provider == CLAUDE:
        return cfg.get("claude_model") or "claude-sonnet-4-6"
    custom = _custom_by_name(provider)
    if custom:
        return custom.get("model") or fallback or cfg.get("ollama_model")
    return fallback or cfg.get("ollama_model")


def active_provider_label(hard: bool = False) -> str:
    """Human-readable name of the provider that would handle a normal call."""
    p = select_provider(hard, has_image=False)
    labels = {OLLAMA: "Ollama (local)", GROQ: "Groq", CLAUDE: "Claude",
              CLAUDE_CODE: "Claude Pro (subscription)"}
    if p in labels:
        return labels[p]
    custom = _custom_by_name(p)
    return custom["name"] if custom else "Ollama (local)"


def _provider_chain(hard: bool, has_image: bool) -> list:
    """Failover order: preferred provider first, then every other configured
    cloud provider, always ending with local Ollama."""
    if has_image:
        return [OLLAMA]
    chain = [select_provider(hard, has_image)]
    candidates = ([GROQ] if has_groq() else [])
    candidates += [c["name"].lower() for c in custom_providers()]
    candidates += ([CLAUDE] if has_claude() else [])
    for p in candidates:
        if p not in chain:
            chain.append(p)
    # skip providers on cooldown (Ollama is always kept as the last resort)
    chain = [p for p in chain if p != OLLAMA and _healthy(p)]
    chain.append(OLLAMA)
    return chain


def _call_one(provider, system, messages, on_token, model, image_b64, temperature) -> str:
    use_model = _model_for(provider, fallback=model)
    # Any image must go to a vision-capable model, whatever the text router chose.
    if image_b64 and provider == OLLAMA:
        use_model = cfg.get("model_vision") or use_model
    if provider == CLAUDE_CODE:
        from core.claude_code_integration import complete_text
        return complete_text(system, messages, on_token)
    if provider == GROQ:
        return _openai_compat(system, messages, on_token, use_model, temperature,
                              cfg.get("groq_base_url") or "https://api.groq.com/openai/v1",
                              cfg.get("groq_api_key"))
    if provider == CLAUDE:
        return _claude(system, messages, on_token, use_model, temperature)
    custom = _custom_by_name(provider)
    if custom:
        return _openai_compat(system, messages, on_token, use_model, temperature,
                              custom["base_url"], custom["api_key"])
    return _ollama(system, messages, on_token, use_model, image_b64, temperature)


def complete(system, messages, on_token=None, model=None, image_b64=None,
             temperature=0.7, hard=False, provider=None) -> str:
    """Run a chat completion, streaming tokens via on_token if provided.
    Fails over through every configured provider before reaching Ollama."""
    chain = [provider] if provider else _provider_chain(hard, image_b64 is not None)
    if OLLAMA not in chain:
        chain.append(OLLAMA)
    last_err = None
    for p in chain:
        try:
            return _call_one(p, system, messages, on_token, model, image_b64, temperature)
        except Exception as e:
            last_err = e
            if p == OLLAMA:
                break
            status = getattr(getattr(e, "response", None), "status_code", None)
            _mark_down(p, 300 if status == 429 else 90)
            log.warning(f"Provider '{p}' failed ({e}); trying next in chain")
    raise last_err


def test_connection(kind: str, base_url: str = None, api_key: str = None,
                    model: str = None) -> tuple:
    """Live connectivity check for the Settings panel.
    kind: 'ollama' | 'claude' | 'openai_compat' (Groq/OpenAI/OpenRouter/…).
    Returns (ok, human_message)."""
    t0 = time.time()
    try:
        if kind == "ollama":
            url = (base_url or cfg.get("ollama_base_url")).rstrip("/")
            r = requests.get(url + "/api/tags", timeout=6)
            r.raise_for_status()
            n = len(r.json().get("models", []))
            return True, f"✓ Connected — {n} models installed ({int((time.time()-t0)*1000)} ms)"
        if kind == "claude":
            if not (api_key or "").strip():
                return False, "✗ No API key entered"
            url = (base_url or cfg.get("claude_base_url")
                   or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
            r = requests.post(url, timeout=20, headers={
                "x-api-key": api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }, json={"model": model or "claude-sonnet-4-6", "max_tokens": 8,
                     "messages": [{"role": "user", "content": "Reply with exactly: OK"}]})
            r.raise_for_status()
            return True, f"✓ Connected ({int((time.time()-t0)*1000)} ms)"
        # openai-compatible
        if not (base_url or "").strip():
            return False, "✗ No base URL entered"
        if not (api_key or "").strip():
            return False, "✗ No API key entered"
        r = requests.post(base_url.rstrip("/") + "/chat/completions", timeout=20,
                          headers={"Authorization": f"Bearer {api_key}"},
                          json={"model": model, "max_tokens": 8,
                                "messages": [{"role": "user", "content": "Reply with exactly: OK"}]})
        r.raise_for_status()
        return True, f"✓ Connected ({int((time.time()-t0)*1000)} ms)"
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        hint = {401: "invalid API key", 403: "key lacks access",
                404: "model not found — check the model id",
                429: "rate limited"}.get(status, "")
        detail = ""
        try:
            j = e.response.json()
            detail = (j.get("error", {}) or {}).get("message", "") or j.get("message", "")
        except Exception:
            pass
        msg = f"✗ HTTP {status}"
        if hint:   msg += f" — {hint}"
        if detail: msg += f": {detail[:90]}"
        return False, msg
    except requests.ConnectionError:
        return False, "✗ Cannot reach server — check the URL / internet"
    except requests.Timeout:
        return False, "✗ Timed out"
    except Exception as e:
        return False, f"✗ {str(e)[:100]}"


# ── Ollama (local) ──────────────────────────────────────────────────────────

def list_ollama_models() -> list:
    """Names of locally installed Ollama models (for the settings picker)."""
    try:
        r = requests.get(f"{cfg.get('ollama_base_url')}/api/tags", timeout=4)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        log.warning(f"Ollama model list failed: {e}")
        return []


def _ollama(system, messages, on_token, model, image_b64, temperature) -> str:
    msgs = list(messages)
    if image_b64 and msgs and msgs[-1]["role"] == "user":
        msgs[-1] = {**msgs[-1], "images": [image_b64]}
    try:
        return _ollama_call(system, msgs, on_token, model, temperature)
    except requests.HTTPError as e:
        # Non-vision models reject image payloads with 400 — retry text-only.
        if image_b64 and e.response is not None and e.response.status_code == 400:
            log.warning("Ollama rejected image (model lacks vision); retrying without image")
            return _ollama_call(system, list(messages), on_token, model, temperature)
        raise


def _ollama_call(system, msgs, on_token, model, temperature) -> str:
    payload = {
        "model":    model or cfg.get("ollama_model"),
        "system":   system,
        "messages": msgs,
        "stream":   on_token is not None,
        "options":  {"temperature": temperature, "num_ctx": 4096},
    }
    url = f"{cfg.get('ollama_base_url')}/api/chat"
    if on_token is None:
        payload["stream"] = False
        r = requests.post(url, json=payload, timeout=180)
        r.raise_for_status()
        return r.json()["message"]["content"]
    full = []
    with requests.post(url, json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                tok = chunk.get("message", {}).get("content", "")
                if tok:
                    full.append(tok)
                    on_token(tok)
                if chunk.get("done"):
                    break
            except Exception:
                continue
    return "".join(full)


# ── OpenAI-compatible chat API (Groq, OpenAI, OpenRouter, Mistral, …) ───────

def _openai_compat(system, messages, on_token, model, temperature,
                   base_url, api_key) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    msgs = [{"role": "system", "content": system}]
    for m in messages:
        if m.get("content"):
            role = "assistant" if m["role"] == "assistant" else "user"
            msgs.append({"role": role, "content": m["content"]})
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {"model": model, "messages": msgs,
               "temperature": temperature, "stream": on_token is not None}
    if on_token is None:
        r = requests.post(url, json=payload, headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    full = []
    with requests.post(url, json=payload, headers=headers, stream=True, timeout=180) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            s = line.decode("utf-8", "ignore").strip()
            if s.startswith("data:"):
                s = s[5:].strip()
            if not s or s == "[DONE]":
                if s == "[DONE]":
                    break
                continue
            try:
                delta = json.loads(s)["choices"][0].get("delta", {})
                tok = delta.get("content", "")
                if tok:
                    full.append(tok)
                    on_token(tok)
            except Exception:
                continue
    return "".join(full)


# ── Claude (Anthropic Messages API) ─────────────────────────────────────────

def _claude_messages(messages):
    """Normalise to alternating user/assistant, starting with user."""
    norm = []
    for m in messages:
        c = m.get("content")
        if not c:
            continue
        role = "assistant" if m["role"] == "assistant" else "user"
        if norm and norm[-1]["role"] == role:
            norm[-1]["content"] += "\n\n" + c
        else:
            norm.append({"role": role, "content": c})
    while norm and norm[0]["role"] != "user":
        norm.pop(0)
    if not norm:
        norm = [{"role": "user", "content": "Hello"}]
    return norm


def _claude(system, messages, on_token, model, temperature) -> str:
    url = (cfg.get("claude_base_url") or "https://api.anthropic.com/v1").rstrip("/") + "/messages"
    headers = {
        "x-api-key":         cfg.get("claude_api_key"),
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    payload = {
        "model":      model,
        "system":     system,
        "messages":   _claude_messages(messages),
        "max_tokens": int(cfg.get("claude_max_tokens") or 1500),
        "temperature": temperature,
        "stream":     on_token is not None,
    }
    if on_token is None:
        r = requests.post(url, json=payload, headers=headers, timeout=180)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []))
    full = []
    with requests.post(url, json=payload, headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            s = line.decode("utf-8", "ignore").strip()
            if not s.startswith("data:"):
                continue
            s = s[5:].strip()
            try:
                d = json.loads(s)
                t = d.get("type")
                if t == "content_block_delta":
                    tok = d.get("delta", {}).get("text", "")
                    if tok:
                        full.append(tok)
                        on_token(tok)
                elif t == "message_stop":
                    break
            except Exception:
                continue
    return "".join(full)
