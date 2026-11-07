"""
troy_pages.py - Troy's Claude-style pages: Projects, Artifacts, Scheduled, Design.

Plain English:
  Projects   - folders for chats, each with its own instructions ("always use plant
               coordinates", "answers for my Etsy customers"). Chats started inside a
               project follow its instructions.
  Artifacts  - everything Troy makes that you'd keep: web pages, designs, code. Troy saves
               them by himself from his replies; open, preview, download or delete them.
  Scheduled  - things Troy should do at a set time (once, daily, weekly). He does them
               the next time Troy is open after that time, and puts the answer in a chat.
  Design     - describe a flyer, poster, web page or app screen; Troy builds it as one
               HTML file you can preview, change and download.

  Everything is saved in this browser (the same place as your chats), so each device
  keeps its own list.
"""

from __future__ import annotations

import html as _html
import re
import time
from datetime import datetime, timedelta
from uuid import uuid4

import streamlit as st

MAX_ARTIFACTS = 40
MAX_ARTIFACT_CHARS = 150_000
DEFAULTS = {"projects": {}, "artifacts": {}, "scheduled": {}, "custom": "", "page": None,
            "project_id": None, "design_id": None, "open_artifact": None, "open_project": None}


def init():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v.copy() if isinstance(v, dict) else v


def load(saved: dict):
    """Pull the pages' data out of what the browser had saved."""
    for k in ("projects", "artifacts", "scheduled"):
        if isinstance(saved.get(k), dict):
            merged = dict(saved[k])
            merged.update(st.session_state[k])
            st.session_state[k] = merged
    if isinstance(saved.get("custom"), str) and not st.session_state.custom:
        st.session_state.custom = saved["custom"]
        st.session_state["custom_box"] = saved["custom"]   # the Customize box shows it too


def payload() -> dict:
    arts = sorted(st.session_state.artifacts.values(), key=lambda a: a["created"], reverse=True)
    st.session_state.artifacts = {a["id"]: a for a in arts[:MAX_ARTIFACTS]}
    return {"projects": st.session_state.projects, "artifacts": st.session_state.artifacts,
            "scheduled": st.session_state.scheduled, "custom": st.session_state.custom}


def open_page(name):
    st.session_state.page = name
    st.session_state.open_artifact = None
    st.session_state.open_project = None


# ------------------------------------------------------------------ Projects
def project_instructions() -> str:
    p = st.session_state.projects.get(st.session_state.project_id or "")
    if not p:
        return ""
    return (f"\n\nPROJECT: {p['name']}\nThis chat belongs to Paul's project \"{p['name']}\"."
            + (f" Follow its instructions:\n{p['instructions']}\n" if p.get("instructions") else "\n"))


