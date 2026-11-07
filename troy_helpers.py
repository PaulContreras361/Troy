"""
troy_helpers.py - other AIs Troy can ask: Perplexity, ChatGPT and Gemini.

Plain English:
  Claude stays Troy's brain. These are helpers he can call when they're useful:
    ask_perplexity  - live web search with sources (news, prices, "what's the latest")
    ask_chatgpt     - a second opinion from OpenAI's ChatGPT
    ask_gemini      - a second opinion from Google's Gemini (uses the voice key)
  Paul can also just say "ask ChatGPT ..." or "check this with Perplexity".

  Each helper only shows up when its key is in Settings. Perplexity and the
  OpenAI API bill per question on their own accounts (a ChatGPT Plus
  subscription does NOT include API use). Gemini's free tier has a daily limit.

  Only plain Python (urllib) - nothing extra to install.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

PERPLEXITY_URLS = ["https://api.perplexity.ai/v1/sonar", "https://api.perplexity.ai/chat/completions"]
PERPLEXITY_MODEL = "sonar"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-5.4-mini"
GEMINI_MODEL = "gemini-2.5-flash"
TIMEOUT = 90


def _post(url, key, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_error(name, e):
    try:
        detail = json.loads(e.read().decode("utf-8", "replace"))
        detail = detail.get("error", detail)
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail)[:300]
    except Exception:            # noqa: BLE001
        detail = ""
    hint = {401: "the key was refused - check it in Settings",
            402: "the account is out of credit",
            429: "too many questions or out of credit - try later"}.get(e.code, "")
    return {"ok": False, "error": f"{name} said {e.code}: {hint or detail}"[:400]}


def ask_perplexity(key, question):
    body = {"model": PERPLEXITY_MODEL, "messages": [{"role": "user", "content": question}]}
    last = None
    for url in PERPLEXITY_URLS:
        try:
            data = _post(url, key, body)
        except urllib.error.HTTPError as e:
            if e.code in (404, 405):          # path moved: try the other one
                last = e
                continue
            return _http_error("Perplexity", e)
        except Exception as e:   # noqa: BLE001
            return {"ok": False, "error": f"Couldn't reach Perplexity: {e}"}
        msg = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        sources = data.get("citations") or [s.get("url") for s in data.get("search_results", [])
                                            if isinstance(s, dict)]
        return {"ok": bool(msg), "answer": msg, "sources": [s for s in sources if s][:10]}
    return _http_error("Perplexity", last)


def ask_chatgpt(key, question):
    body = {"model": OPENAI_MODEL, "messages": [{"role": "user", "content": question}]}
    try:
        data = _post(OPENAI_URL, key, body)
    except urllib.error.HTTPError as e:
        return _http_error("ChatGPT", e)
    except Exception as e:       # noqa: BLE001
        return {"ok": False, "error": f"Couldn't reach OpenAI: {e}"}
    msg = ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")
    return {"ok": bool(msg), "answer": msg, "model": data.get("model", OPENAI_MODEL)}


def ask_gemini(client, question):
    try:
        r = client.models.generate_content(model=GEMINI_MODEL, contents=question)
        return {"ok": bool(r.text), "answer": r.text or ""}
    except Exception as e:       # noqa: BLE001
        return {"ok": False, "error": f"Gemini couldn't answer: {type(e).__name__}: {str(e)[:200]}"}


def _schema(desc):
    return {"type": "object", "required": ["question"], "properties": {
        "question": {"type": "string", "description": desc}}}


def tools(perplexity_key="", openai_key="", gemini_client=None):
    """{name: (function(args) -> dict, Claude tool definition)} for the keys Paul has."""
    out = {}
    if perplexity_key:
        out["ask_perplexity"] = (
            lambda a: ask_perplexity(perplexity_key, a.get("question", "")),
            {"name": "ask_perplexity",
             "description": "Search the live web with Perplexity and get an answer with source "
                            "links. Use for current events, prices, weather, rules that may have "
                            "changed, or when Paul says 'ask Perplexity'. Cite the sources.",
             "input_schema": _schema("A complete, specific question for a web search.")})
    if openai_key:
        out["ask_chatgpt"] = (
            lambda a: ask_chatgpt(openai_key, a.get("question", "")),
            {"name": "ask_chatgpt",
             "description": "Ask OpenAI's ChatGPT. Use only when Paul asks for ChatGPT or a second "
                            "opinion. Then check its answer and tell Paul plainly what is right, "
                            "wrong or unverified.",
             "input_schema": _schema("The full question, with any context ChatGPT needs.")})
    if gemini_client is not None:
        out["ask_gemini"] = (
            lambda a: ask_gemini(gemini_client, a.get("question", "")),
            {"name": "ask_gemini",
             "description": "Ask Google's Gemini. Use only when Paul asks for Gemini or a second "
                            "opinion. Then check its answer and tell Paul what is right, wrong "
                            "or unverified.",
             "input_schema": _schema("The full question, with any context Gemini needs.")})
    return out


INSTRUCTIONS = """

OTHER AIs YOU CAN ASK
You have tools to ask other AIs. You are still Troy and you write the final answer.
- When Paul says "ask Perplexity / ChatGPT / Gemini", call that tool with a full question.
- Use ask_perplexity on your own for anything current (news, prices, today's facts),
  and list its source links at the end.
- When you show another AI's answer, say which AI it came from, and give your own straight
  verdict: what's right, what's wrong, what's unverified.
- If a helper returns an error, say so in one line and answer as best you can yourself.
"""
