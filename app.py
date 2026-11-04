import base64
import html
import json
import time
import io
import os
import re
import wave
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

import anthropic
import streamlit as st
from google import genai
from PIL import Image

MAX_PROMPT_CHARS = 8_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 5

# Claude models Troy can use (paid from Paul's Claude Console credits).
CLAUDE_MODELS = {
    "Claude Haiku 5.5 — fast, cheapest": "claude-haiku-5-5",
    "Claude Sonnet 5.5 — smarter, ~20x the cost": "claude-sonnet-5-5",
}
CLAUDE_MAX_REPLY_TOKENS = 4_096
HISTORY_MESSAGES = 24       # how many past messages Claude sees
FILE_MEMORY_MESSAGES = 6    # files stay attached for this many recent messages

# File types Troy can read. HEIC is left out on purpose: then the iPhone hands
# over photos as JPEG, which both Claude and Gemini can read.
FILE_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "txt": "text/plain",
    "md": "text/plain",
    "csv": "text/csv",
}


def speech_text(text):
    """Strip markdown symbols so the voice doesn't read out '*' and '#'."""
    text = str(text or "")
    text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](link) -> label
    text = re.sub(r"[*_`#>|~]+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# Gemini's free text-to-speech model and a few of its voices.
TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_VOICES = {
    "Charon — calm, informative": "Charon",
    "Puck — upbeat": "Puck",
    "Kore — firm": "Kore",
    "Sulafat — warm": "Sulafat",
    "Aoede — breezy": "Aoede",
    "Enceladus — soft, breathy": "Enceladus",
}
MAX_TTS_CHARS = 2_500


def pcm_to_wav(pcm, rate=24_000):
    """Gemini sends raw 16-bit mono sound; wrap it so phones can play it."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def human_voice(client, text, voice_name):
    """Return WAV bytes of Troy saying `text` in a natural Gemini voice."""
    spoken = speech_text(text)
    if len(spoken) > MAX_TTS_CHARS:
        spoken = spoken[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + " ... The rest is on screen."
    response = client.models.generate_content(
        model=TTS_MODEL,
        contents="Read this aloud in a warm, natural, conversational voice:\n" + spoken,
        config=genai.types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=genai.types.SpeechConfig(
                voice_config=genai.types.VoiceConfig(
                    prebuilt_voice_config=genai.types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )
    for part in response.candidates[0].content.parts:
        blob = getattr(part, "inline_data", None)
        if blob and blob.data:
            rate = 24_000
            match = re.search(r"rate=(\d+)", blob.mime_type or "")
            if match:
                rate = int(match.group(1))
            return pcm_to_wav(blob.data, rate)
    raise ValueError("no audio returned")


# iPhone Safari only lets a page make sound if a tap started it. Troy's voice
# arrives seconds after you hit send, so Safari blocks it. Fix: on your first tap
# anywhere, "unlock" one audio player and keep it for the whole visit; every
# reply after that plays through it with no extra tap.
SPEAKER_JS = """
<script>
(() => {
  if (window.troyAudio) return;
  // Play even when the iPhone ringer switch is on silent (Safari 17+).
  try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) {}
  const SILENT = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
  const A = window.troyAudio = { el: new Audio(), unlocked: false, url: null };
  A.el.setAttribute("playsinline", "");
  function unlock() {
    if (A.unlocked) return;
    A.unlocked = true;
    A.el.src = SILENT;
    A.el.play().catch(() => { A.unlocked = false; });
    if (window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(" ");
      u.volume = 0;
      window.speechSynthesis.speak(u);
    }
  }
  ["touchend", "click", "keydown"].forEach(e =>
    document.addEventListener(e, unlock, { capture: true }));
  A.stop = () => {
    try { A.el.pause(); } catch (e) {}
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  };
  A.play = (b64) => {
    A.stop();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    if (A.url) URL.revokeObjectURL(A.url);
    A.url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
    A.el.src = A.url;
    return A.el.play();
  };
})();
</script>
"""


def play_voice(wav_bytes):
    """Play Troy's voice right away through the unlocked player."""
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    st.html(
        f"""<script>
        (() => {{
          const A = window.troyAudio;
          if (A) A.play("{b64}").catch(() => {{}});
        }})();
        </script>""",
        unsafe_allow_javascript=True,
    )


