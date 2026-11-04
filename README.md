# Troy

Personal AI tutor powered by Streamlit and Gemini. Troy can explain topics, walk through problems, and help you practice.

## Requirements

- Python 3.11+ recommended
- `streamlit`
- `google-genai`

## Setup

1. Install dependencies:

```bash
git clone https://github.com/PaulContreras361/Troy.git
cd Troy
python3 -m pip install -r requirements.txt
```

2. Provide your Gemini API key:

- Set the environment variable:

```bash
export GEMINI_API_KEY="your-api-key"
```

- Or paste it in the Streamlit sidebar after launching the app.

Alternatively, persist the key locally so you don't need to re-enter it:

- Create a file at `.streamlit/secrets.toml` with this content (do NOT commit it):

```toml
GEMINI_API_KEY = "your-api-key"
```

Streamlit loads keys from `.streamlit/secrets.toml`; Troy also accepts the `GEMINI_API_KEY` environment variable or a key entered in the sidebar.

## Run

```bash
python -m streamlit run app.py
```

On Windows, run that from your Troy folder in CMD. `python -m` works even when `streamlit` isn't on your PATH.

## GitHub Codespaces

If you are running this project in GitHub Codespaces:

- Open the `Ports` panel
- Find port `8501` or `8503`
- Click the forwarded preview/public URL for that port
- Do not manually type malformed URLs such as `https://-8501.app.github.dev/`

## Streamlit Community Cloud Deployment

Deploy Troy to Streamlit Community Cloud to use it from both your laptop and iPhone.

1. Make sure `app.py` is in the repository root.
2. Connect this GitHub repository to Streamlit Community Cloud and deploy `app.py`.
3. Add your Gemini API key in the Streamlit Cloud secrets manager:

```toml
GEMINI_API_KEY = "your-api-key"
```

4. Open the deployed app URL in a browser on either device. On iPhone, open it in Safari, tap **Share**, then **Add to Home Screen**.

Do not commit your actual `secrets.toml` to the repository. Check the deployment's access settings before sharing its URL or entering sensitive information. Chat history is kept only in the current browser session and is not synced between devices.

## Security

- Troy limits prompts to 8,000 characters and recordings/uploads to 10 MB.
- Keep the Gemini key in Streamlit secrets or an environment variable; never put real keys in source code or commit them.
- Restrict access to deployed apps that use private credentials. Use HTTPS and keep your host and dependencies updated.
- Troy can help with defensive security and authorized assessments, but will not assist with unauthorized access, credential theft, malware, or evasion.
- These safeguards reduce common risks but cannot guarantee that an app or device will never be compromised. Do not submit passwords, API keys, or other sensitive information in chat.

## Usage

- Ask Troy about a topic, request a step-by-step explanation, or ask for practice questions.
- Use **Record a voice message** to speak to Troy, then select **Send voice message**. Replies are read aloud automatically by default; use the sidebar checkbox to turn this off, or select **Stop speaking** below a reply at any time. **Read aloud** replays a reply.
- Tap **📎 Attach a PDF, photo, or text file** to have Troy read a PDF, a photo (iPhone camera or library), or a .txt/.csv/.md file. Type a question and send, or tap **Ask Troy about these files**. Up to 5 files, 10 MB each.
- **Human voice:** Troy speaks his replies in a natural Gemini voice (sidebar: **Human voice (Gemini)** and **Troy's voice**). It's free but uses one extra Gemini call per reply on the voice model's own daily allowance. If that runs out or fails, Troy says so and uses your device's best voice instead.
- **Better device voice on iPhone:** Settings → Accessibility → Spoken Content → Voices → English → download a **Premium** or **Enhanced** voice (e.g. Ava or Evan). Troy picks it automatically.
- Use the sidebar to add a Gemini API key.
- The app uses Gemini 2.5 Flash.
- Troy adapts explanations and may be mistaken; verify important information, especially for high-stakes decisions.
- Voice recording requires microphone permission and browser support; spoken replies use your browser's text-to-speech voices and may be restricted by browser autoplay settings.
