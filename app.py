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

import troy_study

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
  // iPhone Safari has two toolbar modes. Solid: Troy's page ends above it.
  // See-through (after scrolling): Troy's page runs underneath it and the
  // message box gets covered. Troy's page is then almost as tall as the
  // screen, so lift the box clear of the toolbar and Streamlit's badges.
  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  function fitBox() {
    let lift = 0;
    if (isIOS && screen.height) {
      const tall = window.innerHeight / screen.height;
      if (tall > 0.86) lift = 76;
    }
    document.documentElement.style.setProperty("--troy-lift", lift + "px");
  }
  fitBox();
  window.addEventListener("resize", fitBox);
  if (window.visualViewport) window.visualViewport.addEventListener("resize", fitBox);
  setInterval(fitBox, 1000);
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
       1.5rem keeps it just above the two badges. */
    [data-testid="stChatInput"] {
        margin-bottom: calc(0.5rem + var(--troy-lift, 0px) + env(safe-area-inset-bottom)) !important;
        transition: margin-bottom 0.2s ease;
    }
    [data-testid="stChatInput"] {
        border-radius: 1.6rem !important;
        border: 1px solid rgba(128, 128, 128, 0.45) !important;
        background: rgba(128, 128, 128, 0.12) !important;
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.25);
        padding: 0.3rem 0.45rem 0.3rem 0.6rem;
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
        row-gap: 0;
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
        font-size: 1.1rem !important;
        line-height: 1.4 !important;
        min-height: 2.2rem;
        padding-left: 0.25rem !important;
        padding-top: 0.45rem !important;
        padding-bottom: 0.2rem !important;
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
        width: 2.4rem !important;
        height: 2.4rem !important;
    }
    [data-testid="stChatInputSubmitButton"]:disabled {
        opacity: 0.45;
    }
    [data-testid="stChatInput"] button {
        min-width: 2.4rem;
        min-height: 2.4rem;
    }
    .troy-study-doc { opacity: 0.75; font-size: 0.95rem; margin-bottom: 0.25rem; }
    .troy-study-group { color: #0ea5a4; font-weight: 700; letter-spacing: 0.04em;
        font-size: 0.85rem; margin-top: 0.5rem; }
    .troy-study-title { font-family: Georgia, "Times New Roman", serif; font-size: 1.6rem;
        line-height: 1.25; margin: 0.2rem 0 0.5rem; }
    .troy-study-label { opacity: 0.65; font-size: 0.9rem; margin-top: 0.75rem; }
    .troy-read { font-size: 1.2rem; line-height: 1.65; border: 1px solid rgba(128,128,128,0.3);
        border-radius: 1rem; padding: 0.9rem 1rem; background: rgba(128,128,128,0.06); }
    .troy-read p { margin: 0 0 0.8rem; }
    .troy-read p:last-child { margin-bottom: 0; }
    .troy-read .ts { cursor: pointer; border-radius: 0.3rem; padding: 0.05rem 0.1rem;
        transition: background 0.2s; }
    .troy-read .ts.on { background: rgba(14, 165, 164, 0.35); }
    .troy-topbar {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        min-height: 44px;
        padding-left: 56px;
        margin-bottom: 0.25rem;
    }
    /* ☰ stays pinned top-left while you scroll, just below Safari's address
       bar, like Claude's menu button. */
    .troy-menu {
        position: fixed;
        top: calc(env(safe-area-inset-top) + 4.75rem);
        left: 0.75rem;
        z-index: 1000;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        width: 44px;
        height: 44px;
        display: inline-flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        gap: 5px;
        border: 1px solid rgba(128, 128, 128, 0.35);
        border-radius: 12px;
        background: rgba(20, 22, 28, 0.55);
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
    @media (prefers-color-scheme: light) {
        .troy-menu { background: rgba(255, 255, 255, 0.75); }
    }
    /* invisible marker pinned to the very top of Troy's page */
    .troy-top-anchor {
        position: fixed;
        top: 0;
        left: 0;
        width: 1px;
        height: 1px;
        pointer-events: none;
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
def central_now():
    try:
        return datetime.now(ZoneInfo("America/Chicago"))
    except Exception:  # no time-zone data on this computer
        return datetime.now(timezone(timedelta(hours=-6)))


def with_today(instructions):
    """Add today's date so the brain doesn't have to guess it."""
    now = central_now()
    return (instructions + f"\nToday is {now:%A, %B} {now.day}, {now.year}, "
            f"{now:%I:%M %p} Central time (Point Comfort, Texas).\n")


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
<div class="troy-top-anchor"></div>
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
if not st.session_state.get("messages") and not st.session_state.get("study_on"):
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
           [0, 150, 600].forEach(ms => setTimeout(hide, ms));
           // The iPhone slides Streamlit Cloud's outer page up to make room for
           // the keyboard and leaves it there. Slide it back so Troy's top
           // (and the ☰) shows again. The marker is pinned, so Troy's own chat
           // doesn't scroll.
           const back = () => {
             const a = document.querySelector(".troy-top-anchor");
             if (a) a.scrollIntoView({ block: "start", inline: "nearest" });
           };
           [400, 900, 1600].forEach(ms => setTimeout(back, ms));"""
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
    ("study_on", False), ("study", None), ("study_saved", None),
    ("saved_keys", {}), ("keys_payload", ""), ("keys_rev", ""),
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
  const KEYS = "troy_keys_v1";   // API keys Paul chose to remember on this phone
  if (!data) return;
  if (data.save_rev && window.__troySavedRev !== data.save_rev) {
    try { localStorage.setItem(KEY, data.save); window.__troySavedRev = data.save_rev; } catch (e) {}
  }
  if (data.keys_rev && window.__troyKeysRev !== data.keys_rev) {
    try { localStorage.setItem(KEYS, data.keys); window.__troyKeysRev = data.keys_rev; } catch (e) {}
  }
  if (data.load_token && window.__troyLoadToken !== data.load_token) {
    window.__troyLoadToken = data.load_token;
    let raw = null, keys = null;
    try { raw = localStorage.getItem(KEY); keys = localStorage.getItem(KEYS); } catch (e) {}
    setTriggerValue("loaded", JSON.stringify({ store: raw || "{}", keys: keys || "{}" }));
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
    st.session_state.save_payload = json.dumps(
        {"v": 2, "chats": st.session_state.chats, "study": st.session_state.study_saved}
    )
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
        config=genai.types.GenerateContentConfig(system_instruction=with_today(TROY_INSTRUCTIONS)),
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
            "keys": st.session_state.keys_payload,
            "keys_rev": st.session_state.keys_rev,
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
        if isinstance(saved, dict) and set(saved) == {"store", "keys"}:
            try:
                keys = json.loads(saved["keys"]) or {}
                st.session_state.saved_keys = {
                    k: v for k, v in keys.items() if k in ("claude", "gemini") and v
                }
            except Exception:
                pass
            try:
                saved = json.loads(saved["store"]) or {}
            except Exception:
                saved = {}
        if isinstance(saved, dict) and saved.get("v") == 2:
            if saved.get("study") and not st.session_state.study_saved:
                st.session_state.study_saved = saved["study"]
            saved = saved.get("chats") or {}
        saved.update(st.session_state.chats)  # keep anything from this visit
        st.session_state.chats = saved
        st.session_state.store_loaded = True
        queue_save()

    st.markdown('<div class="troy-side-title">TROY</div>', unsafe_allow_html=True)
    if st.button("New chat", key="new_chat", icon=":material/add:", width="stretch"):
        start_new_chat()
        st.session_state.study_on = False
        st.session_state.close_sidebar = True
        st.rerun()
    if st.button("Study a PDF", key="open_study", icon=":material/menu_book:", width="stretch"):
        st.session_state.study_on = True
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
        # Keys remembered on this phone fill in when Secrets don't have them.
        phone_keys = st.session_state.saved_keys
        from_phone = []
        if not claude_key and phone_keys.get("claude"):
            claude_key = phone_keys["claude"]
            from_phone.append("Claude")
        if not api_key and phone_keys.get("gemini"):
            api_key = phone_keys["gemini"]
            from_phone.append("Gemini")
        typed = {}
        if not claude_key:
            typed["claude"] = st.text_input("Paste your Claude API key:", type="password",
                                            key="type_claude_key").strip()
            claude_key = typed["claude"]
        if not api_key:
            typed["gemini"] = st.text_input("Paste your free Gemini key (voice):",
                                            type="password", key="type_gemini_key").strip()
            api_key = typed["gemini"]
        if typed:
            remember = st.checkbox("Remember keys on this phone", value=True, key="remember_keys",
                                   help="Saved in this phone's browser only, so you don't "
                                   "have to paste them again.")
            good = {k: v for k, v in typed.items() if v}
            bad = [k for k, v in good.items()
                   if (k == "claude" and not v.startswith("sk-ant-"))
                   or (k == "gemini" and not v.startswith("AIza"))]
            if bad:
                st.warning("That doesn't look like a " + " / ".join(
                    "Claude key (starts with sk-ant-)" if k == "claude" else
                    "Gemini key (starts with AIza)" for k in bad) + ".")
            elif remember and good and st.session_state.store_loaded:
                st.session_state.saved_keys = {**phone_keys, **good}
                st.session_state.keys_payload = json.dumps(st.session_state.saved_keys)
                st.session_state.keys_rev = uuid4().hex
                st.rerun()
        if from_phone:
            st.caption("🔑 " + " and ".join(from_phone) + " key saved on this phone.")
            if st.button("Forget saved keys", key="forget_keys", type="tertiary",
                         icon=":material/key_off:"):
                st.session_state.saved_keys = {}
                st.session_state.keys_payload = "{}"
                st.session_state.keys_rev = uuid4().hex
                st.rerun()
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
            st.session_state.study_on = False
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


# ---- Show the conversation so far (Study mode draws its own screen later) ----
for msg in ([] if st.session_state.study_on else st.session_state.messages):
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

if not st.session_state.study_on and st.session_state.get("last_pdf"):
    _pdf_name = st.session_state.last_pdf["name"]
    if st.button(f"Study “{_pdf_name}” section by section", key="study_from_chat",
                 icon=":material/menu_book:"):
        st.session_state.study_on = True
        st.session_state.study_load = st.session_state.last_pdf
        st.rerun()

# One message box, like Claude's: ＋ for files, the text, a mic, and send.
submission = st.chat_input(
    "Ask Troy about this section…" if st.session_state.study_on else "How can I help you today?",
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
            system=with_today(TROY_INSTRUCTIONS),
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
    for f in files:
        if f["mime"] == "application/pdf":
            st.session_state.last_pdf = {"name": f["name"], "data": f["data"]}
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




# =====================================================================
# 📘 Study mode — Troy reads a PDF section by section while Paul follows
# along, then answers questions about it only when Paul asks.
# =====================================================================
STUDY_SYSTEM = """
You are Troy, helping Paul study a document one section at a time.
Use ONLY the section text you are given. Never add rules, numbers, steps, or
requirements that are not in it. If the section doesn't answer something, say
so plainly and, if you can tell, which kind of section would. Plain English,
warm and direct, short sentences that sound good read aloud. No markdown
tables or headings.
"""

STUDY_STYLES = {
    "story": ("📖 Story",
              "Retell this section as a short story (under 220 words) about a worker at "
              "a Gulf Coast plant whose day runs straight into what this section says. "
              "Every fact must match the section exactly. End with one line that starts "
              "'Bottom line:'."),
    "podcast": ("🎙 Podcast",
                "Write a short two-person podcast moment (under 220 words) between Troy "
                "and Jess talking this section through. Start each line with 'Troy:' or "
                "'Jess:'. Jess asks what a listener would ask; Troy answers from the "
                "section. Every fact must match the section exactly."),
    "coach": ("🎯 Coach",
              "Talk straight to Paul like a coach (under 150 words): what this section "
              "says, why it matters on the job, and the one thing to remember."),
}


def ask_brain_once(task, section, max_tokens=1200):
    """One-off question about a section (doesn't touch the chat history)."""
    content = f"Document: {st.session_state.study['name']}\n\nSECTION:\n{section}\n\nTASK:\n{task}"
    if brain == "claude":
        r = st.session_state.claude.messages.create(
            model=claude_model, max_tokens=max_tokens, system=with_today(STUDY_SYSTEM),
            messages=[{"role": "user", "content": content}],
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    r = st.session_state.client.models.generate_content(
        model="gemini-2.5-flash", contents=content,
        config=genai.types.GenerateContentConfig(system_instruction=with_today(STUDY_SYSTEM)),
    )
    return (r.text or "").strip()


def section_label(sec):
    head = f"{sec['num']} {sec['title']}".strip()
    return head


def section_for_brain(sec):
    group = f"(Part of {sec['group']})\n" if sec.get("group") else ""
    return f"{group}{section_label(sec)}\n{sec['text']}"


def load_study_pdf(name, data):
    try:
        result = troy_study.split_sections(data)
    except Exception:
        st.warning(f"Troy couldn't open {name}. Is it a PDF?")
        return
    if result["method"] == "scanned":
        st.warning(f"“{name}” is scanned pictures of pages, so Troy can't pull the words out "
                   "for free reading. You can still attach it with ＋ in a regular chat and "
                   "ask questions about it.")
        return
    st.session_state.study = {
        "name": name, "sections": result["sections"], "idx": 0,
        "qa": {}, "updated": time.time(),
    }
    st.session_state.study_autoread = True
    save_study_progress()


def save_study_progress():
    s = st.session_state.study
    if not s:
        return
    s["updated"] = time.time()
    st.session_state.study_saved = {
        "name": s["name"], "sections": s["sections"], "idx": s["idx"], "updated": s["updated"],
    }
    queue_save()


def go_to_section(i):
    s = st.session_state.study
    s["idx"] = max(0, min(i, len(s["sections"]) - 1))
    st.session_state.study_autoread = True
    save_study_progress()


def add_study_answer(kind, question, answer, quiz=None):
    s = st.session_state.study
    item = {"kind": kind, "q": question, "a": answer, "quiz": quiz, "autoplay": auto_speak}
    if (answer and auto_speak and use_human_voice and api_key
            and not st.session_state.get("tts_off_today")):
        tmp = {"text": answer}
        make_voice(tmp)
        item.update({k: tmp[k] for k in ("audio", "voice_note") if k in tmp})
    s["qa"].setdefault(str(s["idx"]), []).append(item)


def parse_quiz(text):
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {}
    choices = [str(c) for c in data.get("choices", [])][:4]
    ans = int(data.get("answer_index", 0))
    if len(choices) < 2 or not (0 <= ans < len(choices)) or not data.get("question"):
        raise ValueError("bad quiz")
    return {"question": str(data["question"]), "choices": choices, "answer": ans,
            "why": str(data.get("why", "")), "picked": None}


READ_ALONG_JS = """
(() => {
  const box = document.getElementById("%(id)s");
  if (!box || box.dataset.ready) return;
  box.dataset.ready = "1";
  const RATE = %(rate)s;
  const spans = [...box.querySelectorAll(".ts")];
  function bestVoice() {
    if (!window.speechSynthesis) return null;
    const voices = speechSynthesis.getVoices().filter(v => /^en/i.test(v.lang));
    const rank = v => (/premium/i.test(v.name) ? 60 : 0) + (/natural|neural|online/i.test(v.name) ? 50 : 0)
      + (/enhanced/i.test(v.name) ? 40 : 0) + (/google/i.test(v.name) ? 30 : 0)
      + (/en[-_]US/i.test(v.lang) ? 5 : 0);
    voices.sort((a, b) => rank(b) - rank(a));
    return voices[0] || null;
  }
  function clear() { spans.forEach(x => x.classList.remove("on")); }
  function speakFrom(i0) {
    if (!window.speechSynthesis) return;
    if (window.troyAudio) window.troyAudio.stop(); else speechSynthesis.cancel();
    const voice = bestVoice();
    spans.slice(i0).forEach((sp, k) => {
      const u = new SpeechSynthesisUtterance(sp.textContent);
      u.rate = RATE;
      if (voice) { try { u.voice = voice; u.lang = voice.lang; } catch (e) {} }
      u.onstart = () => { clear(); sp.classList.add("on");
        const sc = document.querySelector('[data-testid="stAppScrollToBottomContainer"]');
        if (sc) { const r = sp.getBoundingClientRect(), h = sc.getBoundingClientRect();
          if (r.bottom > h.bottom - 140 || r.top < h.top + 90)
            sc.scrollBy({ top: r.top - h.top - 120, behavior: "smooth" }); } };
      if (k === spans.length - i0 - 1) u.onend = () => clear();
      speechSynthesis.speak(u);
    });
  }
  // Tap any sentence to start reading from there.
  spans.forEach((sp, i) => sp.addEventListener("click", () => speakFrom(i)));
  %(start)s
})();
"""


def read_along(sec, autoplay, rate):
    box_id = f"troy-read-{uuid4().hex}"
    paras = [p for p in re.split(r"\n\s*\n", sec["text"]) if p.strip()] or [sec["text"]]
    out, i = [], 0
    for p in paras:
        spans = []
        for sentence in troy_study.sentences(p):
            spans.append(f'<span class="ts" data-i="{i}">{html.escape(sentence)}</span>')
            i += 1
        out.append("<p>" + " ".join(spans) + "</p>")
    start = ""
    if autoplay:
        # New section: jump back to its title (Troy's own scroll area only, so
        # Safari's page doesn't move), then read from the first sentence.
        start = ("const top = () => { const sc = document.querySelector("
                 "'[data-testid=\"stAppScrollToBottomContainer\"]'); if (sc) sc.scrollTop = 0; };"
                 "[50, 400, 900, 1600].forEach(ms => setTimeout(top, ms));"
                 "setTimeout(() => speakFrom(0), 300);")
    js = READ_ALONG_JS % {"id": box_id, "rate": rate, "start": start}
    st.html(f'<div class="troy-read" id="{box_id}">{"".join(out)}</div><script>{js}</script>',
            unsafe_allow_javascript=True)


def render_study():
    s = st.session_state.study
    # A PDF handed over from the chat ("Study this section by section")
    pending = st.session_state.pop("study_load", None)
    if pending:
        load_study_pdf(pending["name"], pending["data"])
        st.rerun()

    if not s:
        st.markdown("### 📘 Study a PDF")
        st.caption("Troy reads it to you section by section while you follow along. "
                   "Tap Quiz me or Explain, or ask him anything about it.")
        st.caption("Add the PDF with Upload below or the ＋ in the message box. "
                   "Use the mic or type to ask Troy questions while you study.")
        saved = st.session_state.study_saved
        if saved:
            n = len(saved["sections"])
            if st.button(f"Continue “{saved['name']}” — section {saved['idx'] + 1} of {n}",
                         key="study_resume", icon=":material/play_arrow:", type="primary"):
                st.session_state.study = dict(saved, qa={})
                st.session_state.study_autoread = False
                st.rerun()
        if st.session_state.get("last_pdf"):
            name = st.session_state.last_pdf["name"]
            if st.button(f"Study “{name}” (the PDF you sent)", key="study_last_pdf",
                         icon=":material/description:"):
                load_study_pdf(name, st.session_state.last_pdf["data"])
                st.rerun()
        up = st.file_uploader("Add a PDF to study", type=["pdf"], key="study_upload")
        if up is not None:
            load_study_pdf(up.name, up.getvalue())
            if st.session_state.study:
                st.rerun()
        if st.button("Back to chat", key="study_back_chat", type="tertiary",
                     icon=":material/arrow_back:"):
            st.session_state.study_on = False
            st.rerun()
        return

    sections = s["sections"]
    idx = s["idx"]
    sec = sections[idx]
    n = len(sections)

    st.markdown(f'<div class="troy-study-doc">📘 {html.escape(s["name"])}</div>',
                unsafe_allow_html=True)
    st.progress((idx + 1) / n, text=f"Section {idx + 1} of {n}")
    if sec.get("group"):
        st.markdown(f'<div class="troy-study-group">{html.escape(sec["group"])}</div>',
                    unsafe_allow_html=True)
    st.markdown(f'<div class="troy-study-title">{html.escape(section_label(sec))}</div>',
                unsafe_allow_html=True)

    speed = st.segmented_control(
        "Reading speed", ["0.8×", "1×", "1.2×", "1.5×"], default="1×",
        key="read_speed", label_visibility="collapsed",
    ) or "1×"
    rate = float(speed.rstrip("×"))
    autoplay = st.session_state.pop("study_autoread", False) and auto_speak
    read_along(sec, autoplay, rate)

    nav = st.container(horizontal=True, key="study_nav", gap="small")
    if nav.button("Back", key="study_prev", icon=":material/skip_previous:", disabled=idx == 0):
        go_to_section(idx - 1)
        st.rerun()
    if nav.button("Read again", key="study_again", icon=":material/replay:"):
        st.session_state.study_autoread = True
        st.rerun()
    if nav.button("Stop", key="study_stop", icon=":material/stop:"):
        st.html("<script>window.troyAudio && window.troyAudio.stop();"
                "window.speechSynthesis && speechSynthesis.cancel();</script>",
                unsafe_allow_javascript=True)
    if nav.button("Next", key="study_next", icon=":material/skip_next:",
                  type="primary", disabled=idx >= n - 1):
        go_to_section(idx + 1)
        st.rerun()

    st.markdown('<div class="troy-study-label">Need help with this part?</div>',
                unsafe_allow_html=True)
    helprow = st.container(horizontal=True, key="study_help", gap="small")
    action = None
    if helprow.button("Quiz me", key="study_quiz", icon=":material/quiz:"):
        action = ("quiz", None)
    if helprow.button("Explain it", key="study_explain", icon=":material/lightbulb:"):
        action = ("explain", None)
    style_row = st.container(horizontal=True, key="study_styles", gap="small")
    for key, (label, _) in STUDY_STYLES.items():
        if style_row.button(label, key=f"study_style_{key}"):
            action = ("style", key)

    if action:
        kind, key = action
        try:
            with st.spinner("Troy is thinking..."):
                if kind == "quiz":
                    raw = ask_brain_once(
                        "Make ONE quiz question about this section. Pick at random between "
                        "true/false and multiple choice (3 choices). Reply with only JSON: "
                        '{"question": "...", "choices": ["..."], "answer_index": 0, '
                        '"why": "one sentence pointing to what the section says"}',
                        section_for_brain(sec), max_tokens=400)
                    quiz = parse_quiz(raw)
                    add_study_answer("quiz", "Quiz me", "", quiz=quiz)
                elif kind == "explain":
                    ans = ask_brain_once(
                        "Explain this section in plain English in under 150 words: what it "
                        "means and what it looks like on the job.", section_for_brain(sec))
                    add_study_answer("explain", "Explain it", ans)
                else:
                    label, instruction = STUDY_STYLES[key]
                    ans = ask_brain_once(instruction, section_for_brain(sec), max_tokens=900)
                    add_study_answer("style", label, ans)
        except Exception as e:
            add_study_answer("error", "", explain_error(e))
        st.rerun()

    # Answers for this section
    for j, item in enumerate(s["qa"].get(str(idx), [])):
        with st.chat_message("assistant"):
            if item["kind"] == "quiz" and item.get("quiz"):
                qz = item["quiz"]
                st.markdown(f"**Quiz:** {qz['question']}")
                if qz["picked"] is None:
                    row = st.container(horizontal=True, key=f"quizrow_{idx}_{j}", gap="small")
                    for c_i, choice in enumerate(qz["choices"]):
                        if row.button(choice, key=f"quiz_{idx}_{j}_{c_i}"):
                            qz["picked"] = c_i
                            right = c_i == qz["answer"]
                            verdict = ("✅ That's right. " if right else
                                       f"❌ Not quite — it's “{qz['choices'][qz['answer']]}”. ")
                            item["a"] = verdict + qz["why"]
                            item["autoplay"] = auto_speak
                            if (auto_speak and use_human_voice and api_key
                                    and not st.session_state.get("tts_off_today")):
                                tmp = {"text": item["a"]}
                                make_voice(tmp)
                                item.update({k: tmp[k] for k in ("audio", "voice_note") if k in tmp})
                            st.rerun()
                if item["a"]:
                    st.write(item["a"])
            else:
                if item["q"] and item["kind"] in ("ask",):
                    st.caption(f"You asked: {item['q']}")
                elif item["q"]:
                    st.caption(item["q"])
                st.write(item["a"])
            if item["a"]:
                ap = item.pop("autoplay", False) and auto_speak
                if item.get("audio"):
                    st.audio(item["audio"], format="audio/wav")
                    if ap:
                        play_voice(item["audio"])
                else:
                    if item.get("voice_note"):
                        st.caption(item["voice_note"])
                    speak_reply(item["a"], autoplay=ap)

    if st.button("Close this PDF", key="study_close", type="tertiary", icon=":material/close:"):
        st.session_state.study = None
        st.rerun()


def ask_study_question(question):
    s = st.session_state.study
    sec = s["sections"][s["idx"]]
    recent = s["qa"].get(str(s["idx"]), [])[-3:]
    earlier = "\n".join(f"Paul: {i['q']}\nTroy: {i['a']}" for i in recent if i["kind"] == "ask")
    task = (("Earlier questions about this section:\n" + earlier + "\n\n") if earlier else "") + \
        f"Paul asks: {question}\nAnswer from the section. If he asks about a word or a " \
        "sentence, explain it simply."
    try:
        with st.spinner("Troy is thinking..."):
            ans = ask_brain_once(task, section_for_brain(sec))
        add_study_answer("ask", question, ans)
    except Exception as e:
        add_study_answer("error", question, explain_error(e))


if st.session_state.study_on:
    render_study()

if st.session_state.study_on and (prompt or send_voice or attached):
    pdfs = [f for f in attached if (f.name or "").lower().endswith(".pdf")]
    if not brain and not pdfs:
        st.warning("Add Troy's Claude key (or a Gemini key) in the sidebar first, then try again.")
    elif pdfs:
        load_study_pdf(pdfs[0].name, pdfs[0].getvalue())
        st.rerun()
    elif not st.session_state.study:
        st.warning("Add a PDF first: tap ＋ or use “Add a PDF to study”.")
    elif send_voice:
        try:
            with st.spinner("Listening..."):
                words = transcribe(voice_audio.getvalue(), voice_audio.type or "audio/wav")
            ask_study_question(((prompt + " ") if prompt else "") + words)
            st.rerun()
        except Exception:
            st.warning("Troy couldn't make out that recording. Try again, or tap the 🎤 on "
                       "your keyboard and talk — it types for you.")
    else:
        ask_study_question(prompt)
        st.session_state.hide_keyboard = True
        st.rerun()
elif prompt or send_voice or ask_about_files:
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