def speak_reply(text, autoplay=False):
    container_id = f"troy-speech-{uuid4().hex}"
    safe_text = html.escape(speech_text(text))
    start_speech = "speak();" if autoplay else ""
    st.html(
        f"""
        <div id="{container_id}">
            <button class="read-aloud" type="button">🔊 Read aloud</button>
            <button class="stop-speaking" type="button">⏹ Stop speaking</button>
            <span class="speech-text" style="display:none">{safe_text}</span>
        </div>
        <script>
        (() => {{
            const container = document.getElementById("{container_id}");
            const readButton = container.querySelector(".read-aloud");
            const stopButton = container.querySelector(".stop-speaking");
            function speak() {{
                if (!window.speechSynthesis) {{
                    readButton.textContent = "Speech is not supported in this browser";
                    return;
                }}
                window.speechSynthesis.cancel();
                const text = container.querySelector(".speech-text").textContent;
                // Chrome stops long utterances after ~15 s, so speak in
                // sentence-sized pieces that queue one after another.
                const pieces = text.match(/[^.!?\\n]+[.!?]*\\s*/g) || [text];
                const voice = bestVoice();
                for (const piece of pieces) {{
                    if (piece.trim()) {{
                        const u = new SpeechSynthesisUtterance(piece.trim());
                        if (voice) {{
                            try {{ u.voice = voice; u.lang = voice.lang; }} catch (e) {{}}
                        }}
                        window.speechSynthesis.speak(u);
                    }}
                }}
            }}
            // Pick the most natural English voice on this device:
            // Premium/Enhanced (iPhone), Natural/Online (Edge), Google (Chrome).
            function bestVoice() {{
                const voices = window.speechSynthesis.getVoices()
                    .filter(v => /^en/i.test(v.lang));
                const rank = v =>
                    (/premium/i.test(v.name) ? 60 : 0) +
                    (/natural|neural|online/i.test(v.name) ? 50 : 0) +
                    (/enhanced/i.test(v.name) ? 40 : 0) +
                    (/google/i.test(v.name) ? 30 : 0) +
                    (/^(ava|evan|zoe|nathan|samantha|alex|aria|guy|jenny)\\b/i.test(v.name) ? 10 : 0) +
                    (/en[-_]US/i.test(v.lang) ? 5 : 0) +
                    (v.localService ? 0 : 1);
                voices.sort((a, b) => rank(b) - rank(a));
                return voices[0] || null;
            }}
            readButton.addEventListener("click", speak);
            stopButton.addEventListener("click", () => {{
                if (window.troyAudio) window.troyAudio.stop();
                else if (window.speechSynthesis) window.speechSynthesis.cancel();
            }});
            {start_speech}
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


TROY_INSTRUCTIONS = """
You are Troy, Paul's personal AI assistant. Be warm, direct, and genuinely helpful, the way
a capable friend would be. Answer what Paul actually asks and get to the point; don't open
by asking what he wants to learn or turn replies into lessons or quizzes unless he asks to be
taught. When he does want to learn something, explain it clearly in plain English, step by
step, with examples, and distinguish established facts from uncertainty.
For high-stakes medical, legal, financial, or safety topics, give general educational
information and encourage checking important decisions with a qualified professional.
For cybersecurity topics, prioritize defending systems Paul owns or is authorized
to assess. Do not assist with unauthorized access, credential theft, malware, or evasion.
Paul can attach PDFs, photos, and text files to a message. When files are attached,
read them and use what is in them in your answer. Never tell Paul you can't read
attached files.
"""

st.set_page_config(page_title="TROY", layout="centered")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 54rem;
        padding: 4rem 1.5rem 6rem;
    }

    [data-testid="stChatMessage"] {
        padding: 1rem;
        border-radius: 0.75rem;
    }

    .troy-welcome {
        text-align: center;
        margin: 2.5rem 0 2rem;
    }
    .troy-welcome h1 {
        font-family: Georgia, "Times New Roman", serif;
        font-weight: 400;
        font-size: 2.4rem;
        line-height: 1.2;
        margin: 0.4rem 0 0;
        padding: 0;
    }
    .troy-mark {
        color: #0ea5a4;
        font-weight: 700;
        letter-spacing: 0.25em;
        font-size: 0.85rem;
    }
    /* Recents list: left-aligned rows like Claude's sidebar */
    .st-key-recents button {
        justify-content: flex-start;
        text-align: left;
        padding-left: 0.6rem;
        min-height: 2.6rem;
    }
    .st-key-recents button > div,
    .st-key-recents button > div > span {
        justify-content: flex-start;
        width: 100%;
        min-width: 0;
    }
    .st-key-recents button p {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: left;
    }
    .st-key-recents button[kind="tertiary"] {
        border: 1px solid transparent;
    }
    .troy-side-title {
        font-family: Georgia, "Times New Roman", serif;
        font-size: 1.9rem;
        margin: -1.5rem 0 0.75rem;
    }
    .troy-side-label {
        opacity: 0.6;
        font-size: 0.9rem;
        margin: 0.75rem 0 0.25rem;
    }
    .troy-badge {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin-top: 1.5rem;
        font-weight: 600;
    }
    .troy-badge span {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        border: 1px solid rgba(128, 128, 128, 0.45);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 0.9rem;
    }
    /* Message box, like Claude's: big, rounded, easy to see */
    /* Streamlit Cloud puts its own badges (your profile picture and the red
       "Hosted with Streamlit" crown) in the bottom-right corner, outside Troy,
       where Troy can't hide them. Lift the message box above them. */
    /* Lift the box itself (the outer frame didn't move on Streamlit Cloud).
       5.5rem clears Safari's floating toolbar plus the two badges. */
    [data-testid="stChatInput"] {
        margin-bottom: calc(5.5rem + env(safe-area-inset-bottom)) !important;
    }
    [data-testid="stChatInput"] {
        border-radius: 1.6rem !important;
        border: 1px solid rgba(128, 128, 128, 0.45) !important;
        background: rgba(128, 128, 128, 0.12) !important;
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
        padding: 0.5rem 0.5rem 0.5rem 0.75rem;
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: #0ea5a4 !important;
    }
    /* one box only (Streamlit draws a second one inside) */
    [data-testid="stChatInput"] > div {
        background: transparent !important;
        border: none !important;
    }
    /* text on its own full-width row, buttons underneath (like Claude) */
    [data-testid="stChatInput"] > div > div {
        flex-wrap: wrap !important;
        align-items: center;
        row-gap: 0.35rem;
    }
    [data-testid="stChatInput"] > div > div > div:has(textarea) {
        order: 0;
        flex: 1 1 100% !important;
        width: 100% !important;
    }
    [data-testid="stChatInput"] > div > div > div:has([data-testid="stChatInputFileUploadButton"]) {
        order: 1;
    }
    [data-testid="stChatInput"] > div > div > div:has([data-testid="stChatInputSubmitButton"]) {
        order: 2;
        margin-left: auto;
        gap: 0.4rem;
    }
    [data-testid="stChatInput"] textarea {
        font-size: 1.15rem !important;
        line-height: 1.5 !important;
        min-height: 2.6rem;
        padding-left: 0.25rem !important;
    }
    [data-testid="stChatInputFileUploadButton"] button,
    [data-testid="stChatInputMicButton"] {
        border: 1px solid rgba(128, 128, 128, 0.45) !important;
        border-radius: 50% !important;
    }
    [data-testid="stChatInputSubmitButton"] {
        background: #0ea5a4 !important;
        color: #ffffff !important;
        border-radius: 50% !important;
        width: 2.75rem !important;
        height: 2.75rem !important;
    }
    [data-testid="stChatInputSubmitButton"]:disabled {
        opacity: 0.45;
    }
    [data-testid="stChatInput"] button {
        min-width: 2.75rem;
        min-height: 2.75rem;
    }
    .troy-topbar {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.25rem;
    }
    .troy-menu {
        width: 44px;
        height: 44px;
        display: inline-flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        gap: 5px;
        border: 1px solid rgba(128, 128, 128, 0.35);
        border-radius: 12px;
        background: transparent;
        color: inherit;
        cursor: pointer;
        padding: 0;
    }
    .troy-menu span {
        display: block;
        width: 20px;
        height: 2px;
        border-radius: 2px;
        background: currentColor;
    }
    .troy-menu:active {
        opacity: 0.6;
    }

    @media (max-width: 640px) {
        .block-container {
            padding: 3.5rem 0.75rem calc(5rem + env(safe-area-inset-bottom));
        }

        [data-testid="stChatMessage"] {
            padding: 0.75rem;
        }

        [data-testid="stChatInput"] textarea {
            font-size: 16px;
        }

        .troy-welcome h1 {
            font-size: 2rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---- Welcome, like Claude: greet Paul by time of day until the chat starts ----
def greeting():
    try:
        now = datetime.now(ZoneInfo("America/Chicago"))
    except Exception:  # no time-zone data on this computer
        now = datetime.now(timezone(timedelta(hours=-6)))
    if 5 <= now.hour < 12:
        return "Good morning, Paul"
    if 12 <= now.hour < 17:
        return "Good afternoon, Paul"
    return "Good evening, Paul"


# ☰ menu button, like Claude's. Streamlit's own sidebar arrow is tiny and on
# iPhone it hides under Safari's address bar, so this opens the sidebar instead.
MENU_BUTTON = """
<button class="troy-menu" type="button" aria-label="Open menu">
  <span></span><span></span><span></span>
</button>
<script>
(() => {
  document.querySelectorAll(".troy-menu").forEach(btn => {
    if (btn.dataset.ready) return;
    btn.dataset.ready = "1";
    btn.addEventListener("click", () => {
      const open = document.querySelector(
        '[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"] button');
      if (open) { open.click(); return; }
      // Sidebar already open: close it.
      const close = document.querySelector(
        '[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarHeader"] button');
      if (close) close.click();
    });
  });
})();
</script>
"""
if not st.session_state.get("messages"):
    st.html(
        MENU_BUTTON
        + f'''<div class="troy-welcome">
            <div class="troy-mark">TROY</div>
            <h1>{greeting()}</h1>
        </div>''',
        unsafe_allow_javascript=True,
    )
else:
    st.html(
        '<div class="troy-topbar">' + MENU_BUTTON
        + '<div class="troy-mark">TROY</div></div>',
        unsafe_allow_javascript=True,
    )

# ---- Find Troy's key ----
# 1. Streamlit Secret (used when deployed on Streamlit Cloud)
# 2. Environment variable (if you ever set one)
# 3. Sidebar box (handy when running locally)
api_key = ""
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    api_key = os.environ.get("GEMINI_API_KEY", "")

st.html(SPEAKER_JS, unsafe_allow_javascript=True)
auto_speak = st.toggle(
    "🔊 Troy speaks out loud", value=True, key="voice_on",
    help="On: Troy reads every reply aloud by himself. Off: he stays quiet.",
)
# One page helper, drawn on EVERY run so the layout never shifts. (If it only
# appeared sometimes, Streamlit would think the attach panel was new and close it.)
page_jobs = []
if st.session_state.pop("hide_keyboard", False):
    # Like Claude: after you send, put the phone keyboard away so you can read.
    page_jobs.append(
        """const hide = () => {
             const el = document.activeElement;
             if (el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT")) el.blur();
           };
           [0, 150, 600].forEach(ms => setTimeout(hide, ms));"""
    )
if not auto_speak:
    page_jobs.append("window.troyAudio && window.troyAudio.stop();")
if st.session_state.pop("close_sidebar", False):
    # On a phone, slide the sidebar shut after picking a chat (like Claude).
    page_jobs.append(
        """setTimeout(() => {
             if (window.innerWidth > 700) return;
             const b = document.querySelector(
               '[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarHeader"] button');
             if (b) b.click();
           }, 50);"""
    )
st.html(
    "<script>(() => {" + "\n".join(page_jobs) + "})();</script>",
    unsafe_allow_javascript=True,
)
# ---- Keys from Streamlit Secrets or environment ----
claude_key = ""
try:
    claude_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    claude_key = os.environ.get("ANTHROPIC_API_KEY", "")

# ---- Chat state ----
for name, start in (
    ("messages", []), ("claude_history", []), ("chats", {}), ("chat_id", None),
    ("store_loaded", False), ("save_payload", ""), ("save_rev", ""),
):
    if name not in st.session_state:
        st.session_state[name] = start
if "load_token" not in st.session_state:
    st.session_state.load_token = uuid4().hex

# Saves Troy's chats in this phone's browser storage, so they're private to the
# phone and survive Troy restarting on Streamlit Cloud.
STORE_JS = """
export default function(component) {
  const { data, setTriggerValue } = component;
  const KEY = "troy_chats_v1";
  if (!data) return;
  if (data.save_rev && window.__troySavedRev !== data.save_rev) {
    try { localStorage.setItem(KEY, data.save); window.__troySavedRev = data.save_rev; } catch (e) {}
  }
  if (data.load_token && window.__troyLoadToken !== data.load_token) {
    window.__troyLoadToken = data.load_token;
    let raw = null;
    try { raw = localStorage.getItem(KEY); } catch (e) {}
    setTriggerValue("loaded", raw || "{}");
  }
}
"""


@st.cache_resource
def troy_store():
    return st.components.v2.component("troy_store", js=STORE_JS)


MAX_SAVED_CHATS = 40


def queue_save():
    """Send the chat list to the phone's storage on the next draw."""
    if not st.session_state.store_loaded:
        return  # never overwrite saved chats before they've been read
    newest = sorted(st.session_state.chats.values(), key=lambda c: c["updated"], reverse=True)
    st.session_state.chats = {c["id"]: c for c in newest[:MAX_SAVED_CHATS]}
    st.session_state.save_payload = json.dumps(st.session_state.chats)
    st.session_state.save_rev = uuid4().hex


def chat_title(messages):
    for m in messages:
        if m["role"] == "user":
            first = m["text"].split("\n\n📎")[0].removeprefix("🎤 ").strip()
            first = first or "Files"
            return first[:48] + ("…" if len(first) > 48 else "")
    return "New chat"


def save_current():
    msgs = [{"role": m["role"], "text": m["text"]} for m in st.session_state.messages]
    if not msgs:
        return
    cid = st.session_state.chat_id or uuid4().hex[:12]
    old = st.session_state.chats.get(cid, {})
    st.session_state.chats[cid] = {
        "id": cid, "title": old.get("title") or chat_title(msgs),
        "updated": time.time(), "messages": msgs,
    }
    st.session_state.chat_id = cid
    queue_save()


def new_gemini_chat(history=None):
    if "client" not in st.session_state:
        return
    contents = [
        genai.types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[genai.types.Part.from_text(text=m.get("text") or m.get("content", ""))],
        )
        for m in (history or [])
    ]
    st.session_state.chat = st.session_state.client.chats.create(
        model="gemini-2.5-flash",
        config=genai.types.GenerateContentConfig(system_instruction=TROY_INSTRUCTIONS),
        history=contents or None,
    )


def history_for_brain(msgs):
    """Text-only history in strict user/assistant turns (what Claude requires)."""
    out = []
    for m in msgs:
        role = "user" if m["role"] == "user" else "assistant"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + m["text"]
        else:
            out.append({"role": role, "content": m["text"]})
    return out


def start_new_chat():
    st.session_state.messages = []
    st.session_state.claude_history = []
    st.session_state.chat_id = None
    new_gemini_chat()


def open_chat(cid):
    chat = st.session_state.chats[cid]
    st.session_state.messages = [dict(m) for m in chat["messages"]]
    hist = history_for_brain(chat["messages"])
    st.session_state.claude_history = hist
    st.session_state.chat_id = cid
    new_gemini_chat(hist)


with st.sidebar:
    store = troy_store()(
        data={
            "load_token": "" if st.session_state.store_loaded else st.session_state.load_token,
            "save": st.session_state.save_payload,
            "save_rev": st.session_state.save_rev,
        },
        key="troy_store",
        on_loaded_change=lambda: None,
        height=0,
    )
    if not st.session_state.store_loaded and store.loaded is not None:
        try:
            saved = json.loads(store.loaded) or {}
        except Exception:
            saved = {}
        saved.update(st.session_state.chats)  # keep anything from this visit
        st.session_state.chats = saved
        st.session_state.store_loaded = True
        queue_save()

    st.markdown('<div class="troy-side-title">TROY</div>', unsafe_allow_html=True)
    if st.button("New chat", key="new_chat", icon=":material/add:", width="stretch"):
        start_new_chat()
        st.session_state.close_sidebar = True
        st.rerun()
    query = st.text_input(
        "Search chats", key="chat_search", placeholder="Search chats",
        label_visibility="collapsed", icon=":material/search:",
    ).strip().lower()

    with st.expander("Settings", key="settings_panel", icon=":material/settings:"):
        use_human_voice = st.checkbox(
            "Human voice (Gemini)",
            value=True,
            help="Uses Gemini's free voice model: one extra free call per reply, on its own "
            "daily allowance. If it's unavailable, Troy falls back to your device's voice.",
        )
        voice_label = st.selectbox(
            "Troy's voice", list(TTS_VOICES), disabled=not use_human_voice
        )
        if not claude_key:
            claude_key = st.text_input("Paste your Claude API key:", type="password")
        if not api_key:
            api_key = st.text_input("Paste your free Gemini key (voice):", type="password")
        brain = "claude" if claude_key else ("gemini" if api_key else None)
        claude_model = CLAUDE_MODELS[
            st.selectbox("Troy's brain", list(CLAUDE_MODELS), disabled=brain != "claude")
        ]
        if brain == "claude":
            st.caption("AI brain: Claude — no daily limit (uses your Console credits)")
        elif brain == "gemini":
            st.caption("AI brain: Gemini free tier (20 messages a day)")
        else:
            st.caption("AI brain: waiting for a key")
        st.caption("Human voice: " + ("Gemini (free)" if api_key else "needs Gemini key"))
        st.caption("Chats are saved on this phone only.")

    st.markdown('<div class="troy-side-label">Recents</div>', unsafe_allow_html=True)
    recents = sorted(st.session_state.chats.values(), key=lambda c: c["updated"], reverse=True)
    if query:
        recents = [
            c for c in recents
            if query in c["title"].lower()
            or any(query in m["text"].lower() for m in c["messages"])
        ]
    if not recents:
        st.caption("No chats yet." if not query else "No chats match.")
    recents_box = st.container(key="recents", gap="small")
    for c in recents:
        current = c["id"] == st.session_state.chat_id
        if recents_box.button(
            c["title"], key=f"open_{c['id']}", icon=":material/chat_bubble:",
            type="secondary" if current else "tertiary", width="stretch",
        ) and not current:
            open_chat(c["id"])
            st.session_state.close_sidebar = True
            st.rerun()
    if st.session_state.chat_id:
        if st.button("Delete this chat", key="delete_chat", icon=":material/delete:",
                     type="tertiary"):
            st.session_state.chats.pop(st.session_state.chat_id, None)
            queue_save()
            start_new_chat()
            st.rerun()
    st.markdown(
        '<div class="troy-badge"><span>PC</span>Paul Contreras</div>',
        unsafe_allow_html=True,
    )

# Keep clients in session_state. If they are throwaway variables, Python
# deletes them after this run and the chat fails with "client has been closed".
if claude_key and st.session_state.get("claude_key") != claude_key:
    st.session_state.claude = anthropic.Anthropic(api_key=claude_key)
    st.session_state.claude_key = claude_key
if api_key and st.session_state.get("key") != api_key:
    st.session_state.client = genai.Client(api_key=api_key)
    new_gemini_chat(history_for_brain(st.session_state.messages))
    st.session_state.key = api_key


def make_voice(msg):
    """Fill in msg['audio'], or a note saying why the device voice is used."""
    try:
        with st.spinner("Troy is getting his voice ready..."):
            msg["audio"] = human_voice(
                st.session_state.client, msg["text"], TTS_VOICES[voice_label]
            )
    except Exception as e:
        if getattr(e, "code", None) == 429:
            # Voice allowance used up: stop trying for the rest of this visit.
            st.session_state.tts_off_today = True
            msg["voice_note"] = "Human voice used up for today — using your device's voice."
        else:
            msg["voice_note"] = (
                f"Human voice unavailable ({type(e).__name__}) — using your device's voice."
            )


# ---- Show the conversation so far ----
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["text"])
        if msg["role"] == "assistant":
            autoplay = msg.pop("autoplay", False) and auto_speak
            if msg.pop("pending_voice", False):
                make_voice(msg)
            if msg.get("audio"):
                st.audio(msg["audio"], format="audio/wav")
                if autoplay:
                    play_voice(msg["audio"])
            else:
                if msg.get("voice_note"):
                    st.caption(msg["voice_note"])
                speak_reply(msg["text"], autoplay=autoplay)

