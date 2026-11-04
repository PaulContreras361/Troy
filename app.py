import html
import os
import streamlit as st
import streamlit.components.v1 as components
from google import genai

def speak_reply(text, autoplay=False):
    safe_text = html.escape(text)
    start_speech = "speak();" if autoplay else ""
    components.html(
        f"""
        <button type="button" onclick="speak()">🔊 Read aloud</button>
        <button type="button" onclick="window.speechSynthesis.cancel()">⏹ Stop speaking</button>
        <span id="speech-text" style="display:none">{safe_text}</span>
        <script>
        function speak() {{
            if (!("speechSynthesis" in window)) {{
                return;
            }}
            window.speechSynthesis.cancel();
            const text = document.getElementById("speech-text").textContent;
            window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
        }}
        if (!("speechSynthesis" in window)) {{
            document.querySelectorAll("button").forEach((button) => {{
                button.disabled = true;
                button.textContent = "Speech is not supported in this browser";
            }});
        }}
        {start_speech}
        </script>
        """,
        height=48,
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
        client = genai.Client(api_key=api_key)
        st.session_state.chat = client.chats.create(
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

prompt = st.chat_input("What would you like to learn?")
voice_audio = st.audio_input("Or record a voice message")
send_voice = st.button("Send voice message", disabled=voice_audio is None)


def send_to_troy(user_text, message):
    st.session_state.messages.append({"role": "user", "text": user_text})
    try:
        answer = st.session_state.chat.send_message(message).text
    except Exception as e:
        answer = "Troy had a problem: " + str(e)
    st.session_state.messages.append(
        {"role": "assistant", "text": answer, "autoplay": auto_speak}
    )


if prompt or send_voice:
    if not api_key:
        st.warning("Paste your free Gemini key in the sidebar first, then try again.")
    elif send_voice:
        audio_part = genai.types.Part.from_bytes(
            data=voice_audio.getvalue(),
            mime_type=voice_audio.type or "audio/wav",
        )
        send_to_troy("🎤 Voice message", audio_part)
        st.rerun()
    else:
        send_to_troy(prompt, prompt)
        st.rerun()
