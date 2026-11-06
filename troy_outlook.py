"""
troy_outlook.py - Troy reads your email and writes DRAFTS. He never sends.

Plain English:
  Classic Outlook for Windows lets other programs read it through COM. Troy
  uses that to list, search and read your mail (LOOK level), and to write a
  draft or a draft reply (DO level). The draft opens on your screen; YOU read
  it and press Send. There is no send function anywhere in this file.

  It works with every account set up in classic Outlook (work, Yahoo, Gmail).
  The "new Outlook" (the toggle at the top right of Outlook) has no COM
  doorway - switch that toggle off to use classic Outlook with Troy.
"""

from __future__ import annotations

import re

try:
    import pythoncom
    import win32com.client
    HAS_COM = True
except Exception as _e:          # noqa: BLE001
    HAS_COM = False
    _COM_ERROR = str(_e)

INBOX, SENT, DRAFTS = 6, 5, 16
FOLDERS = {"inbox": INBOX, "sent": SENT, "drafts": DRAFTS}
MAIL_CLASS = 43                  # olMail - skip meeting requests, receipts, etc.


def ok(**kw):
    return {"ok": True, **kw}


def fail(reason, **kw):
    return {"ok": False, "error": reason, **kw}


def _ns():
    if not HAS_COM:
        raise RuntimeError(f"Email tools need Windows with pywin32 installed ({_COM_ERROR}).")
    pythoncom.CoInitialize()
    try:
        app = win32com.client.Dispatch("Outlook.Application")
        return app, app.GetNamespace("MAPI")
    except Exception as e:       # noqa: BLE001
        raise RuntimeError("Couldn't reach classic Outlook. If Outlook shows a 'New Outlook' "
                           f"toggle at the top right, turn it off and try again. ({e})")


def _folder(ns, folder="inbox", account=""):
    kind = FOLDERS.get(folder.lower().strip(), INBOX)
    if not account:
        return ns.GetDefaultFolder(kind)
    for store in ns.Stores:
        if account.lower() in str(store.DisplayName).lower():
            return store.GetDefaultFolder(kind)
    raise RuntimeError(f"No Outlook account matching '{account}'. Use outlook_accounts.")


def _clean(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:n]


def _summary(m):
    return {"id": m.EntryID, "from": str(m.SenderName), "subject": str(m.Subject),
            "received": str(m.ReceivedTime)[:16], "unread": bool(m.UnRead),
            "preview": _clean(m.Body, 200)}


def _latest(folder, limit):
    items = folder.Items
    items.Sort("[ReceivedTime]", True)
    out, m = [], items.GetFirst()
    while m is not None and len(out) < limit:
        if getattr(m, "Class", None) == MAIL_CLASS:
            out.append(m)
        m = items.GetNext()
    return out


# ---------------------------------------------------------------- LOOK
def outlook_accounts() -> dict:
    _, ns = _ns()
    return ok(accounts=[str(s.DisplayName) for s in ns.Stores])


def outlook_list(count: int = 10, unread_only: bool = False, folder: str = "inbox",
                 account: str = "") -> dict:
    _, ns = _ns()
    f = _folder(ns, folder, account)
    count = max(1, min(int(count), 50))
    mails = _latest(f, 400 if unread_only else count)
    if unread_only:
        mails = [m for m in mails if m.UnRead][:count]
    return ok(folder=str(f.Name), unread_in_folder=f.UnReadItemCount,
              emails=[_summary(m) for m in mails])


def outlook_search(text: str, count: int = 10, folder: str = "inbox", account: str = "",
                   look_back: int = 300) -> dict:
    """Search the newest emails' sender, subject and body for some words."""
    _, ns = _ns()
    f = _folder(ns, folder, account)
    words = [w for w in text.lower().split() if w]
    hits = []
    for m in _latest(f, max(20, min(int(look_back), 1000))):
        hay = f"{m.SenderName} {m.Subject} {str(m.Body)[:3000]}".lower()
        if all(w in hay for w in words):
            hits.append(_summary(m))
            if len(hits) >= max(1, min(int(count), 30)):
                break
    return ok(searched=f"newest {look_back} in {f.Name}", matches=hits)


def outlook_read(email_id: str) -> dict:
    _, ns = _ns()
    m = ns.GetItemFromID(email_id)
    atts = [m.Attachments.Item(i + 1).FileName for i in range(m.Attachments.Count)]
    return ok(**_summary(m), to=str(m.To), cc=str(m.CC), attachments=atts,
              body=str(m.Body)[:8000])


# ---------------------------------------------------------------- DO (draft only)
def outlook_draft(body: str, to: str = "", subject: str = "", reply_to_id: str = "",
                  reply_all: bool = False) -> dict:
    """Write a new email or a reply as a DRAFT and show it. Paul presses Send himself."""
    app, ns = _ns()
    if reply_to_id:
        orig = ns.GetItemFromID(reply_to_id)
        mail = orig.ReplyAll() if reply_all else orig.Reply()
        mail.Body = body.rstrip() + "\n\n" + str(mail.Body)
        if to:
            mail.To = to
    else:
        if not to:
            return fail("A new email needs a 'to' address.")
        mail = app.CreateItem(0)
        mail.To, mail.Subject, mail.Body = to, subject, body
    mail.Save()                      # lands in Drafts
    mail.Display(False)              # opens on screen; nothing is sent
    return ok(draft_saved=True, to=str(mail.To), subject=str(mail.Subject),
              note="Draft is open on the screen and in Drafts. Paul reads it and presses Send.")


REGISTRY = {
    "outlook_accounts": (outlook_accounts, 1),
    "outlook_list":     (outlook_list, 1),
    "outlook_search":   (outlook_search, 1),
    "outlook_read":     (outlook_read, 1),
    "outlook_draft":    (outlook_draft, 2),
}
ALWAYS_ASK: set = set()

DECLARATIONS = [
    {"name": "outlook_accounts", "description": "List the email accounts in Outlook.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "outlook_list",
     "description": "List the newest emails (sender, subject, time, unread, a preview, and an id "
                    "for outlook_read). folder: inbox, sent or drafts.",
     "parameters": {"type": "object", "properties": {
         "count": {"type": "integer"}, "unread_only": {"type": "boolean"},
         "folder": {"type": "string"}, "account": {"type": "string"}}, "required": []}},
    {"name": "outlook_search",
     "description": "Find emails whose sender, subject or body contain all the given words.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": "string"}, "count": {"type": "integer"},
         "folder": {"type": "string"}, "account": {"type": "string"},
         "look_back": {"type": "integer", "description": "How many recent emails to search."}},
         "required": ["text"]}},
    {"name": "outlook_read", "description": "Read one email in full by its id.",
     "parameters": {"type": "object", "properties": {"email_id": {"type": "string"}},
                    "required": ["email_id"]}},
    {"name": "outlook_draft",
     "description": "Write a DRAFT email or reply and open it on screen. It is never sent - Paul "
                    "reviews it and presses Send himself. Use reply_to_id to reply to an email.",
     "parameters": {"type": "object", "properties": {
         "body": {"type": "string"}, "to": {"type": "string"}, "subject": {"type": "string"},
         "reply_to_id": {"type": "string"}, "reply_all": {"type": "boolean"}},
         "required": ["body"]}},
]
