import os
import streamlit as st
from google import genai

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
    st.chat_message(msg["role"]).write(msg["text"])

# ---- Talk to Troy ----
prompt = st.chat_input("What would you like to learn?")

if prompt:
    if not api_key:
        st.warning("Paste your free Gemini key in the sidebar first, then try again.")
    else:
        st.chat_message("user").write(prompt)
        st.session_state.messages.append({"role": "user", "text": prompt})
        try:
            answer = st.session_state.chat.send_message(prompt).text
        except Exception as e:
            answer = "Troy had a problem: " + str(e)
        st.chat_message("assistant").write(answer)
        st.session_state.messages.append({"role": "assistant", "text": answer})