# One message box, like Claude's: ＋ for files, the text, a mic, and send.
submission = st.chat_input(
    "How can I help you today?",
    key="composer",
    max_chars=MAX_PROMPT_CHARS,
    accept_file="multiple",
    file_type=[f".{ext}" for ext in FILE_TYPES],
    accept_audio=True,
    max_upload_size=10,
)
prompt = (submission.text or "").strip() if submission else ""
attached = list(submission.files or []) if submission else []
voice_audio = submission.audio if submission else None
send_voice = voice_audio is not None
ask_about_files = bool(attached) and not prompt and not send_voice


def explain_error(e):
    """Turn an error into a short, honest message without leaking details."""
    if isinstance(e, anthropic.APIError):
        code = getattr(e, "status_code", None)
        detail = str(getattr(e, "message", "") or e).lower()
        if "credit balance" in detail:
            return ("Troy's Claude credits ran out. Add more at console.anthropic.com → "
                    "Billing, then ask again.")
        if code == 401:
            return "Claude didn't accept the API key (401). Check ANTHROPIC_API_KEY in Troy's secrets."
        if code == 429:
            return "Claude asked Troy to slow down (429). Wait a minute and try again."
        if code in (500, 529) or (code or 0) >= 500:
            return f"Claude's servers are busy ({code}). Try again in a minute."
        if code == 400:
            return "Claude couldn't read that request (400). If you attached a file, try a smaller one."
        return f"Troy had a problem talking to Claude ({type(e).__name__}). Try again."
    code = getattr(e, "code", None)
    if code == 429:
        return ("Troy used up today's free Gemini messages (429). Add your Claude key "
                "(ANTHROPIC_API_KEY in Troy's Streamlit Secrets) for no daily limit, "
                "or try again tomorrow.")
    if code in (400, 401, 403):
        return f"Gemini rejected the request ({code}). Check that the API key is correct."
    if code is not None and code >= 500:
        return f"Gemini's servers had a problem ({code}). Try again in a minute."
    return f"Troy had a problem ({type(e).__name__}). Try again."


