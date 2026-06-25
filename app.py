import base64
import io
import json
import os
from pathlib import Path

import streamlit as st
from openai import OpenAI
from PIL import Image

HISTORY_FILE = Path(__file__).resolve().parent / "chat_history.json"
MEMORY_FILE = Path(__file__).resolve().parent / "memory.json"
ICON_FILE = None
for icon_name in ["Troy.ico", "troy_icon.svg"]:
    candidate = Path(__file__).resolve().parent / icon_name
    if candidate.exists():
        ICON_FILE = candidate
        break

OPENAI_ENV_KEY = "OPENAI_API_KEY"

DEFAULT_SYSTEM_PROMPT = (
    "You are Troy, a friendly and warm AI assistant. Keep responses short, conversational, and fun. Use 1-2 sentences unless asked for more. Be like chatting with a friend, not reading a manual."
)

TROY_SYSTEM_PROMPT = """
You are TROY, a friendly engineering buddy who gets straight to the point.
Keep responses short, punchy, and conversational (2-3 sentences max). Be witty and sarcastic but always helpful.
When discussing ideas:
- Point out the cool parts
- Flag any obvious issues
- Suggest one quick fix or iteration
Talk like a friend brainstorming, not a textbook. Make it fun!
"""

ENGINEERING_SYSTEM_PROMPT = TROY_SYSTEM_PROMPT
PERSONA_MODES = ["Engineering Inventor", "Default"]

page_icon = "🤖"
if ICON_FILE is not None:
    page_icon = str(ICON_FILE)

st.set_page_config(
    page_title="Troy Engineering Engine",
    page_icon=page_icon,
    layout="wide",
)

# Initialize session state before accessing it
if "active_project" not in st.session_state:
    st.session_state.projects = []
    st.session_state.active_project = None

st.title("Troy AI")
st.write("A personal AI assistant powered by OpenAI.")
project_display = st.session_state.active_project or "No active project"
st.subheader(f"Working on: {project_display}")

st.info(
    "Troy is a web app. In GitHub Codespaces, open port 8501 from the Ports panel and use the forwarded preview URL. "
    "Do not use malformed URLs such as `https://-8501.app.github.dev/` or `http://localhost:8501` from a different machine."
)


def load_history() -> list[dict[str, str]]:
    if HISTORY_FILE.exists():
        try:
            with HISTORY_FILE.open("r", encoding="utf-8") as history_file:
                data = json.load(history_file)
            if isinstance(data, list):
                return [
                    item
                    for item in data
                    if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
                ]
        except Exception:
            pass
    return []


def save_history() -> None:
    try:
        messages = [message for message in st.session_state.messages if message["role"] != "system"]
        with HISTORY_FILE.open("w", encoding="utf-8") as history_file:
            json.dump(messages, history_file, indent=2)
    except Exception:
        pass


def clear_history_file() -> None:
    if HISTORY_FILE.exists():
        try:
            HISTORY_FILE.unlink()
        except Exception:
            pass


def load_memory() -> list[str]:
    if MEMORY_FILE.exists():
        try:
            with MEMORY_FILE.open("r", encoding="utf-8") as memory_file:
                data = json.load(memory_file)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, str)]
        except Exception:
            pass
    return []


def save_memory(memory: list[str]) -> None:
    try:
        with MEMORY_FILE.open("w", encoding="utf-8") as memory_file:
            json.dump(memory, memory_file, indent=2)
    except Exception:
        pass


def clear_memory_file() -> None:
    if MEMORY_FILE.exists():
        try:
            MEMORY_FILE.unlink()
        except Exception:
            pass


def add_memory_item(item: str) -> None:
    item = item.strip()
    if not item:
        return
    if item not in st.session_state.memory:
        st.session_state.memory.append(item)
        save_memory(st.session_state.memory)


def remove_memory_item(subject: str) -> bool:
    subject = subject.strip().lower()
    if not subject:
        return False
    before = len(st.session_state.memory)
    st.session_state.memory = [item for item in st.session_state.memory if subject not in item.lower()]
    if len(st.session_state.memory) != before:
        save_memory(st.session_state.memory)
        return True
    return False