def render_projects(chats, open_chat, new_chat, save):
    st.markdown('<div class="troy-page-title">Projects</div>', unsafe_allow_html=True)
    projects = st.session_state.projects
    pid = st.session_state.open_project
    if pid and pid in projects:
        p = projects[pid]
        if st.button("All projects", key="proj_back", icon=":material/arrow_back:", type="tertiary"):
            st.session_state.open_project = None
            st.rerun()
        st.subheader(p["name"])
        instr = st.text_area("Instructions Troy follows in this project", p.get("instructions", ""),
                             key=f"proj_instr_{pid}", height=120,
                             placeholder="e.g. Use FPC plant coordinates. Keep answers short.")
        if instr != p.get("instructions", ""):
            p["instructions"] = instr
            save()
        if st.button("New chat in this project", key="proj_new_chat", icon=":material/add:",
                     type="primary"):
            new_chat()
            st.session_state.project_id = pid
            st.session_state.page = None
            st.rerun()
        mine = sorted((c for c in chats.values() if c.get("project") == pid),
                      key=lambda c: c["updated"], reverse=True)
        st.caption(f"{len(mine)} chat(s)")
        for c in mine:
            if st.button(c["title"], key=f"proj_chat_{c['id']}", icon=":material/chat_bubble:",
                         type="tertiary"):
                open_chat(c["id"])
                st.session_state.page = None
                st.rerun()
        with st.expander("Rename or delete", key="proj_edit"):
            name = st.text_input("Name", p["name"], key=f"proj_name_{pid}")
            if name.strip() and name.strip() != p["name"]:
                p["name"] = name.strip()
                save()
                st.rerun()
            if st.button("Delete project (its chats stay in Recents)", key="proj_del",
                         icon=":material/delete:"):
                for c in chats.values():
                    if c.get("project") == pid:
                        c.pop("project", None)
                projects.pop(pid, None)
                st.session_state.open_project = None
                save()
                st.rerun()
        return
    with st.form("new_project", clear_on_submit=True, border=True):
        st.markdown("**New project**")
        name = st.text_input("Project name", placeholder="e.g. EPR weekly updates")
        instr = st.text_area("Instructions for Troy (optional)", height=90,
                             placeholder="What should Troy always know or do in this project?")
        if st.form_submit_button("Create project", icon=":material/create_new_folder:") and name.strip():
            new_id = uuid4().hex[:10]
            projects[new_id] = {"id": new_id, "name": name.strip(), "instructions": instr.strip(),
                                "created": time.time()}
            st.session_state.open_project = new_id
            save()
            st.rerun()
    if not projects:
        st.caption("No projects yet. Make one above, then start chats inside it.")
    for p in sorted(projects.values(), key=lambda p: p["created"], reverse=True):
        n = sum(1 for c in chats.values() if c.get("project") == p["id"])
        if st.button(f"{p['name']}  ·  {n} chat(s)", key=f"proj_open_{p['id']}",
                     icon=":material/folder:", width="stretch"):
            st.session_state.open_project = p["id"]
            st.rerun()


# ------------------------------------------------------------------ Artifacts
FENCE = re.compile(r"```([\w+-]*)[^\n]*\n(.*?)```", re.S)
KIND = {"html": "Web page", "svg": "Picture (SVG)", "python": "Python", "py": "Python",
        "javascript": "JavaScript", "js": "JavaScript", "css": "CSS", "json": "JSON",
        "csv": "Table (CSV)", "sql": "SQL", "bat": "Windows script", "md": "Document",
        "markdown": "Document", "text": "Text"}
EXT = {"html": "html", "svg": "svg", "python": "py", "py": "py", "javascript": "js", "js": "js",
       "css": "css", "json": "json", "csv": "csv", "sql": "sql", "bat": "bat", "md": "md",
       "markdown": "md"}


def add_artifact(title, lang, content, source=""):
    if not content.strip() or len(content) > MAX_ARTIFACT_CHARS:
        return None
    for a in st.session_state.artifacts.values():     # same thing saved twice
        if a["content"] == content:
            return a["id"]
    aid = uuid4().hex[:10]
    st.session_state.artifacts[aid] = {
        "id": aid, "title": title[:70], "lang": (lang or "text").lower(), "content": content,
        "created": time.time(), "source": source[:80]}
    return aid


def capture(reply_text, chat_title):
    """Save code blocks worth keeping from one of Troy's replies. Returns how many."""
    n = 0
    for lang, body in FENCE.findall(reply_text or ""):
        lang = (lang or "").lower()
        lines = body.strip().count("\n") + 1
        keep = (lang in ("html", "svg") and lines >= 5) or lines >= 12
        if not keep:
            continue
        if lang == "" and body.lstrip().lower().startswith(("<!doctype", "<html")):
            lang = "html"
        m = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
        title = (m.group(1).strip() if m else "") or f"{KIND.get(lang, lang.upper() or 'Code')} — {chat_title}"
        if add_artifact(title, lang, body.strip(), chat_title):
            n += 1
    return n


