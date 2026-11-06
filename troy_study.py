"""Split a PDF (like an FPC procedure) into numbered sections Troy can read aloud.

Plain-English summary:
- Pull the words out of each page with pypdf (free, no AI call).
- Remove lines that repeat on many pages (headers/footers like "Page 3 of 39").
- Start a new section at numbered headings such as "2.0 SCOPE" or
  "4.1 Site General Manager".
- A table of contents at the front lists the same headings with no text under
  them; those empty copies are dropped.
- Very long sections are cut into parts at paragraph breaks so each reading
  stays a few minutes long.
- No headings found? Fall back to one section per page.
- No words at all? The PDF is scanned pictures; the caller tells Paul.
"""

from __future__ import annotations

import io
import re
from collections import Counter

from pypdf import PdfReader

MAX_SECTION_CHARS = 2_500     # about 2-3 minutes of reading aloud
MIN_BODY_CHARS = 25           # shorter than this = a table-of-contents line

# "2.0 SCOPE", "4.1 Site General Manager", "5.2.3 Isolation" — number with at
# least one dot, then a title that starts with a letter and isn't a sentence.
HEADING = re.compile(
    r"^\s*(?P<num>\d{1,2}(?:\.\d{1,2}){1,3})\.?\s+(?P<title>[A-Za-z][^\n]{1,90}?)\s*$"
)
PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d+\s*(of\s*\d+)?\s*$", re.I)


