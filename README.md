# Troy

Paul's personal AI assistant, powered by Streamlit and Gemini. Troy greets you like Claude does, answers questions, reads PDFs and photos, takes voice messages, and talks back in a human voice.

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
- Replies are read aloud automatically; the **🔊 Troy speaks out loud** switch turns this off, **Stop speaking** stops a reply, and **Read aloud** replays one.
- **Message box like Claude's:** type in the box at the bottom; tap **＋** to add PDFs, photos (camera or library), .txt/.csv/.md files, or a **.zip** of them (up to 5 files, 10 MB each; a zip is unpacked — up to 10 readable files, 30 MB unpacked — and anything Troy can't read is listed as skipped); tap the **mic** to record a voice note, then **Submit recording**; tap the teal arrow to send.
- **Troy speaks by himself:** after your first tap on the page, every reply is read aloud automatically — no play button. The **🔊 Troy speaks out loud** switch at the top turns his voice off and on.
- **📘 Study a PDF:** ☰ → **Study a PDF** (or tap **Study “file” section by section** after sending a PDF). Troy splits it at its numbered sections (2.0 SCOPE, 4.1 …), shows the words big, and reads them word for word with the sentence highlighted — tap any sentence to start there. **Back · Read again · Stop · Next**, reading speed 0.8×–1.5×. Ask only when you want: **Quiz me**, **Explain it**, or **📖 Story / 🎙 Podcast / 🎯 Coach** retellings, or type/say any question about the section. Reading is free (words come straight from the PDF, phone voice); each question is one small brain call. Your place is saved on the phone — **Continue** picks up where you stopped. If a PDF's words come out as gibberish (some company PDFs store letters as font codes) or it's scanned pages, Troy **reads it with Claude's eyes by himself** (no button): each page picture is typed out word for word by Claude Haiku (about 2¢ for 40 pages, one time — the result is saved), then split into sections as usual.
- **Sidebar like Claude:** tap ☰ for **New chat**, **Search chats**, **Settings** (voice, brain, keys) and **Recents** — every chat is saved on your phone (browser storage), private to that phone, and survives Troy restarting. Tap a chat to reopen it; Troy remembers what was said.
- **Keyboard:** after you send, the phone keyboard closes so you can read the reply.
- **Human voice:** Troy speaks his replies in a natural Gemini voice (sidebar: **Human voice (Gemini)** and **Troy's voice**). It's free but uses one extra Gemini call per reply on the voice model's own daily allowance. If that runs out or fails, Troy says so and uses your device's best voice instead.
- **Better device voice on iPhone:** Settings → Accessibility → Spoken Content → Voices → English → download a **Premium** or **Enhanced** voice (e.g. Ava or Evan). Troy picks it automatically.
- **Brain:** Claude (Haiku 5.5 by default; Sonnet 5.5 in the sidebar). No daily limit — each message is paid from your Claude Console credits (Haiku costs a small fraction of a cent per message). If credits run out, Troy says so. Without a Claude key, Troy falls back to Gemini's free tier (20 messages a day).
- **Voice:** Gemini (free) makes Troy's human voice and writes down your voice messages for Claude.
- **Keys:** easiest — paste them once in ☰ → Settings with **Remember keys on this phone** ticked; Troy fills them in every time on that phone (saved in that browser only; **Forget saved keys** removes them). Or put `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in the app's Streamlit Secrets (works on every device and takes priority).
- The app uses Gemini 2.5 Flash.
- Troy adapts explanations and may be mistaken; verify important information, especially for high-stakes decisions.
- Voice recording requires microphone permission and browser support; spoken replies use your browser's text-to-speech voices and may be restricted by browser autoplay settings.

## Troy's health (troy_doctor.py)

Open ☰ → **Troy's health**.

- **Checkup** — a quick offline check runs by itself each time Troy starts (after every redeploy). **Run full checkup** also tests the Claude/Gemini keys, the AI models, and (optionally) the human voice. Run it from a terminal too: `python troy_doctor.py`.
- **Problems Troy noticed** — every real error, from Troy and from the phone (including two voices at once), with the time. Keys are never written to the log.
- **Double-check answers about files** (Settings) — after Troy answers from a file, a second pass checks the facts against the file, fixes them, and checks again.
- **Auto-adjust** — Claude busy: Troy waits and retries. Troy's Claude model retired: he switches to the other model and notes it.
- **Self-repair** — **Ask Troy to fix it**: Troy reads his problem list and code from GitHub, writes a fix, tests it with the checkup (one retry if it breaks a check), and opens it as a pull request. Nothing changes until you tap **Approve**. **Undo last fix** puts the files back. Repairs may only change `app.py`, `troy_study.py` and `requirements.txt` — never `troy_doctor.py`, so Approve/Undo always keep working.

Self-repair needs a GitHub key in Streamlit Secrets:

```toml
GITHUB_TOKEN = "github_pat_..."   # fine-grained, Troy repo only: Contents + Pull requests = Read and write
```

## Troy learns and thinks (troy_memory.py)

- **What Troy remembers** (☰) — after each chat, a quick pass keeps what you *said* that's worth knowing next time: how you like things done, facts about you, your projects. "Remember …" and "forget …" work. Every memory is listed with an ✕ to delete it; you can type one in; **Forget everything** erases it. Never stores keys, ID/account numbers, health, money amounts or similar. Switch **Learn from our chats** off any time.
- Memory is kept on each device. To share one memory between phone and laptop, create a **private** repo (e.g. `PaulContreras361/troy-memory`), include it in the GitHub key (Contents: Read and write), and add to Secrets:

```toml
TROY_MEMORY_REPO = "PaulContreras361/troy-memory"
```

  Troy refuses to keep memory in a public repo.
- **How Troy thinks** (Settings): **Troy decides** (quick model for small talk, the smarter model thinking it through for files, plans, code, EPR work), **Always deep thinker**, or **Fast, but thinks**. Each reply shows 🧠 which was used.