def _preview(a, height=520):
    if a["lang"] in ("html", "svg"):
        doc = a["content"] if a["lang"] == "html" else (
            "<!doctype html><body style='margin:0;display:grid;place-items:center;background:#fff'>"
            + a["content"] + "</body>")
        st.components.v1.html(doc, height=height, scrolling=True)
    else:
        st.code(a["content"], language=a["lang"] if a["lang"] in KIND else None, line_numbers=True)


def render_artifacts(save):
    st.markdown('<div class="troy-page-title">Artifacts</div>', unsafe_allow_html=True)
    arts = st.session_state.artifacts
    aid = st.session_state.open_artifact
    if aid and aid in arts:
        a = arts[aid]
        if st.button("All artifacts", key="art_back", icon=":material/arrow_back:", type="tertiary"):
            st.session_state.open_artifact = None
            st.rerun()
        st.subheader(a["title"])
        st.caption(f"{KIND.get(a['lang'], a['lang'])} · made "
                   f"{datetime.fromtimestamp(a['created']):%b %d, %I:%M %p}"
                   + (f" · from “{a['source']}”" if a.get("source") else ""))
        _preview(a)
        c1, c2, c3 = st.columns(3)
        safe = re.sub(r"[^\w\- ]+", "", a["title"]).strip()[:40] or "troy-artifact"
        c1.download_button("Download", a["content"], file_name=f"{safe}.{EXT.get(a['lang'], 'txt')}",
                           icon=":material/download:", key="art_dl", width="stretch")
        if a["lang"] == "html" and c2.button("Change it in Design", key="art_design",
                                             icon=":material/palette:", width="stretch"):
            st.session_state.design_id = aid
            open_page("design")
            st.rerun()
        if c3.button("Delete", key="art_del", icon=":material/delete:", width="stretch"):
            arts.pop(aid, None)
            st.session_state.open_artifact = None
            save()
            st.rerun()
        if a["lang"] in ("html", "svg"):
            with st.expander("See the code", key="art_code"):
                st.code(a["content"], language=a["lang"])
        return
    if not arts:
        st.caption("Nothing yet. When Troy makes a web page, design, or a long piece of code, "
                   "it lands here by itself. You can also make one in Design.")
        return
    q = st.text_input("Search artifacts", key="art_search", placeholder="Search artifacts",
                      label_visibility="collapsed", icon=":material/search:").strip().lower()
    for a in sorted(arts.values(), key=lambda a: a["created"], reverse=True):
        if q and q not in a["title"].lower() and q not in a["content"][:4000].lower():
            continue
        label = f"{a['title']}  ·  {KIND.get(a['lang'], a['lang'])}"
        if st.button(label, key=f"art_open_{a['id']}", width="stretch",
                     icon=":material/web:" if a["lang"] in ("html", "svg") else ":material/code:"):
            st.session_state.open_artifact = a["id"]
            st.rerun()


# ------------------------------------------------------------------ Scheduled
REPEATS = {"Once": None, "Every day": timedelta(days=1), "Every week": timedelta(days=7),
           "Weekdays": "weekdays"}


def _next(when: datetime, repeat: str, now: datetime) -> datetime | None:
    step = REPEATS.get(repeat)
    if step is None:
        return None
    nxt = when
    while nxt <= now:
        if step == "weekdays":
            nxt += timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
        else:
            nxt += step
    return nxt


def due_tasks(now: datetime):
    return [t for t in st.session_state.scheduled.values()
            if t.get("active", True) and datetime.fromisoformat(t["when"]) <= now]