def process_memory_command(prompt_text: str) -> str | None:
    normalized = prompt_text.strip()
    lower_text = normalized.lower()

    if "forget everything" in lower_text or "forget all" in lower_text:
        st.session_state.memory = []
        clear_memory_file()
        return "Memory cleared."

    if lower_text.startswith("forget ") or lower_text.startswith("forget that "):
        subject = normalized.split("forget", 1)[1].strip()
        if subject:
            removed = remove_memory_item(subject)
            return "Removed matching memory." if removed else "No matching memory found to forget."

    if lower_text.startswith("remember "):
        remembered = normalized[len("remember ") :].strip(" .")
        if remembered:
            add_memory_item(remembered)
            return f"Saved memory: {remembered}"

    if lower_text.startswith("save "):
        remembered = normalized[len("save ") :].strip(" .")
        if remembered:
            add_memory_item(remembered)
            return f"Saved memory: {remembered}"

    return None


def build_system_message() -> dict[str, str]:
    persona_mode = st.session_state.get("persona_mode", "Engineering Inventor")
    message = ENGINEERING_SYSTEM_PROMPT if persona_mode == "Engineering Inventor" else DEFAULT_SYSTEM_PROMPT

    memory_items = st.session_state.get("memory", [])
    if memory_items:
        memory_lines = "\n".join(f"- {item}" for item in memory_items)
        message += f"\n\nRemember these user details for future responses:\n{memory_lines}"

    return {"role": "system", "content": message}


def verify_design_integrity(response_text: str) -> dict:
    """Audit the generated response for engineering integrity and clarity."""
    issues = []
    
    if not response_text.strip():
        issues.append("Response is empty.")
    
    if len(response_text) < 20:
        issues.append("Response is too brief.")
    
    return {
        "status": "FAIL" if issues else "PASS",
        "issues": issues,
        "text": response_text,
    }


