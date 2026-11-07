# Troy Hotkey — Rev 0 Handbook

Hold **Ctrl + Alt + Space**, say what you need, let go. Troy does it on your laptop.

This is a separate program from your Streamlit Troy. It runs on your **personal Windows laptop** only. It does not change any of your other Troy files.

---

## What you'll need before starting

- Your personal Windows laptop (not a work machine)
- Python installed (you already have it — you run `py` for Troy)
- Claude Code installed and signed in (you already have it)
- The file `troy_hotkey.py` from this chat
- About 15 minutes

---

## Step 1 — Already done

`troy_hotkey.py` is already in your new Troy folder (`C:\Users\paulc\OneDrive\Desktop\Troy's Nov 7, 2026\Troy`), next to `troy_hands.py`.

---

## Step 2 — Open Command Prompt in the Troy folder

1. In File Explorer, while you're inside the Troy folder, click the **address bar** at the top (where the folder path shows).
2. Type `cmd` and press **Enter**.
3. A black Command Prompt window opens, already in the Troy folder.

---

## Step 3 — Already done

`Install Troy.bat` installed everything Troy Hotkey needs. Skip to Step 4.

---

## Step 4 — Check that everything is there

Type this and press **Enter**:

```
python troy_hotkey.py --check
```

**Right:** every line says `OK`, like this:

```
  OK       keyboard         hotkey
  OK       sounddevice      microphone
  ...
  OK       Claude Code      C:\Users\paulc\...\claude.cmd
  OK       troy_hands.py    file changes
```

**Wrong:** a line says `MISSING`.
- If a Python part is missing → double-click `Install Troy.bat` again.
- If **Claude Code** is missing → type `claude --version`. If that fails, Claude Code isn't on PATH; tell me what it says.
- If **troy_hands.py** is missing → Troy Hotkey still works, but it won't move/rename/delete files until `troy_hands.py` is in the same folder.

---

## Step 5 — Run the self-test

Type this and press **Enter**:

```
python troy_hotkey.py --selftest
```

**Right:** `Selftest: 27 passed, 0 failed`

**Wrong:** any `FAIL` line. Copy the whole output and send it to me.

---

## Step 6 — Try it by typing first (no microphone yet)

This proves the hands and the brain work before adding your voice.

Type each line, press **Enter**, and watch what happens:

| Type this | What should happen |
|---|---|
| `python troy_hotkey.py --text "open notepad"` | Notepad opens. No AI used. |
| `python troy_hotkey.py --text "notepad on the left"` | Notepad snaps to the left half. |
| `python troy_hotkey.py --text "find my pipeline drawings"` | File Explorer opens with the top match selected. |
| `python troy_hotkey.py --text "what's 15 percent of 240"` | Troy's brain answers (takes a few seconds — this one uses Claude Code). |

If the last one says **"My brain didn't answer"**, copy the message and send it to me.

---

## Step 7 — Start the real hotkey

Type this and press **Enter**:

```
pythonw troy_hotkey.py
```

- `pythonw` runs it **without** a black window.
- A small dark box appears at the bottom of your screen: **"Loading speech model…"**
- **The first time only**, it downloads the speech model (about 150 MB). Wait for **"Ready. Hold Ctrl + Alt + Space and talk."**

---

## Step 8 — Talk to it

1. **Hold** Ctrl + Alt + Space.
2. The box says **"Listening…"**.
3. Keep holding and say: **"Open Calculator."**
4. **Let go.**
5. Calculator opens.

**Esc** while holding = cancel.
Pressing the hotkey while Troy is talking = stops his voice.

### Things to try

| Say | What Troy does | Uses AI? |
|---|---|---|
| "Open AutoCAD." | Opens it from your Start menu | No |
| "Chrome on my second screen." | Moves Chrome there, full size | No |
| "Excel on the right of the big screen." | Snaps Excel right on the larger monitor | No |
| "Find my pipeline drawings." | Searches inside files, opens Explorer at the top match | No |
| "Search for Point Comfort tide chart." | Google search in your browser | No |
| "Reply: sounds good, see you at 7." | Types it into the app you were in. **Never presses Enter.** | No |
| "What's wrong with this code?" | Looks at your screen and answers out loud | Yes |
| "Code on my big screen, Chrome and Terminal on the laptop." | Arranges all three | Yes |
| "Move that PDF to my D drive." | Plans it, then shows an **Allow / Deny** box | Yes |

---

## Step 9 — Quit it

Press **Ctrl + Alt + Shift + Q**.

---

## Step 10 (optional) — Start Troy Hotkey when the laptop turns on

1. Press **Windows key + R**.
2. Type `shell:startup` and press **Enter**. A folder opens.
3. In that folder, **right-click** an empty spot → **New** → **Shortcut**.
4. In the box, paste:
   ```
   pythonw "C:\Users\paulc\OneDrive\Desktop\Troy's Nov 7, 2026\Troy\troy_hotkey.py"
   ```
5. Click **Next**, name it `Troy Hotkey`, click **Finish**.

To stop it starting at login, delete that shortcut.

---

## Safety — what Troy Hotkey can and can't do

**Can, without asking:** open apps, websites and files; move windows; search; type text (never presses Enter, so it never sends anything).

**Asks you first (Allow / Deny box):** move, copy, rename, delete or make a folder. These go through your own `troy_hands.py`, so deletes go to `troy_trash` and stay inside your fence folders.

**Can never do:** run commands or scripts. The brain is blocked from Bash, file editing and web fetching inside Claude Code. There is no "run" action at all.

**No auto-update.** Unlike Atticus, nothing downloads new code by itself. The only code that runs is the file you put in the folder.

**Privacy:** your voice is turned into text on your laptop; the audio never leaves it. A screenshot is only sent to Claude when your ask is about your screen ("this," "that," "my screen," "what's wrong"). The overlay box hides itself from screenshots.

Its log, settings and last screenshot live in:
`C:\Users\paulc\AppData\Local\TroyHotkey`
(outside your GitHub folder, so nothing gets pushed to GitHub.)

---

## Switching the brain to your API key (optional)

The default brain is your **Claude Pro plan through Claude Code** — no per-ask charge.

To use your Claude API key instead:

1. Open `troy_hotkey.py` in Notepad.
2. Find this line near the top:
   - **Wrong (for API):** `BRAIN = "claude_code"`
   - **Right (for API):** `BRAIN = "api"`
3. Save.
4. In Command Prompt, once:
   ```
   setx ANTHROPIC_API_KEY "your-key-here"
   ```
5. Close Command Prompt, open a new one, and restart Troy Hotkey.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Hotkey does nothing | Make sure the box said "Ready." If not, wait for the speech model. Try running `python troy_hotkey.py` (not `pythonw`) to see error messages. |
| "Still loading the speech model…" | First run downloads ~150 MB. Wait a minute. |
| "I couldn't find an app called …" | Say the name as it shows in your Start menu. |
| Window goes to the wrong screen | "Second screen" = the one that isn't your main display. "Big screen" = the largest. "Laptop" = the smallest. |
| Brain is slow | Claude Code takes a few seconds per ask. Instant commands (the "No AI" ones) are immediate. |
| "My brain didn't answer: …" | Send me the message. Most often Claude Code needs you to sign in again — type `claude` once in Command Prompt. |
| Hotkey clashes with another app | Open `troy_hotkey.py`, change `HOTKEY = "ctrl+alt+space"` to something else. |
