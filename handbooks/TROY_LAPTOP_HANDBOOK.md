# TROY LAPTOP HANDBOOK — Nov 6, 2026

Everything for your **personal laptop**, in one folder: Troy, his laptop powers (screen, mouse, keyboard, files, AutoCAD, SketchUp, Outlook, EPR checker), Troy Hotkey, Hey Troy, and Glass HUD.

Your old Troy folders are **not deleted**: they're in `_old copies (delete after new Troy works)`. Once this Troy works, delete that folder yourself.

---

## What's in the folder

| File or folder | What it is |
|---|---|
| **Install Troy.bat** | Double-click once. Installs everything and makes the Desktop icon. |
| **Start Troy.bat** | Starts Troy (the Desktop icon runs this). |
| **Start Troy Hotkey.bat** | Starts the hold-Ctrl+Alt+Space voice helper. |
| `app.py`, `troy_study.py` | Troy himself: the same app as on your iPhone. |
| `troy_laptop.py` | Lets Claude use the laptop tools, with your Allow / Deny box. |
| `troy_tools.py` | Screen, mouse, keyboard, folders, apps (from Troy 2.0, Rev 4). |
| `troy_hands.py`, `troy_files.py` | Safe file moves, copies, renames, deletes (to troy_trash), undo. |
| `troy_autocad.py` | Draws in AutoCAD. |
| `troy_sketchup.py`, `sketchup\troy_bridge.rb` | Draws in SketchUp Pro. |
| `troy_outlook.py` | Reads email, writes **drafts only**. |
| `troy_epr.py` | EPR Master Tracker checker (read-only, never changes the workbook). |
| `troy_hotkey.py` | Troy Hotkey. |
| `brain.py` | Troy's free local brain (Ollama), rebuilt from our Sept 10 build. |
| `jarvis-troy\` | JARVIS, renamed so it wakes to **"Hey Troy"**. |
| `extras\glass-hud.html` | The Iron Man hand-tracking screen. |
| `extras\troy_desktop_assistant.html` | Your old one-file HTML Troy (kept, not used). |
| `old\` | The last Troy 2.0 app and the Troy class files, for reference only. |
| `handbooks\` | This handbook, the Troy Hotkey handbook, and the Local Brain handbook. |

---

# PART 1 — Install (one time, about 15 minutes)

### Step 1 — Stop the old Troy
1. Find the black window that's running TROY 2.0.
2. Click inside it and press **Ctrl + C**. Close the window.

### Step 2 — Unzip the new folder
Your old copies are already moved into **Desktop\Troy's Nov 7, 2026\_old copies (delete after new Troy works)**, so nothing gets mixed up.

1. Open your **Downloads** folder (press **Windows key + E**, click **Downloads**).
2. Right-click **Troy 11-7-2026.zip** and choose **Extract All…**
3. In the box at the top, delete what's there and type:
   ```
   C:\Users\paulc\OneDrive\Desktop\Troy's Nov 7, 2026
   ```
4. Click **Extract**.
5. Open **Desktop → Troy's Nov 7, 2026 → Troy**.
   - **Right:** you see `Install Troy.bat` and `app.py`. This **Troy** folder is the one good Troy from now on.
   - **Wrong:** you see another folder inside. Open it until you see `Install Troy.bat`; use that one.

### Step 3 — Run the installer
1. Double-click **Install Troy.bat**.
2. If a blue box says **"Windows protected your PC"**: click **More info**, then **Run anyway**. (Windows says this about every new .bat file.)
3. A black window fills with text for 2–5 minutes. Wait until it says **All set** or lists FAIL lines.
4. Read the last 15 lines:

| You see | Means |
|---|---|
| `OK` | Ready. |
| `NOTE  SketchUp ... open SketchUp Pro once` | Open SketchUp, close it, double-click Install Troy.bat again. |
| `NOTE  Outlook ... classic Outlook not found` | See Part 5. Everything else still works. |
| `FAIL` | Take a photo of the window and send it to Claude. |

5. Press any key to close the window.

---

# PART 2 — Start Troy

1. Double-click **Start Troy** on your Desktop (Troy's face icon).
2. A black window opens (leave it open; closing it stops Troy). Your browser opens Troy at `localhost:8501`.
   - If it opens **old TROY 2.0** instead, the old one is still running. Go back to Part 1 Step 1.
3. Tap **☰** (top left) → **Customize**.
4. If Troy asks for your key, paste your **Claude API key** (starts with `sk-ant-`), keep **Remember keys on this device** ticked, press **Enter**. You only do this once on this laptop.
5. In Customize, find **Laptop powers**. It starts on **1 · LOOK**.

---

# PART 3 — The leash (Laptop powers)

| Level | Troy can |
|---|---|
| **0 · OFF** | Talk only, like on your phone. |
| **1 · LOOK** | Read files and folders, take screenshots, check CPU/memory, see what's open in AutoCAD and SketchUp, read and search email, run the EPR checker. |
| **2 · DO** | Everything above, plus open apps, files and websites, draw in AutoCAD and SketchUp, write email drafts, and move/copy/rename/delete files (each one asks first). |
| **3 · DRIVE** | Everything above, plus move the mouse, click, type, press keys, and type AutoCAD commands. |

**Run without asking, up to** decides which steps stop for the **Allow / Deny** box. Leave it on **1 · LOOK** to start: Troy looks on his own but asks before he does anything.

**These ALWAYS ask, whatever you set:** moving, copying, renaming or deleting a file, making a folder, undoing a file action, saving a drawing or model, and typing an AutoCAD command.

**The Allow box** shows exactly what Troy will do (for files, troy_hands' own plan, like `PLAN: move file … → …`).
- **Allow** = do it.
- **Deny** = skip it; Troy is told you said no.
- Typing a new message instead = counts as Deny.

**🛑 Emergency stop:** shove the mouse into the **top-left corner** of the screen. Mouse and keyboard control stops instantly.

**After each reply** Troy lists what he used, like `🛠️ autocad_status ✓, autocad_draw ✓`. ✓ = worked, ✗ = failed, (denied) = you said no.

**Brain:** for screen clicking and drawing, pick **Claude Sonnet 5.5** in Customize → Troy's brain. Haiku is cheaper but less reliable at reading the screen.

---

# PART 4 — Try it

Set **Laptop powers** to **2 · DO** for these.

| Say or type | What happens |
|---|---|
| "How's my laptop running?" | CPU, memory, disk, battery. |
| "What's in my Downloads folder?" | Lists it. |
| "Find my pipeline drawings in Documents." | Searches file names. |
| "Start AutoCAD." | Opens full AutoCAD. Wait ~30 seconds. |
| "In AutoCAD, draw a 12 by 16 rectangle on a layer called SHED, red, with a dimension on the long side." | Draws it in one step. One **Ctrl+Z** in AutoCAD removes it all. |
| "What's on the drawing right now?" | Counts by layer and type, with sizes. |
| "Save the drawing." | Allow box first. Troy won't overwrite an existing file with Save As. |
| "Start SketchUp." | Opens SketchUp Pro. Pick a template if it asks. |
| "In SketchUp, make a 12 by 16 shed floor, four 8-foot walls half a foot thick, and name each piece." | Draws named groups. Each one is one Ctrl+Z. |
| "Show my unread emails." | Newest unread: sender, subject, preview. |
| "Draft a reply to the newest email from Mike saying I'll have the EPR update by Friday." | Draft opens on screen. **You** read it and press Send. Troy can't send. |
| "Check my EPR tracker at C:\Users\paulc\Downloads\Pauls_Master_EPR_Tracker_WE_11-08-2026_Rev_1.xlsx" | Read-only report: counts, move candidates, numbering, duplicates. |

**3 · DRIVE** (mouse and keyboard), try: "Take a screenshot and tell me what's on my screen", then "Click the File menu."

---

# PART 5 — Email: classic Outlook only

Troy reads email through **classic Outlook** for Windows. It works with every account you've added there (work, Yahoo, Gmail).

If Outlook has a **New Outlook** switch at the top right that's **on**, Troy can't reach it. Turn the switch **off** to go back to classic Outlook, then try again.

---

# PART 6 — SketchUp check

1. Open SketchUp Pro.
2. Top menu: **Extensions → Troy Bridge → Status**.
   - **Right:** "Troy Bridge 1.0 is running."
   - **Wrong:** no Troy Bridge in the menu. Close SketchUp, double-click **Install Troy.bat** again, reopen SketchUp.

The plugin can only draw boxes, rectangles, outlines, walls, cylinders and lines, move or delete Troy's named groups, zoom, undo and save. It can't run anything else.

---

# PART 7 — Troy Hotkey (hold Ctrl+Alt+Space and talk)

Already installed. Follow **handbooks\TROY_HOTKEY_HANDBOOK.md** from **Step 2** (Steps 1 and 3 are done). To start it any time, double-click **Start Troy Hotkey.bat**.

---

# PART 8 — Hey Troy (JARVIS)

This is JARVIS with the name changed: it wakes to **"Hey Troy"**, calls itself Troy, and shows TROY on screen. It also answers to "Hey Troi" or "Hey Roy" when Chrome mishears you. Plain "try" and "toy" don't wake it.

1. Press **Windows key**, type `cmd`, press **Enter** (Command Prompt, **not** PowerShell).
2. Type `node -v` and press **Enter**.
   - **Right:** `v20` or higher.
   - **Wrong:** an error or `v18`. Install **Node LTS** from **nodejs.org**, close Command Prompt, open a new one.
3. Copy this line, paste it (right-click), press **Enter**:
   ```
   cd /d "C:\Users\paulc\OneDrive\Desktop\Troy's Nov 7, 2026\Troy\jarvis-troy"
   ```
4. Type `npm run setup` and press **Enter**. Answer what it asks.
5. Type `npm install` and press **Enter**. Wait (a few minutes the first time).
6. Type `npm start` and press **Enter**. **Leave this window open.**
7. Open **Chrome** and go to `http://localhost:5173`
8. Click **INITIALISE**, allow the microphone, and say **"Hey Troy."**

