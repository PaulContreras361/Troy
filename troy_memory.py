"""Troy's memory — he learns what Paul wants, the way Claude does.

After each chat turn, a quick background pass reads what Paul said and Troy's
reply and keeps only what's worth knowing next time: how Paul wants Troy to
answer, facts about Paul and his world, and his ongoing projects. Only things
Paul actually SAID — never guesses. "Remember …" and "forget …" are honored.

What Troy knows goes into his instructions on every message, so he uses it
without being reminded. Paul can see, delete, or add memories in Settings.

Where it's kept:
  * on this device (browser storage, like the chats) — always works;
  * synced in a PRIVATE GitHub repo (TROY_MEMORY_REPO secret) when set up, so the
    phone and laptop share one memory. Never in Troy's public code repo.
"""

import base64
import json
import re
import time
import urllib.error
import urllib.request
from uuid import uuid4

LEARN_MODEL = "claude-haiku-5-5"
MAX_FACTS = 120
MEMORY_PATH = "memory.json"
KINDS = {"preference": "How Paul wants Troy to work",
         "about": "About Paul",
         "project": "Paul's projects and ongoing work"}

LEARN_SYSTEM = """You maintain Troy's long-term memory of Paul. Troy is Paul's personal AI
assistant. You get Troy's current memory and the latest exchange. Decide what, if anything,
Troy should remember for FUTURE conversations.

Keep only what Paul himself said (never your guesses or Troy's suggestions):
- preference: how Paul wants Troy to answer or work (length, tone, format, steps, voice,
  what to skip). A remark about just this one reply is NOT a standing preference unless Paul
  says it's how he likes things or to do it from now on.
- about: durable facts about Paul (role, workplace, tools, family members he mentions by role,
  hobbies that come up repeatedly).
- project: ongoing work and its stable decisions (names, goals, choices he made).
Honor explicit requests: "remember …" -> add it; "forget …"/"that's not true anymore" -> remove
or update. Prefer updating an existing line over adding a near-duplicate. One short line per
fact, written as a plain statement ("Prefers step-by-step instructions starting from the first
click"). Skip small talk and one-off tasks.

NEVER store: passwords, API keys, account/card/ID numbers; health or medical details; money
amounts (pay, balances, debts); religion, politics, race, sexual matters; anything about crimes
or abuse; private details about other people's lives; instructions to flatter Paul, agree with
everything, hide problems, or stop giving honest feedback.

Reply with ONLY this JSON (empty lists when nothing changes, which is most of the time):
{"add": [{"kind": "preference|about|project", "text": "..."}],
 "update": [{"id": "...", "text": "..."}],
 "remove": ["id", ...]}"""


def empty():
    return {"v": 1, "facts": [], "updated": 0}


def parse(raw):
    try:
        m = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return empty()
    if not isinstance(m, dict) or not isinstance(m.get("facts"), list):
        return empty()
    facts = [f for f in m["facts"] if isinstance(f, dict) and f.get("text") and f.get("id")]
    return {"v": 1, "facts": facts[:MAX_FACTS], "updated": float(m.get("updated") or 0)}


def merge(a, b):
    """Two copies (device + synced): the newer copy wins outright. Deletions must
    stick, so this is not a union."""
    a, b = parse(a), parse(b)
    return a if a["updated"] >= b["updated"] else b


def for_instructions(mem):
    """The block added to Troy's instructions on every message."""
    facts = parse(mem)["facts"]
    if not facts:
        return ""
    out = ["", "WHAT YOU KNOW ABOUT PAUL (learned from past chats with him):"]
    for kind, label in KINDS.items():
        lines = [f["text"] for f in facts if f.get("kind") == kind]
        if lines:
            out.append(label + ":")
            out += [f"- {t}" for t in lines]
    out.append("Follow his preferences without being reminded. Use the facts when they change "
               "the answer; don't recite them or say 'I remember' unless he asks what you know.")
    return "\n".join(out)


_SECRETISH = re.compile(r"sk-ant-|AIza[\w-]{10}|github_pat_|ghp_\w{10}|\b\d{9,}\b|password", re.I)


def apply_ops(mem, ops):
    """Apply what the learning pass decided. Returns (memory, changed?)."""
    mem = parse(mem)
    facts = {f["id"]: f for f in mem["facts"]}
    changed = False
    for fid in ops.get("remove") or []:
        if facts.pop(str(fid), None):
            changed = True
    for up in ops.get("update") or []:
        f = facts.get(str(up.get("id")))
        text = str(up.get("text", "")).strip()[:300]
        if f and text and text != f["text"] and not _SECRETISH.search(text):
            f["text"], f["t"] = text, time.time()
            changed = True
    have = {f["text"].lower() for f in facts.values()}
    for add in ops.get("add") or []:
        text = str(add.get("text", "")).strip()[:300]
        kind = add.get("kind") if add.get("kind") in KINDS else "about"
        if text and text.lower() not in have and not _SECRETISH.search(text):
            fid = uuid4().hex[:8]
            facts[fid] = {"id": fid, "kind": kind, "text": text, "t": time.time()}
            have.add(text.lower())
            changed = True
    if changed:
        newest = sorted(facts.values(), key=lambda f: f.get("t", 0), reverse=True)[:MAX_FACTS]
        mem = {"v": 1, "facts": sorted(newest, key=lambda f: f.get("t", 0)), "updated": time.time()}
    return mem, changed