def run_due(now: datetime, ask, put_in_chat, save, limit=3):
    """Do overdue tasks (a few at a time). Returns the titles done."""
    done = []
    for t in sorted(due_tasks(now), key=lambda t: t["when"])[:limit]:
        try:
            answer = ask(t["prompt"])
            ok = True
        except Exception as e:     # noqa: BLE001
            answer, ok = f"Troy couldn't do this one: {type(e).__name__}: {e}", False
        t["last_run"] = now.isoformat(timespec="minutes")
        t["last_result"] = answer[:4000]
        put_in_chat(t, answer)
        nxt = _next(datetime.fromisoformat(t["when"]), t.get("repeat", "Once"), now)
        if nxt is None:
            t["active"] = False
        else:
            t["when"] = nxt.isoformat(timespec="minutes")
        done.append(t["title"] + ("" if ok else " (failed)"))
    if done:
        save()
    return done


def render_scheduled(now: datetime, ask, put_in_chat, save):
    st.markdown('<div class="troy-page-title">Scheduled</div>', unsafe_allow_html=True)
    st.caption("Troy does each task the next time he's open after its time (he can't wake himself "
               "up while every Troy window is closed). Each answer goes into a new chat.")
    with st.form("new_task", clear_on_submit=True, border=True):
        st.markdown("**New scheduled task**")
        title = st.text_input("Name", placeholder="e.g. Monday EPR reminder")
        prompt = st.text_area("What should Troy do?", height=80,
                              placeholder="e.g. Remind me to send the weekly EPR update and list the steps.")
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("Day", value=now.date())
        at = c2.time_input("Time", value=(now + timedelta(minutes=30)).time().replace(second=0, microsecond=0))
        repeat = c3.selectbox("Repeat", list(REPEATS))
        if st.form_submit_button("Schedule it", icon=":material/schedule:") and prompt.strip():
            tid = uuid4().hex[:10]
            st.session_state.scheduled[tid] = {
                "id": tid, "title": (title.strip() or prompt.strip())[:60], "prompt": prompt.strip(),
                "when": datetime.combine(day, at).isoformat(timespec="minutes"), "repeat": repeat,
                "active": True, "created": time.time()}
            save()
            st.rerun()
    tasks = sorted(st.session_state.scheduled.values(), key=lambda t: (not t.get("active", True), t["when"]))
    if not tasks:
        st.caption("No scheduled tasks yet.")
    for t in tasks:
        with st.container(border=True, key=f"task_{t['id']}"):
            when = datetime.fromisoformat(t["when"])
            status = (f"Next: {when:%a %b %d, %I:%M %p}" if t.get("active", True) else "Done")
            st.markdown(f"**{_html.escape(t['title'])}** · {t.get('repeat', 'Once')} · {status}")
            st.caption(t["prompt"][:200])
            if t.get("last_run"):
                st.caption(f"Last done {t['last_run'].replace('T', ' ')}")
            b1, b2, b3 = st.columns(3)
            if b1.button("Run now", key=f"task_run_{t['id']}", icon=":material/play_arrow:", width="stretch"):
                with st.spinner("Troy is doing it..."):
                    try:
                        answer = ask(t["prompt"])
                    except Exception as e:     # noqa: BLE001
                        answer = f"Troy couldn't do this one: {type(e).__name__}: {e}"
                t["last_run"] = now.isoformat(timespec="minutes")
                t["last_result"] = answer[:4000]
                put_in_chat(t, answer)
                save()
                st.session_state.page = None
                st.rerun()
            if t.get("active", True):
                if b2.button("Pause", key=f"task_pause_{t['id']}", icon=":material/pause:", width="stretch"):
                    t["active"] = False
                    save()
                    st.rerun()
            elif b2.button("Turn on", key=f"task_on_{t['id']}", icon=":material/play_circle:", width="stretch"):
                t["active"] = True
                if datetime.fromisoformat(t["when"]) <= now:
                    t["when"] = (_next(datetime.fromisoformat(t["when"]), t.get("repeat", "Once"), now)
                                 or now + timedelta(minutes=5)).isoformat(timespec="minutes")
                save()
                st.rerun()
            if b3.button("Delete", key=f"task_del_{t['id']}", icon=":material/delete:", width="stretch"):
                st.session_state.scheduled.pop(t["id"], None)
                save()
                st.rerun()