def shrink_photo(data, mime):
    """Claude takes photos up to 5 MB; big phone photos get resized."""
    if not mime.startswith("image/") or (len(data) < 3_500_000):
        return data, mime
    img = Image.open(io.BytesIO(data))
    img.thumbnail((2000, 2000))
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


def file_parts(files):
    """Read uploaded files into a simple list. Returns (files, problem)."""
    if len(files) > MAX_FILES:
        return None, f"Please attach {MAX_FILES} files or fewer at a time."
    parts = []
    for f in files:
        data = f.getvalue()
        if len(data) > MAX_FILE_BYTES:
            return None, f"{f.name} is over 10 MB. Try a smaller file."
        ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
        mime = FILE_TYPES.get(ext)
        if mime is None:
            return None, f"Troy can't read {f.name}. Use a PDF, photo, or text file."
        try:
            data, mime = shrink_photo(data, mime)
        except Exception:
            return None, f"Troy couldn't open the photo {f.name}. Try another one."
        parts.append({"name": f.name, "mime": mime, "data": data})
    return parts, None


def gemini_parts(files):
    return [genai.types.Part.from_bytes(data=f["data"], mime_type=f["mime"]) for f in files]


def claude_blocks(files, text):
    """Turn files + text into the content blocks Claude reads."""
    blocks = []
    for f in files:
        b64 = base64.b64encode(f["data"]).decode("ascii")
        if f["mime"] == "application/pdf":
            blocks.append({"type": "document", "title": f["name"],
                           "source": {"type": "base64", "media_type": "application/pdf",
                                      "data": b64}})
        elif f["mime"].startswith("image/"):
            blocks.append({"type": "image",
                           "source": {"type": "base64", "media_type": f["mime"], "data": b64}})
        else:
            body = f["data"].decode("utf-8", errors="replace")
            blocks.append({"type": "text", "text": f"File {f['name']}:\n{body}"})
    blocks.append({"type": "text", "text": text})
    return blocks