def add_fact(mem, text, kind="about"):
    return apply_ops(mem, {"add": [{"kind": kind, "text": text}]})


def remove_fact(mem, fid):
    return apply_ops(mem, {"remove": [fid]})


def forget_all():
    m = empty()
    m["updated"] = time.time()
    return m


def _json_from(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1]) if s >= 0 else {}


def learn(claude_client, mem, paul_said, troy_said):
    """The learning pass. Returns the (possibly) updated memory and what changed,
    as short notes for the screen. Raises on API errors (caller logs them)."""
    mem = parse(mem)
    listing = "\n".join(f"[{f['id']}] ({f['kind']}) {f['text']}" for f in mem["facts"]) or "(nothing yet)"
    msg = claude_client.messages.create(
        model=LEARN_MODEL, max_tokens=800, system=LEARN_SYSTEM,
        messages=[{"role": "user", "content":
                   f"TROY'S CURRENT MEMORY:\n{listing}\n\nLATEST EXCHANGE\nPaul: {paul_said[:6000]}"
                   f"\n\nTroy: {troy_said[:3000]}"}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        ops = _json_from(raw)
    except ValueError:
        return mem, []
    before = {f["id"]: f["text"] for f in mem["facts"]}
    mem, changed = apply_ops(mem, ops)
    if not changed:
        return mem, []
    after = {f["id"]: f["text"] for f in mem["facts"]}
    notes = [f"Learned: {t}" for i, t in after.items() if i not in before]
    notes += [f"Updated: {t}" for i, t in after.items() if i in before and before[i] != t]
    notes += [f"Forgot: {t}" for i, t in before.items() if i not in after]
    return mem, notes


# ---- Synced copy in a PRIVATE GitHub repo ----------------------------------
class Sync:
    def __init__(self, token, repo):
        self.token, self.repo, self.sha = token, repo, None

    def _req(self, method, path, body=None):
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "troy-memory"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == "GET":
                return None
            raise RuntimeError(f"GitHub said {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from None

    def check_private(self):
        info = self._req("GET", "")
        if info is None:
            raise RuntimeError(f"can't find the memory repo {self.repo} (or the GitHub key can't see it)")
        if not info.get("private"):
            raise RuntimeError(f"{self.repo} is PUBLIC — Troy won't keep your memory there. Make it private.")
        return True

    def load(self):
        self.check_private()
        d = self._req("GET", f"/contents/{MEMORY_PATH}")
        if d is None:
            return empty()
        self.sha = d["sha"]
        return parse(base64.b64decode(d["content"]).decode("utf-8"))

    def save(self, mem):
        body = {"message": "Troy memory update",
                "content": base64.b64encode(json.dumps(parse(mem), indent=1).encode()).decode()}
        if self.sha:
            body["sha"] = self.sha
        try:
            r = self._req("PUT", f"/contents/{MEMORY_PATH}", body)
        except RuntimeError as e:
            if "409" not in str(e) and "422" not in str(e):
                raise
            # Another device saved first: take theirs, keep the newer copy, save again.
            theirs = self.load()
            mem = merge(mem, theirs)
            body["content"] = base64.b64encode(json.dumps(mem, indent=1).encode()).decode()
            body["sha"] = self.sha
            r = self._req("PUT", f"/contents/{MEMORY_PATH}", body)
        self.sha = r["content"]["sha"]
        return mem


def sync_from(secret_get):
    repo, token = secret_get("TROY_MEMORY_REPO"), secret_get("GITHUB_TOKEN")
    return Sync(token, repo) if (repo and token) else None


# ---- Thinking: how hard Troy thinks before answering ------------------------
THINK_MODES = {
    "Troy decides": "auto",
    "Always deep thinker": "deep",
    "Fast, but thinks": "fast_think",
}
FAST_MODEL = "claude-haiku-5-5"
SMART_MODEL = "claude-sonnet-5-5"
_REAL_WORK = re.compile(
    r"\b(why|how (do|does|can|should|would|to)|plan|compare|calculat|math|formula|code|script|"
    r"python|html|bug|fix|build|design|explain|analy[sz]|review|check|step[- ]by[- ]step|"
    r"write|draft|epr|excel|spreadsheet|tracker|permit|procedure|coordinate|survey|map|"
    r"estimate|decide|should i|pros and cons|figure out|troubleshoot|error|repair|recipe|budget)\b",
    re.I)


def needs_deep_thought(text, has_files):
    t = (text or "").strip()
    return has_files or len(t) > 280 or t.count("?") > 1 or bool(_REAL_WORK.search(t))


def thinking_plan(mode, text, has_files):
    """(model, thinking on?, label for the screen)."""
    if mode == "deep":
        return SMART_MODEL, True, "Thought it through · Sonnet"
    if mode == "fast_think":
        return FAST_MODEL, True, "Thought it through · Haiku"
    if needs_deep_thought(text, has_files):
        return SMART_MODEL, True, "Thought it through · Sonnet"
    return FAST_MODEL, False, "Quick answer · Haiku"
