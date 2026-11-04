import html
import io
import os
import re
import wave
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

import streamlit as st
from google import genai

MAX_PROMPT_CHARS = 8_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 5

# File types Troy can read, and the type name Gemini expects for each.
FILE_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
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
                if (window.speechSynthesis) {{
                    window.speechSynthesis.cancel();
                }}
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
    .troy-mark-small {
        margin-bottom: 0.75rem;
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


if not st.session_state.get("messages"):
    st.markdown(
        f'''<div class="troy-welcome">
            <div class="troy-mark">TROY</div>
            <h1>{greeting()}</h1>
        </div>''',
        unsafe_allow_html=True,
    )
else:
    st.markdown('<div class="troy-mark troy-mark-small">TROY</div>', unsafe_allow_html=True)

# ---- Find Troy's key ----
# 1. Streamlit Secret (used when deployed on Streamlit Cloud)
# 2. Environment variable (if you ever set one)
# 3. Sidebar box (handy when running locally)
api_key = ""
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    api_key = os.environ.get("GEMINI_API_KEY", "")

st.sidebar.title("TROY")
st.sidebar.write("Prototype v0.2")
auto_speak = st.sidebar.checkbox("Automatically read Troy's replies aloud", value=True)
use_human_voice = st.sidebar.checkbox(
    "Human voice (Gemini)",
    value=True,
    help="Uses Gemini's free voice model: one extra free call per reply, on its own "
    "daily allowance. If it's unavailable, Troy falls back to your device's voice.",
)
voice_label = st.sidebar.selectbox(
    "Troy's voice", list(TTS_VOICES), disabled=not use_human_voice
)

if not api_key:
    api_key = st.sidebar.text_input("Paste your free Gemini key:", type="password")

# ---- Wake the brain up once we have a key ----
if api_key:
    if "chat" not in st.session_state or st.session_state.get("key") != api_key:
        # Keep the client in session_state. If it is a throwaway variable,
        # Python deletes it after this run and the chat fails with
        # "client has been closed" on the next message.
        st.session_state.client = genai.Client(api_key=api_key)
        st.session_state.chat = st.session_state.client.chats.create(
            model="gemini-2.5-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=TROY_INSTRUCTIONS,
            ),
        )
        st.session_state.key = api_key
        st.session_state.messages = []
    st.sidebar.write("AI brain: ON")
else:
    st.sidebar.write("AI brain: waiting for key")

st.sidebar.write("Chat: on")
st.sidebar.write("Memory: on (this session)")
st.sidebar.write("File uploads: on (PDF, photos, text)")

# Make sure the history list exists.
if "messages" not in st.session_state:
    st.session_state.messages = []

# ---- Show the conversation so far ----
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["text"])
        if msg["role"] == "assistant":
            autoplay = msg.pop("autoplay", False)
            if msg.get("audio"):
                st.audio(msg["audio"], format="audio/wav", autoplay=autoplay)
            else:
                if msg.get("voice_note"):
                    st.caption(msg["voice_note"])
                speak_reply(msg["text"], autoplay=autoplay)

prompt = st.chat_input("How can I help you today?", max_chars=MAX_PROMPT_CHARS)
if "voice_key" not in st.session_state:
    st.session_state.voice_key = 0
voice_audio = st.audio_input(
    "Or record a voice message", key=f"voice_{st.session_state.voice_key}"
)
send_voice = st.button("Send voice message", disabled=voice_audio is None)

if "file_key" not in st.session_state:
    st.session_state.file_key = 0
with st.expander("📎 Attach a PDF, photo, or text file"):
    attached = st.file_uploader(
        "Troy reads these along with your next message",
        type=list(FILE_TYPES),
        accept_multiple_files=True,
        key=f"files_{st.session_state.file_key}",
    ) or []
    ask_about_files = st.button("Ask Troy about these files", disabled=not attached)


def explain_error(e):
    """Turn an error into a short, honest message without leaking details."""
    code = getattr(e, "code", None)
    if code == 429:
        return "Troy hit today's free Gemini limit (429). Try again later or tomorrow."
    if code in (400, 401, 403):
        return f"Gemini rejected the request ({code}). Check that the API key is correct."
    if code is not None and code >= 500:
        return f"Gemini's servers had a problem ({code}). Try again in a minute."
    return f"Troy had a problem ({type(e).__name__}). Try again."


def file_parts(files):
    """Turn uploaded files into pieces Gemini can read. Returns (parts, problem)."""
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
        parts.append(genai.types.Part.from_bytes(data=data, mime_type=mime))
    return parts, None


def file_label(files):
    return "".join(f"\n\n📎 {f.name}" for f in files)


def send_to_troy(user_text, message):
    st.session_state.messages.append({"role": "user", "text": user_text})
    try:
        response = st.session_state.chat.send_message(message)
        answer = response.text
        if not isinstance(answer, str) or not answer.strip():
            answer = "I couldn't generate a text reply. Please try asking again."
        ok = True
    except Exception as e:
        answer = explain_error(e)
        ok = False
    reply = {"role": "assistant", "text": answer, "autoplay": auto_speak}
    if ok and use_human_voice and not st.session_state.get("tts_off_today"):
        try:
            with st.spinner("Troy is getting his voice ready..."):
                reply["audio"] = human_voice(
                    st.session_state.client, answer, TTS_VOICES[voice_label]
                )
        except Exception as e:
            if getattr(e, "code", None) == 429:
                # Voice allowance used up: stop trying for the rest of this visit.
                st.session_state.tts_off_today = True
                reply["voice_note"] = "Human voice used up for today — using your device's voice."
            else:
                reply["voice_note"] = (
                    f"Human voice unavailable ({type(e).__name__}) — using your device's voice."
                )
    st.session_state.messages.append(reply)


if prompt or send_voice or ask_about_files:
    parts, problem = file_parts(attached)
    if not api_key:
        st.warning("Paste your free Gemini key in the sidebar first, then try again.")
    elif problem:
        st.warning(problem)
    elif send_voice:
        audio_bytes = voice_audio.getvalue()
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            st.warning("That recording is too large. Please record a shorter message.")
        else:
            audio_part = genai.types.Part.from_bytes(
                data=audio_bytes,
                mime_type=voice_audio.type or "audio/wav",
            )
            send_to_troy(
                "🎤 Voice message" + file_label(attached),
                parts
                + [audio_part, "This is Paul's voice message. Reply to what they said."],
            )
            # New keys = fresh recorder and uploader, so nothing is sent twice.
            st.session_state.voice_key += 1
            if attached:
                st.session_state.file_key += 1
            st.rerun()
    else:
        text = prompt or "Please read the attached file(s) and help me understand them."
        send_to_troy(text + file_label(attached), parts + [text] if parts else text)
        if attached:
            st.session_state.file_key += 1
        st.rerun()
