import html
import os
from uuid import uuid4

import streamlit as st
from google import genai

MAX_PROMPT_CHARS = 8_000
MAX_AUDIO_BYTES = 10 * 1024 * 1024


def speak_reply(text, autoplay=False):
    container_id = f"troy-speech-{uuid4().hex}"
    safe_text = html.escape(str(text or ""))
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
                window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
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
"""

st.set_page_config(page_title="TROY", layout="centered")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 54rem;
        padding: 2.5rem 1.5rem 6rem;
    }

    [data-testid="stChatMessage"] {
        padding: 1rem;
        border-radius: 0.75rem;
    }

    @media (max-width: 640px) {
        .block-container {
            padding: 1rem 0.75rem calc(5rem + env(safe-area-inset-bottom));
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
st.sidebar.write("File uploads: soon")

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
voice_audio = st.audio_input("Or record a voice message")
send_voice = st.button("Send voice message", disabled=voice_audio is None)


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


if prompt or send_voice:
    if not api_key:
        st.warning("Paste your free Gemini key in the sidebar first, then try again.")
    elif send_voice:
        audio_bytes = voice_audio.getvalue()
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            st.warning("That recording is too large. Please record a shorter message.")
        else:
            audio_part = genai.types.Part.from_bytes(
                data=audio_bytes,
                mime_type=voice_audio.type or "audio/wav",
            )
            send_to_troy("🎤 Voice message", audio_part)
            st.rerun()
    else:
        send_to_troy(prompt, prompt)
        st.rerun()