def claude_messages():
    """Recent history for Claude. Old files are swapped for a short note so a big
    PDF isn't paid for again on every message."""
    hist = st.session_state.claude_history[-HISTORY_MESSAGES:]
    while hist and hist[0]["role"] != "user":
        hist = hist[1:]
    out = []
    for i, m in enumerate(hist):
        content = m["content"]
        if isinstance(content, list) and i < len(hist) - FILE_MEMORY_MESSAGES:
            kept = []
            for b in content:
                if b["type"] in ("image", "document"):
                    kept.append({"type": "text", "text": "[a file Paul shared earlier]"})
                else:
                    kept.append(b)
            content = kept
        out.append({"role": m["role"], "content": content})
    return out


def ask_claude(files, text):
    st.session_state.claude_history.append(
        {"role": "user", "content": claude_blocks(files, text)}
    )
    try:
        response = st.session_state.claude.messages.create(
            model=claude_model,
            max_tokens=CLAUDE_MAX_REPLY_TOKENS,
            system=TROY_INSTRUCTIONS,
            messages=claude_messages(),
        )
    except Exception:
        st.session_state.claude_history.pop()  # keep history in user/assistant order
        raise
    answer = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    st.session_state.claude_history.append({"role": "assistant", "content": answer or "(no reply)"})
    return answer