def _page_lines(pdf_bytes: bytes) -> list[list[str]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append([ln.rstrip() for ln in text.splitlines()])
    return pages


def _strip_repeats(pages: list[list[str]]) -> list[list[str]]:
    """Drop headers/footers: lines that appear on 30%+ of pages, and page numbers."""
    if len(pages) >= 3:
        counts = Counter(
            ln.strip() for lines in pages for ln in set(lines) if ln.strip()
        )
        limit = max(2, int(len(pages) * 0.3))
        repeated = {ln for ln, n in counts.items() if n >= limit}
    else:
        repeated = set()
    cleaned = []
    for lines in pages:
        keep = []
        for ln in lines:
            s = ln.strip()
            if s in repeated:
                continue
            # "Page 3 of 39" style lines, even when the number changes
            if PAGE_NUMBER.match(s) or re.match(r"^\s*page\s+\d+\s+of\s+\d+\s*$", s, re.I):
                continue
            keep.append(ln)
        cleaned.append(keep)
    return cleaned


def _is_heading(line: str):
    m = HEADING.match(line)
    if not m:
        return None
    title = m.group("title").strip()
    # A sentence (ends with a period, or very long) is body text, not a title.
    if title.endswith((".", ",", ";")) or len(title.split()) > 12:
        return None
    # Dotted leaders in a table of contents: "2.0 SCOPE ........ 3"
    title = re.sub(r"[.\s·]{4,}\d*\s*$", "", title).strip()
    if not title:
        return None
    return m.group("num"), title


def _tidy(text: str) -> str:
    """Join lines that were wrapped mid-sentence; keep paragraph breaks."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    lines = text.split("\n")
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            out.append("")
            continue
        starts_new = bool(re.match(r"^([a-z]\.|\d+\.|[•\-–▪●○]|\(?[a-z0-9]\))\s", ln, re.I))
        if out and out[-1] and not starts_new and not out[-1].endswith((":", ".", "?", "!")):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _split_long(num: str, title: str, body: str) -> list[dict]:
    if len(body) <= MAX_SECTION_CHARS:
        return [{"num": num, "title": title, "text": body}]
    paras = [p for p in re.split(r"\n\s*\n|\n(?=[a-z0-9]{1,3}[.)]\s)", body) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > MAX_SECTION_CHARS:
            chunks.append(cur.strip())
            cur = ""
        cur += p.strip() + "\n\n"
    if cur.strip():
        chunks.append(cur.strip())
    # a single giant paragraph: cut at sentence ends
    final = []
    for c in chunks:
        while len(c) > MAX_SECTION_CHARS * 1.3:
            cut = c.rfind(". ", 0, MAX_SECTION_CHARS)
            cut = cut + 1 if cut > 200 else MAX_SECTION_CHARS
            final.append(c[:cut].strip())
            c = c[cut:].strip()
        final.append(c)
    n = len(final)
    return [
        {"num": num, "title": f"{title} (part {i} of {n})", "text": t}
        for i, t in enumerate(final, 1)
    ]


def garbled(text: str) -> bool:
    """True when the "words" pulled out are font codes, not words.

    Some company PDFs use fonts that store letters as code numbers, so text
    comes out like "/0/1/2/3/i255/5/i255/13/22". Real procedure text is
    mostly letters and spaces with few slashes.
    """
    body = re.sub(r"\s", "", text)
    if len(body) < 40:
        return False
    slashes = body.count("/") / len(body)
    letters = sum(ch.isalpha() for ch in body) / len(body)
    code_runs = len(re.findall(r"(?:/[A-Za-z]?\d{1,4}){4,}", text))
    words = re.findall(r"[A-Za-z]{3,}", text)
    word_chars = sum(len(w) for w in words) / len(body)
    return slashes > 0.08 or code_runs >= 3 or (letters < 0.45 and word_chars < 0.35)


def split_sections(pdf_bytes: bytes) -> dict:
    """Return {"sections": [{num, title, text}], "pages": n, "method": ...}.

    method is "headings", "pages", "scanned" (no words found) or "garbled"
    (font codes instead of words). For the last two the caller can have the
    pages read from pictures and pass the text to split_page_texts().
    """
    pages = _strip_repeats(_page_lines(pdf_bytes))
    n_pages = len(pages)
    all_text = "\n".join("\n".join(p) for p in pages)
    if len(re.sub(r"\s", "", all_text)) < 40:
        return {"sections": [], "pages": n_pages, "method": "scanned"}
    if garbled(all_text):
        return {"sections": [], "pages": n_pages, "method": "garbled"}
    return _split_pages(pages)


def split_page_texts(page_texts: list[str]) -> dict:
    """Same splitting, for page text that was read from page pictures."""
    pages = _strip_repeats([[ln.rstrip() for ln in t.splitlines()] for t in page_texts])
    return _split_pages(pages)


def page_images(pdf_bytes: bytes, max_side: int = 1600):
    """Yield each page as JPEG bytes (for reading by eye when the text is codes)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        for i in range(len(doc)):
            page = doc[i]
            w, h = page.get_size()                      # points (1/72 inch)
            scale = max_side / max(w, h)
            img = page.render(scale=scale).to_pil().convert("RGB")
            out = io.BytesIO()
            img.save(out, "JPEG", quality=82)
            page.close()
            yield out.getvalue()
    finally:
        doc.close()


def _split_pages(pages: list[list[str]]) -> dict:
    n_pages = len(pages)

    # Walk every line; a heading opens a new section.
    raw = []          # [num, title, [lines]]
    intro = []
    for lines in pages:
        for ln in lines:
            h = _is_heading(ln)
            if h:
                raw.append([h[0], h[1], []])
            elif raw:
                raw[-1][2].append(ln)
            else:
                intro.append(ln)

    sections = []
    parent = None     # e.g. ("4.0", "RESPONSIBILITIES") with only 4.1, 4.2 under it
    for num, title, body_lines in raw:
        body = _tidy("\n".join(body_lines))
        if len(body) < MIN_BODY_CHARS:
            # A table-of-contents entry, or a heading whose only content is
            # sub-sections ("4.0 RESPONSIBILITIES" then "4.1 ...").
            parent = (num, title)
            continue
        group = ""
        if parent and num.startswith(parent[0].split(".")[0] + ".") and num != parent[0]:
            group = f"{parent[0]} {parent[1]}"
        elif parent and not num.startswith(parent[0].split(".")[0] + "."):
            parent = None
        for part in _split_long(num, title, body):
            part["group"] = group
            sections.append(part)

    if len(sections) >= 3:
        intro_text = _tidy("\n".join(intro))
        if len(intro_text) >= 200:
            first = _split_long("", "Opening page", intro_text)[0]
            first["group"] = ""
            sections.insert(0, first)
        return {"sections": sections, "pages": n_pages, "method": "headings"}

    # No usable headings: one section per page.
    by_page = []
    for i, lines in enumerate(pages, 1):
        body = _tidy("\n".join(lines))
        if body:
            for part in _split_long("", f"Page {i}", body):
                part["group"] = ""
                by_page.append(part)
    return {"sections": by_page, "pages": n_pages, "method": "pages"}


def sentences(text: str) -> list[str]:
    """Split text into sentence-sized pieces for read-along highlighting."""
    parts = re.split(r"(?<=[.!?:;])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]
