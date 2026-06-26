import os
import streamlit as st
from google import genai

st.set_page_config(page_title="TROY", layout="wide")

st.title("TROY")
st.subheader("Personal AI Assistant")
st.write("Welcome, Paul!")

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
        st.session_state.chat = client.chats.create(model="gemini-2.5-flash")
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
prompt = st.chat_input("Talk to TROY:")

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