def transcribe(audio_bytes, mime):
    """Claude can't hear audio, so Gemini writes down what Paul said."""
    last_error = None
    for model in ("gemini-2.5-flash-lite", "gemini-2.5-flash"):
        try:
            r = st.session_state.client.models.generate_content(
                model=model,
                contents=[
                    genai.types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                    "Write down exactly what the speaker says. Reply with only the words.",
                ],
            )
            if r.text and r.text.strip():
                return r.text.strip()
        except Exception as e:
            last_error = e
    raise last_error or ValueError("no words heard")


def file_label(files):
    return "".join(f"\n\n📎 {f.name}" for f in files)


def send_to_troy(user_text, files, text, audio=None):
    """Send Paul's message to Troy's brain and add the reply to the chat."""
    st.session_state.messages.append({"role": "user", "text": user_text})
    st.session_state.hide_keyboard = True
    try:
        if brain == "claude":
            answer = ask_claude(files, text)
        else:
            message = gemini_parts(files) + ([audio] if audio else []) + [text]
            response = st.session_state.chat.send_message(
                message if len(message) > 1 else text
            )
            answer = response.text
        if not isinstance(answer, str) or not answer.strip():
            answer = "I couldn't generate a text reply. Please try asking again."
        ok = True
    except Exception as e:
        answer = explain_error(e)
        ok = False
    reply = {"role": "assistant", "text": answer, "autoplay": auto_speak}
    if (ok and auto_speak and use_human_voice and api_key
            and not st.session_state.get("tts_off_today")):
        # Show the text now; the voice is made right after it appears.
        reply["pending_voice"] = True
    st.session_state.messages.append(reply)
    save_current()



