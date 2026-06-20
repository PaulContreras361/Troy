import streamlit as st

st.set_page_config(
    page_title="TROY",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 TROY")
st.subheader("Personal AI Assistant")

st.write("Welcome, Paul!")

user_input = st.text_input("Talk to TROY:")

if user_input:
    st.success(f"You said: {user_input}")

st.sidebar.title("TROY")
st.sidebar.write("Prototype v0.1")
st.sidebar.write("✅ Chat")
st.sidebar.write("🔜 Memory")
st.sidebar.write("🔜 File Uploads")
st.sidebar.write("🔜 AI Brain")

