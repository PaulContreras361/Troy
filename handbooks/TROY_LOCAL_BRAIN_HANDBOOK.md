# Troy Local Brain — Install Handbook

**Goal:** give Troy a free thinking engine that runs on your own laptop: no API
credits, no internet once it's downloaded. It's a backup for Claude, not a
replacement: it can chat, but it can't see photos or PDFs or use the laptop tools.

**Rebuilt Nov 6, 2026:** `brain.py` is already in your Troy folder and already
wired into Troy (Stage 2 is done). You only need Steps 0–3, Step 5 (only if you picked a smaller model) and Step 6.

Everything here is free. Nothing here changes any file you already have.

---

## Step 0 — Find out how much memory your laptop has

This decides which model you download. Do not skip it.

1. Press the **Windows key**.
2. Type `powershell`
3. Press **Enter**. A blue window opens.
4. Type this exactly, then press **Enter**:

```
(Get-CIMInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
```

5. Write down the number it prints.

**Now pick your model from the number:**

| Your RAM | Model to use | Download size |
|---|---|---|
| 16 GB or more | `qwen3:8b` | about 5 GB |
| 8 GB to 15 GB | `qwen3.5:4b` | about 3 GB |
| Under 8 GB | `llama3.2:3b` | about 2 GB |

Write your model name down. You will type it three more times.

> **Why not `llama3.2:3b` for everyone, like the Perplexity page said?**
> That model is fine for plain chat, but it is weak at *tool calling* — the part
> where Troy has to emit clean JSON to fire one of his 37 tools. Qwen3 carries
> Ollama's native Tools support and is the current default pick for agents.
> Use the biggest one your RAM allows.

---

## Step 1 — Install Ollama

Ollama is the program that runs the model. It installs like any other Windows app.

1. Open your browser.
2. Go to **https://ollama.com/download**
3. Click **Download for Windows**.
4. When the file finishes, double-click it.
5. Click through and accept every default.
6. Wait for it to finish. Ollama starts itself and sits in your system tray.

**Prove it installed.** Back in PowerShell, type this and press **Enter**:

```
ollama --version
```

You should see a version number (something like `0.32.x`).

- If you see `ollama is not recognized`, **close PowerShell completely and open
  a new one**. Windows only picks up the new command in a fresh window.

---

## Step 2 — Download the model

In PowerShell, type `ollama pull ` followed by **your model from Step 0**.
Example for a 16 GB laptop:

```
ollama pull qwen3:8b
```

Press **Enter**.

This downloads several GB. It will take a while — leave the window open and let
the progress bar finish. If it stalls, press **Ctrl + C** and run the same
command again; it resumes where it stopped.

---

## Step 3 — Talk to the model directly

Still in PowerShell:

```
ollama run qwen3:8b
```

(Use your own model name.)

Wait for the `>>>` prompt, then type:

```
Say hello and tell me what you can help with.
```

Press **Enter**. You should get a normal answer in a few seconds.

**To exit:** type `/bye` and press **Enter**.

> `/bye` is the clean exit. `Ctrl + C` also works but can leave the model
> loaded in memory.

**If this step works, the brain itself is proven.** Everything from here is
just plumbing.

---

## Step 4 — Already done

`brain.py` is already in `C:\Users\paulc\OneDrive\Desktop\Troy's Nov 7, 2026\Troy`, beside `app.py`.

---

## Step 5 — Tell `brain.py` which model you picked

Skip this if you are using `qwen3:8b` — that is already the default.

Otherwise, open `brain.py` in Notepad and find this line near the top:

```python
MODEL = os.environ.get("TROY_LOCAL_MODEL", "qwen3:8b")
```

Change **only** the text inside the second set of quotes to your model:

```python
MODEL = os.environ.get("TROY_LOCAL_MODEL", "qwen3.5:4b")
```

Save and close.

---

## Step 6 — Test `brain.py` on its own

In a **Command Prompt** window (Windows key, type `cmd`, Enter), move into the Troy folder first:

```
cd /d "C:\Users\paulc\OneDrive\Desktop\Troy's Nov 7, 2026\Troy"
```

Then run:

```
py brain.py
```

If `py` does not work, use:

```
python brain.py
```

**What you should see:**

```
Host  : http://127.0.0.1:11434
Model : qwen3:8b
Pulled: qwen3:8b

OK. Asking a test question...

Hello, Paul. I can help with...
```

If it printed a real answer, the local brain works.

---

## If something went wrong

| What you see | What it means | Fix |
|---|---|---|
| `ollama is not recognized` | PowerShell was open before the install | Close it, open a new PowerShell |
| `Ollama is not answering at http://127.0.0.1:11434` | The service is not running | Type `ollama serve` and leave that window open |
| `Model 'x' is not pulled` | Step 2 did not finish, or the name is misspelled | Run `ollama list` to see the exact tag you have, then fix Step 5 |
| Answers take 60+ seconds | Model is too big for your RAM | Drop one row down the Step 0 table and pull the smaller model |
| `py is not recognized` | Python launcher missing | Use `python brain.py` instead |

---

## Stage 2 — Use it in Troy (already wired)

1. Start Troy with the **Start Troy** icon.
2. **☰** → **Settings** → **Troy's brain** → pick **Local brain — free, on this laptop (Ollama)**.
   - **Right:** under it you see `AI brain: local Ollama (qwen3:8b) — free, offline, no tools`.
   - **Wrong:** `⚠️ Local brain not ready: ...` — do what that line says (usually `ollama serve`).
3. Chat as normal. Answers take 10–60 seconds on a laptop.
4. Switch back to **Claude** for photos, PDFs, AutoCAD, SketchUp, email or anything on the screen.

**Automatic backup:** if your Claude credits run out while you're on the laptop and Ollama is
running, Troy answers with the local brain by himself and tells you he did.

---

## What this does and does not give Troy

**Does:** unlimited free conversation and reasoning, offline, with no daily cap.

**Does not:** see photos or PDFs, or use the laptop tools (screen, files, AutoCAD,
SketchUp, email). Those need the Claude brain, behind your Allow / Deny box.