if prompt or send_voice or ask_about_files:
    parts, problem = file_parts(attached)
    if not brain:
        st.warning("Add Troy's Claude key (or a Gemini key) in the sidebar first, then try again.")
    elif problem:
        st.warning(problem)
    elif send_voice:
        audio_bytes = voice_audio.getvalue()
        mime = voice_audio.type or "audio/wav"
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            st.warning("That recording is too large. Please record a shorter message.")
        elif brain == "claude" and not api_key:
            st.warning("Voice messages need the Gemini key. For now, tap the 🎤 on your "
                       "keyboard and talk — it types for you.")
        elif brain == "claude":
            try:
                with st.spinner("Listening..."):
                    words = transcribe(audio_bytes, mime)
                said = (prompt + "\n\n" + words).strip() if prompt else words
                send_to_troy("🎤 " + said + file_label(attached), parts, said)
                st.rerun()
            except Exception:
                st.warning("Troy couldn't make out that recording. Try again, or tap "
                           "the 🎤 on your keyboard and talk — it types for you.")
        else:
            audio_part = genai.types.Part.from_bytes(data=audio_bytes, mime_type=mime)
            note = "This is Paul's voice message. Reply to what he said."
            send_to_troy("🎤 Voice message" + file_label(attached), parts,
                         (prompt + "\n\n" + note) if prompt else note, audio=audio_part)
            st.rerun()
    else:
        text = prompt or "Please read the attached file(s) and help me understand them."
        send_to_troy(text + file_label(attached), parts, text)
        st.rerun()
