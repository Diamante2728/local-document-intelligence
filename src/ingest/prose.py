"""Prose extraction: PyMuPDF page text -> page-anchored chunks for the embedding index.

# DECISION: chunking size/strategy
# Default: per-page, paragraph-aware chunking. Paragraphs (split on blank lines) are packed
# into chunks up to `max_chars` (800 chars, ~150-200 tokens); a paragraph longer than the cap
# is itself split into overlapping windows (`overlap` chars). Chunks NEVER span two pages.
#
# Why: every chunk needs a single, honest page number for its {doc, page} citation. A chunk
# that spans pages 12-13 forces picking one page to cite, which silently misattributes
# whichever half of the paragraph fell on the other page.
#
# Rejected alternative: fixed-size sliding window over the whole document's concatenated text,
# ignoring page boundaries (the more common RAG default). Rejected specifically because it
# breaks per-page citation precision, which this project's trust requirements treat as
# non-negotiable (constraint #3) — worth the slightly less even chunk sizes.
"""
CHUNK_MAX_CHARS = 800
CHUNK_OVERLAP = 100

import fitz  # pymupdf


def chunk_page_text(text, max_chars=CHUNK_MAX_CHARS, overlap=CHUNK_OVERLAP):
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks = []
    current = ""
    for para in paragraphs:
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(para):
                end = start + max_chars
                chunks.append(para[start:end])
                if end >= len(para):
                    break
                start = end - overlap
        elif current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para

    if current:
        chunks.append(current)
    return chunks


def extract_prose_chunks(pdf_path, doc_id, max_chars=CHUNK_MAX_CHARS, overlap=CHUNK_OVERLAP):
    """Returns (chunk_rows, breakages, num_pages).

    chunk_rows: list of (doc_id, chunk_id, page, text)
    """
    chunk_rows = []
    breakages = []

    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    try:
        for page_idx in range(num_pages):
            page_num = page_idx + 1
            try:
                text = doc[page_idx].get_text("text")
            except Exception as e:
                breakages.append({
                    "doc_id": doc_id, "page": page_num,
                    "reason": f"get_text() raised {type(e).__name__}: {e}",
                })
                continue

            if not text.strip():
                breakages.append({
                    "doc_id": doc_id, "page": page_num,
                    "reason": "no extractable text — likely scanned/image-only page (OCR not run)",
                })
                continue

            for i, chunk_text in enumerate(chunk_page_text(text, max_chars, overlap)):
                chunk_id = f"{doc_id}_p{page_num}_c{i}"
                chunk_rows.append((doc_id, chunk_id, page_num, chunk_text))
    finally:
        doc.close()

    return chunk_rows, breakages, num_pages
