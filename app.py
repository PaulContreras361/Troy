import streamlit as st
from openai import OpenAI

# 1. Setup the connection to the Brain (OpenAI)
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# 2. Memory: Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# 3. UI: Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. Handle new user input
if prompt := st.chat_input("What is on your mind?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 5. Generate and display TROY's response
    with st.chat_message("assistant"):
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=st.session_state.messages
        )
        full_response = response.choices[0].message.content
        st.markdown(full_response)
    
    st.session_state.messages.append({"role": "assistant", "content": full_response})