def refine_design(draft_response: str, audit_issues: list[str]) -> str:
    """Refine the response based on audit feedback."""
    if not client:
        return draft_response
    
    refinement_prompt = f"""
Your previous response had these gaps:
{chr(10).join(f"- {issue}" for issue in audit_issues)}

Please refine your response to address these gaps:
1. Add more depth if needed
2. Include risk analysis or trade-offs
3. Probe for clarifications
4. Be more action-oriented

Original response:
{draft_response}

Refined response:
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": refinement_prompt}],
            max_tokens=250,
        )
        if hasattr(response.choices[0], "message"):
            return response.choices[0].message.content or draft_response
        return draft_response
    except Exception:
        return draft_response


def get_troy_response(user_input: str, conversation_history: list[dict[str, str]] | None = None, model_name: str = "gpt-4o-mini") -> str:
    """
    Generate a Troy response with built-in design audit and self-correction.
    
    Workflow:
    1. Draft - Generate initial response
    2. Audit - Verify design integrity
    3. Gate - If failed, refine; otherwise return
    """
    messages = [build_system_message()]
    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_input})

    # Draft: Generate initial response
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=250,
        )
        choice = response.choices[0]
        if hasattr(choice, "message"):
            draft = getattr(choice.message, "content", "") or ""
        else:
            draft = getattr(choice, "text", "") or ""
    except Exception:
        return ""

    # Audit: Verify design integrity
    audit = verify_design_integrity(draft)

    # Gate: Self-correct if audit failed
    if audit["status"] == "FAIL":
        refined = refine_design(draft, audit["issues"])
        return refined

    return draft


def init_session_state() -> None:
    defaults = {
        "memory": load_memory(),
        "persona_mode": "Engineering Inventor",
        "prompt_input": "",
        "pending_image": None,
        "pending_audio_text": None,
        "tts_enabled": False,
        "image_mode": False,
        "media_panel_open": False,
        "projects": [],
        "active_project": None,
        "new_project_name": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if st.session_state.active_project is None:
        st.session_state.active_project = st.session_state.projects[0] if st.session_state.projects else "Untitled Project"

    if "messages" not in st.session_state:
        previous_messages = load_history()
        system_message = build_system_message()
        st.session_state.messages = [system_message, *previous_messages] if previous_messages else [system_message]


init_session_state()

with st.sidebar:
    st.title("Troy AI")
    st.header("Recent Projects")

    for proj in st.session_state.projects:
        if proj == st.session_state.active_project:
            st.markdown(f"**▶ {proj}**")
        else:
            if st.button(proj, key=f"project_{proj}", use_container_width=True):
                st.session_state.active_project = proj
                st.experimental_rerun()

    st.divider()

    st.text_input(
        "New project name",
        value=st.session_state.new_project_name,
        key="new_project_name",
        placeholder="Enter project name",
        label_visibility="collapsed",
    )
    if st.button("+ New Project", use_container_width=True):
        new_name = st.session_state.new_project_name.strip()
        if new_name:
            if new_name not in st.session_state.projects:
                st.session_state.projects.append(new_name)
                st.session_state.active_project = new_name
                st.session_state.new_project_name = ""
                st.experimental_rerun()
            else:
                st.warning("A project with that name already exists.")
        else:
            st.warning("Enter a project name first.")

    st.divider()

    st.header("Settings")
    st.text_input(
        "OpenAI API Key",
        type="password",
        value=st.session_state.get("openai_api_key", ""),
        key="openai_api_key",
        placeholder="Paste your OpenAI API key here",
        help="You can also set OPENAI_API_KEY as an environment variable or add it to .streamlit/secrets.toml.",
    )
    model = st.selectbox(
        "Model",
        options=["gpt-3.5-turbo", "gpt-4o-mini"],
        index=0,
        help="Choose the OpenAI model to power Troy AI.",
    )
    st.checkbox("Speak responses", key="tts_enabled", help="Enable text-to-speech for Troy's replies.")
    st.checkbox("Image generation mode", key="image_mode", help="Generate an image instead of a chat response.")
    st.selectbox(
        "Troy persona",
        options=PERSONA_MODES,
        key="persona_mode",
        help="Choose how Troy frames his responses.",
    )

    if st.button("Clear chat"):
        st.session_state.messages = [build_system_message()]
        st.experimental_rerun()

    if st.button("Clear saved history"):
        clear_history_file()
        st.success("Saved history cleared.")
        st.session_state.messages = [build_system_message()]
        st.experimental_rerun()

    if st.button("Clear saved memory"):
        clear_memory_file()
        st.session_state.memory = []
        st.success("Saved memory cleared.")

    if HISTORY_FILE.exists():
        st.info(f"Saved history loaded from {HISTORY_FILE.name}.")
    if MEMORY_FILE.exists():
        st.info(f"Saved memory loaded from {MEMORY_FILE.name}.")

    if st.session_state.memory:
        st.markdown("**Memory items**")
        for item in st.session_state.memory:
            st.write(f"- {item}")

try:
    secrets_key = st.secrets.get(OPENAI_ENV_KEY)
except Exception:
    secrets_key = None

openai_api_key = st.session_state.openai_api_key or secrets_key or os.getenv(OPENAI_ENV_KEY, "")
if not openai_api_key:
    st.warning("Enter your OpenAI API key in the sidebar or configure OPENAI_API_KEY.")

client = OpenAI(api_key=openai_api_key) if openai_api_key else None

for message in st.session_state.messages[1:]:
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        st.chat_message("assistant").write(message["content"])

media_open = st.query_params.get("media", "false").lower() == "true"
if media_open != st.session_state.media_panel_open:
    st.session_state.media_panel_open = media_open

if st.session_state.media_panel_open:
    toggle_query = "?media=false"
    toggle_label = "✕"
else:
    toggle_query = "?media=true"
    toggle_label = "🎙️"

st.markdown(
    f"""
    <style>
        .media-float {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 12px;
        }}
        .media-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            border: none;
            background: #111;
            color: white;
            font-size: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
            cursor: pointer;
            text-decoration: none;
        }}
        .media-panel {{
            width: 320px;
            background: rgba(255, 255, 255, 0.98);
            border-radius: 18px;
            padding: 16px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
            border: 1px solid rgba(0, 0, 0, 0.08);
        }}
        .media-panel h3 {{
            margin: 0 0 12px;
            font-size: 16px;
        }}
        .media-panel label {{
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
        }}
    </style>
    <div class="media-float">
        <a href="{toggle_query}" class="media-button">{toggle_label}</a>
    </div>
    """,
    unsafe_allow_html=True,
)

if st.session_state.media_panel_open:
    st.markdown(
        """
        <div class="media-float">
            <div class="media-panel">
                <h3>Media Controls</h3>
        """,
        unsafe_allow_html=True,
    )
    image_file = st.file_uploader(
        "Upload an image to attach to your next message",
        type=["png", "jpg", "jpeg", "gif"],
        key="image_uploader",
    )
    if image_file is not None:
        try:
            image = Image.open(image_file)
            st.image(image, caption="Uploaded image", width=260)

            buf = io.BytesIO()
            image.save(buf, format="PNG")
            img_bytes = buf.getvalue()
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")

            st.session_state.pending_image = img_b64
            st.success("Image ready to attach to your next prompt.")
        except Exception as exc:
            st.error(f"Failed to process image: {exc}")

    if hasattr(st, "audio_input"):
        audio_file = st.audio_input("🎙️ Record a voice message")
    else:
        audio_file = st.file_uploader("Upload a voice note", type=["wav", "mp3", "m4a", "ogg"], key="audio_uploader")

    st.markdown("</div></div>", unsafe_allow_html=True)
else:
    image_file = None
    audio_file = None

if audio_file is not None:
    if client is None:
        st.warning("OpenAI API key is required for voice transcription.")
    else:
        try:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
            transcribed_text = getattr(transcription, "text", None)
            if transcribed_text is None and isinstance(transcription, dict):
                transcribed_text = transcription.get("text")

            if transcribed_text:
                st.success("Transcription complete")
                st.write(transcribed_text)
                if st.button("Use transcription as prompt"):
                    st.session_state.prompt_input = transcribed_text
            else:
                st.error("Could not extract transcription text.")
        except Exception as exc:
            st.error(f"Transcription failed: {exc}")


def submit_prompt(user_input: str | None = None) -> None:
    if user_input is None:
        prompt_text = st.session_state.prompt_input.strip()
    else:
        prompt_text = user_input.strip()
    
    if not prompt_text:
        return

    memory_response = process_memory_command(prompt_text)
    if memory_response is not None:
        st.info(memory_response)
        return

    if st.session_state.pending_image:
        st.session_state.messages.append(
            {
                "role": "user",
                "content": f"[ImageAttached]\ndata:image/png;base64,{st.session_state.pending_image}",
            }
        )
        st.session_state.pending_image = None

    if client is None:
        st.error("OpenAI API key is required to send messages.")
        return

    with st.spinner("Troy is thinking..."):
        try:
            if st.session_state.image_mode or "draw" in prompt_text.lower() or "generate image" in prompt_text.lower():
                try:
                    image_response = client.images.generate(
                        model="gpt-image-1",
                        prompt=prompt_text,
                        size="1024x1024",
                    )
                    image_data = None
                    if hasattr(image_response, "data") and image_response.data:
                        first = image_response.data[0]
                        image_data = getattr(first, "b64_json", None) or (
                            first.get("b64_json") if isinstance(first, dict) else None
                        )
                    if image_data:
                        image_bytes = base64.b64decode(image_data)
                        st.image(image_bytes, caption="Generated image", use_column_width=True)
                        st.session_state.messages.append(
                            {"role": "assistant", "content": "Generated an image for your request."}
                        )
                    else:
                        st.error("Image generation returned no image data.")
                except Exception as image_exc:
                    st.error(f"Image generation failed: {image_exc}")
            else:
                st.session_state.messages[0] = build_system_message()
                conversation_history = st.session_state.messages[1:]
                reply = get_troy_response(
                    prompt_text,
                    conversation_history=conversation_history,
                    model_name=model,
                )
                st.session_state.messages.append({"role": "user", "content": prompt_text})
                st.session_state.messages.append({"role": "assistant", "content": reply})
                save_history()
                st.chat_message("assistant").write(reply)

                if st.session_state.tts_enabled and reply:
                    try:
                        tts_response = client.audio.speech.create(
                            model="tts-1",
                            voice="alloy",
                            input=reply,
                        )
                        audio_bytes = None
                        if hasattr(tts_response, "audio"):
                            audio_bytes = tts_response.audio
                        elif isinstance(tts_response, dict):
                            audio_bytes = tts_response.get("audio")
                        if audio_bytes is not None:
                            if isinstance(audio_bytes, str):
                                audio_bytes = base64.b64decode(audio_bytes)
                            st.audio(audio_bytes)
                    except Exception as tts_exc:
                        st.warning(f"TTS failed: {tts_exc}")
        except Exception as exc:
            st.error(f"OpenAI request failed: {exc}")


prompt_text = st.chat_input("Ask Troy something...", key="prompt_input")
if prompt_text:
    submit_prompt(prompt_text)