# ------------------------------------------------------------------ Design
DESIGN_SYSTEM = """You are Troy's design studio. You build ONE complete, self-contained HTML file.
Rules:
- Output ONLY the HTML document, starting with <!doctype html>. No explanation before or after.
- All CSS inline in a <style> tag. Google Fonts links are fine. No other outside files.
- No cartoon or drawn characters, mascots or clip-art people. Use strong typography, color,
  shapes, layout, icons made from simple CSS/SVG geometry, and photo placeholders (a labeled
  box saying what real photo goes there) instead.
- Never copy a real brand's logo, characters or trademarked look.
- Make it look professionally designed: clear hierarchy, generous spacing, a deliberate color
  palette, readable sizes. It must fit the requested size and work on a phone.
- Put a short <title> naming the design.
"""
DESIGN_KINDS = {
    "Flyer / poster (letter)": "a printable flyer, 8.5 x 11 inch page proportions",
    "Social post (square)": "a square social media post, 1080 x 1080",
    "Web page": "a one-page website / landing page that scrolls",
    "App screen (phone)": "a phone app screen mockup, 390 x 844",
    "Slide (16:9)": "a single presentation slide, 1920 x 1080 proportions",
    "Sign / label": "a sign or label",
}


def _clean_html(text):
    m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S)
    text = m.group(1) if m else text
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    return text[i:].strip() if i >= 0 else text.strip()


def design_request(request, kind, ask_design, chat_title="Design"):
    """Make a new design, or change the one that's open. Returns the artifact id."""
    current = st.session_state.artifacts.get(st.session_state.design_id or "")
    if current and current["lang"] == "html":
        prompt = (f"Here is the current design:\n\n{current['content']}\n\nChange it like this: "
                  f"{request}\nReturn the whole updated HTML file.")
    else:
        prompt = f"Design {DESIGN_KINDS.get(kind, kind)}.\nWhat Paul wants: {request}"
    out = _clean_html(ask_design(prompt, DESIGN_SYSTEM))
    if "<" not in out:
        raise ValueError("Troy's design came back without any HTML. Try describing it again.")
    m = re.search(r"<title>(.*?)</title>", out, re.I | re.S)
    title = (m.group(1).strip() if m else "") or request[:50]
    aid = add_artifact(title, "html", out, chat_title)
    st.session_state.design_id = aid
    return aid


def render_design(save, ask_design):
    st.markdown('<div class="troy-page-title">Design</div>', unsafe_allow_html=True)
    current = st.session_state.artifacts.get(st.session_state.design_id or "")
    if current:
        st.caption(f"Working on: **{current['title']}** — type a change in the message box "
                   "(e.g. “make the title bigger and use navy and gold”).")
        _preview(current, height=620)
        c1, c2, c3 = st.columns(3)
        safe = re.sub(r"[^\w\- ]+", "", current["title"]).strip()[:40] or "troy-design"
        c1.download_button("Download", current["content"], file_name=f"{safe}.html",
                           icon=":material/download:", key="des_dl", width="stretch")
        if c2.button("Start a new design", key="des_new", icon=":material/add:", width="stretch"):
            st.session_state.design_id = None
            st.rerun()
        if c3.button("All artifacts", key="des_arts", icon=":material/web:", width="stretch"):
            open_page("artifacts")
            st.rerun()
        return
    st.caption("Describe what you want in the message box below and send it. Troy builds it as a "
               "web file you can preview, change, download and print.")
    st.segmented_control("What kind?", list(DESIGN_KINDS), default=list(DESIGN_KINDS)[0],
                         key="design_kind")
    st.caption("Examples: “Flyer for a Saturday fish fry at the Point Comfort pavilion, 6 PM, "
               "$10 plates” · “Landing page for My Deer Spot app” · “Safety sign: hard hats required "
               "past this point”.")
