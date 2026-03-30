"""
PDF Processor — uses PyMuPDF (fitz) for precise page-level and section-level extraction.
Each chunk carries metadata: paper_id, filename, page_number, section, char_offset.
"""

"""
Transformation layer for PDF-to-Semantic-Fragments.
Handles metadata extraction and normalization.
"""
import fitz  # PyMuPDF
import re
import os
from typing import List, Dict, Any


# ── helpers ─────────────────────────────────────────────────────────────────

SECTION_PATTERNS = [
    r"^(abstract|introduction|background|related work|methodology|methods|"
    r"experiments?|results?|discussion|conclusion|references?|"
    r"acknowledgements?|appendix|limitations?|future work)",
    r"^\d+[\.\s]+[A-Z][a-zA-Z\s]+$",   # "1. Introduction"
    r"^[IVXLCDM]+\.\s+[A-Z]",           # "II. Related Work"
]
SECTION_RE = re.compile("|".join(SECTION_PATTERNS), re.IGNORECASE | re.MULTILINE)


def _detect_section(text: str) -> str:
    """Return the first section heading found in a block of text, or 'Body'."""
    for line in text.split("\n"):
        line = line.strip()
        if line and SECTION_RE.match(line):
            return line[:80]
    return "Body"


def _clean(text: str) -> str:
    """Light cleanup: collapse whitespace, remove hyphenation artifacts."""
    text = re.sub(r"-\n", "", text)          # dehyphenate
    text = re.sub(r"\n{3,}", "\n\n", text)   # max 2 blank lines
    text = re.sub(r" {2,}", " ", text)        # collapse spaces
    return text.strip()


# ── main extraction ──────────────────────────────────────────────────────────

def extract_pages(pdf_path: str, paper_id: str, filename: str) -> List[Dict[str, Any]]:
    """
    Return a list of page-level dicts:
      { text, page_number, paper_id, filename, section }
    """
    doc = fitz.open(pdf_path)
    pages = []
    current_section = "Abstract"

    for page_num, page in enumerate(doc, start=1):
        raw = page.get_text("text")          # plain text
        cleaned = _clean(raw)
        if not cleaned:
            continue
        detected = _detect_section(cleaned)
        if detected != "Body":
            current_section = detected

        pages.append({
            "text": cleaned,
            "page_number": page_num,
            "paper_id": paper_id,
            "filename": filename,
            "section": current_section,
        })

    doc.close()
    return pages


def chunk_pages(
    pages: List[Dict[str, Any]],
    chunk_size: int = 800,
    overlap: int = 150,
) -> List[Dict[str, Any]]:
    """
    Split each page into overlapping character-based chunks.
    Preserves all metadata + adds chunk_index.
    """
    chunks = []
    for page in pages:
        text = page["text"]
        start = 0
        chunk_idx = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            if chunk_text.strip():
                chunks.append({
                    **page,
                    "chunk_text": chunk_text,
                    "chunk_index": chunk_idx,
                    "char_start": start,
                })
            start += chunk_size - overlap
            chunk_idx += 1
    return chunks


def get_paper_metadata(pdf_path: str) -> Dict[str, Any]:
    """Extract title, author guesses, page count from the PDF."""
    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}
    page_count = doc.page_count

    # Try to extract title from first-page text if metadata missing
    title = meta.get("title", "").strip()
    if not title and doc.page_count > 0:
        first_text = doc[0].get_text("text")
        lines = [l.strip() for l in first_text.split("\n") if l.strip()]
        title = lines[0][:120] if lines else os.path.basename(pdf_path)

    doc.close()
    return {
        "title": title or os.path.basename(pdf_path),
        "author": meta.get("author", "Unknown"),
        "page_count": page_count,
        "subject": meta.get("subject", ""),
    }
