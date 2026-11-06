"""
brain.py - Troy's local thinking engine.

Talks to Ollama on this machine over plain HTTP.
No API key. No daily quota. No internet needed once the model is pulled.

Why no "ollama" pip package:
    The Ollama Python SDK changes its return shapes between versions, which
    breaks code that worked last month. The REST endpoint (/api/chat) has been
    stable. This file uses only the Python standard library, so there is
    nothing extra to install and nothing to break on an update.

Drop-in use:
    from brain import think
    answer = think("What is a good weekend plan for improving Troy?")

Environment overrides (optional):
    TROY_LOCAL_MODEL    default "qwen3:8b"
    OLLAMA_HOST         default "http://127.0.0.1:11434"
    TROY_LOCAL_TIMEOUT  default 180 (seconds)
"""

import json
import os
import re
import urllib.error
import urllib.request

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("TROY_LOCAL_MODEL", "qwen3:8b")
TIMEOUT = int(os.environ.get("TROY_LOCAL_TIMEOUT", "180"))

SYSTEM_PROMPT = """You are Troy, Paul's personal AI assistant, running locally on his Windows laptop.

How Paul wants you to work:
- Be practical, clear, patient, and step-by-step.
- Give the answer first. No padding, no hedging.
- When giving instructions, start from the very first keypress.
- Explain code in plain English.

Your subjects: Windows, Python, Streamlit, local files, GIS and plant mapping,
Excel compliance tracking, AI tools, troubleshooting, and planning.

Hard rules:
- Never claim you performed an action unless you received confirmation it
  completed. If you did not run it, say what should be run.
- Ask before suggesting anything risky, destructive, or irreversible.
- If you do not know, say so. Do not invent file paths, commands, or numbers.
"""


# ---------------------------------------------------------------- transport

def _post(path, payload, timeout=TIMEOUT):
    req = urllib.request.Request(
        HOST + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path, timeout=5):
    with urllib.request.urlopen(HOST + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- health

def installed_models():
    """List of model tags currently pulled on this machine. [] if Ollama is down."""
    try:
        tags = _get("/api/tags")
    except Exception:
        return []
    out = []
    for m in tags.get("models", []):
        name = m.get("name") or m.get("model")
        if name:
            out.append(name)
    return out


def status(model=None):
    """
    Returns {"ok": bool, "reason": str, "model": str, "models": [...]}.
    Call this before wiring the brain into a UI so you can show a useful
    message instead of a stack trace.
    """
    want = model or MODEL
    names = installed_models()

    if not names:
        return {
            "ok": False,
            "model": want,
            "models": [],
            "reason": (
                f"Ollama is not answering at {HOST}. "
                "Open PowerShell and run:  ollama serve"
            ),
        }

    # Accept an exact tag, or the same family if the tag was written without it.
    if want in names or any(n.split(":")[0] == want.split(":")[0] for n in names):
        return {"ok": True, "model": want, "models": names, "reason": ""}

    return {
        "ok": False,
        "model": want,
        "models": names,
        "reason": (
            f"Model '{want}' is not pulled. Open PowerShell and run:  "
            f"ollama pull {want}"
        ),
    }


# ---------------------------------------------------------------- thinking

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(text):
    """Qwen and some other models emit a <think>...</think> block. Hide it."""
    return _THINK_BLOCK.sub("", text).strip()


def think(user_message, context="", history=None, model=None, temperature=0.4):
    """
    Ask the local model one question and return the answer as a string.

    user_message : what Paul typed
    context      : optional extra text (file contents, registry entries, notes)
    history      : optional list of {"role": "user"/"assistant", "content": "..."}
    model        : override the default model tag for this one call
    """
    use = model or MODEL

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if context:
        messages.append({
            "role": "system",
            "content": "Local context Troy has already looked up:\n" + str(context),
        })

    if history:
        for turn in history:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    try:
        data = _post("/api/chat", {
            "model": use,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        })
    except urllib.error.URLError as e:
        return (
            f"[Troy local brain offline] Could not reach Ollama at {HOST}.\n"
            f"Details: {e}\n"
            "Fix: open PowerShell and run  ollama serve  then try again."
        )
    except Exception as e:
        return f"[Troy local brain error] {type(e).__name__}: {e}"

    text = (data.get("message") or {}).get("content", "")
    if not text:
        return "[Troy local brain returned nothing] Raw reply: " + json.dumps(data)[:400]

    return _strip_reasoning(text)


# ---------------------------------------------------------------- self test

if __name__ == "__main__":
    print(f"Host  : {HOST}")
    print(f"Model : {MODEL}")

    s = status()
    print(f"Pulled: {', '.join(s['models']) if s['models'] else '(none found)'}")

    if not s["ok"]:
        print("\nFAIL: " + s["reason"])
        raise SystemExit(1)

    print("\nOK. Asking a test question...\n")
    print(think("Say hello in one sentence, then list three things you can help Paul with."))