- **D** = diagnostics. **Space** = talk without the wake word.
- It starts in **read-only** mode. To let it take actions: close the window, then run `npm start -- --writes`.
- "Bridge not reachable" = the window from step 6 was closed. Run `npm start` again.

---

# PART 8½ — Free local brain (optional)

Follow **handbooks\TROY_LOCAL_BRAIN_HANDBOOK.md**: Steps 0–3 install Ollama and the model, Step 6
tests it. Then in Troy: **Customize → Troy's brain → Local brain**. It chats for free and offline,
but can't see photos/PDFs or use the laptop tools. If Claude credits run out, Troy switches to it
by himself (when Ollama is running).

---

# PART 9 — Glass HUD

1. Open the **extras** folder.
2. Right-click **glass-hud.html** → **Open with** → **Google Chrome**.
3. Click **Start camera** → **Allow**. Point to move the ring, pinch to click.

---

# PART 10 — If something goes wrong

| Problem | Fix |
|---|---|
| Laptop powers isn't in Customize | You're on the phone/cloud Troy. Use the Desktop **Start Troy** icon on this laptop. |
| "AutoCAD isn't open" | Say "start AutoCAD", wait 30 seconds, ask again. |
| AutoCAD step fails with "rejected" | AutoCAD was busy (a dialog box open). Close the dialog, ask again. |
| "SketchUp didn't answer" | SketchUp must be open with a model, and the plugin loaded (Part 6). |
| "Couldn't reach classic Outlook" | Part 5. |
| "needs level 3 (DRIVE)" | Troy needs a higher level. Raise **Laptop powers** if you want him to. |
| Troy says a path is "outside Troy's fence" | Troy works only in Desktop, Documents, Downloads, Pictures, the Troy folder and drives D–H. |
| You want a deleted file back | Ask Troy "undo the last file action", or look in the **troy_trash** folder. |
| Anything else | Send Claude a photo of the screen and the black window. |

---

## Where Troy keeps things

| What | Where |
|---|---|
| Action log | `troy_data\action_log.jsonl` |
| Screenshots | `troy_data\screenshots` |
| Laptop powers setting | `troy_data\laptop_settings.json` |
| File actions and undo list | `troy_logs\` |
| Deleted files | `troy_trash\` |
| SketchUp requests | `%LOCALAPPDATA%\TroyBridge\sketchup` |
| Troy Hotkey log | `%LOCALAPPDATA%\TroyHotkey` |
