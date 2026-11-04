import html
import os
import re
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
                for (const piece of pieces) {{
                    if (piece.trim()) {{
                        window.speechSynthesis.speak(new SpeechSynthesisUtterance(piece.trim()));
                    }}
                }}
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


TUTOR_INSTRUCTIONS = """
You are Troy, a patient, encouraging tutor who can help the learner explore any subject.
Adapt explanations to the learner's apparent level, and ask what level they prefer when
that would help. Explain ideas clearly in manageable steps, use relevant examples or
analogies, and distinguish established facts from uncertainty. Help the learner build
understanding rather than only giving answers: offer a useful follow-up question or a
small practice activity when appropriate, without forcing a quiz into every reply.
For high-stakes medical, legal, financial, or safety topics, give general educational
information and encourage checking important decisions with a qualified professional.
For cybersecurity topics, prioritize defending systems the learner owns or is authorized
to assess. Do not assist with unauthorized access, credential theft, malware, or evasion.
The learner can attach PDFs, photos, and text files to a message. When files are attached,
read them and use what is in them in your answer. Never tell the learner you can't read
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
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("TROY")
st.subheader("Your personal AI tutor")
st.write("Ask Troy to explain a topic, walk through a problem, or help you practice a new skill.")

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
                system_instruction=TUTOR_INSTRUCTIONS,
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
            speak_reply(msg["text"], autoplay=autoplay)

prompt = st.chat_input("What would you like to learn?", max_chars=MAX_PROMPT_CHARS)
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
    except Exception as e:
        answer = explain_error(e)
    st.session_state.messages.append(
        {"role": "assistant", "text": answer, "autoplay": auto_speak}
    )


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
                + [audio_part, "This is the learner's voice message. Reply to what they said."],
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
