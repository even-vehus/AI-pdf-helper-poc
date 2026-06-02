"""
PDF metadata extraction: PDF pages → Claude vision API → SQLite.

Usage:
    py extract.py                      # extract all PDFs in Nosted_data/
    py extract.py path/to/file.pdf     # extract one specific PDF
    py extract.py --reset              # drop and recreate DB, then extract all
"""

import json
import re
import sys
import base64
from pathlib import Path

import fitz  # PyMuPDF
import anthropic

import db
from config import ANTHROPIC_API_KEY, EXTRACTION_MODEL, MAX_IMAGE_DPI, PROMPTS_DIR, BATCH_SIZE, PDF_DIR, DB_PATH
from extract_catalog import extract_catalog, is_catalog_pdf

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _load_prompt() -> str:
    return (PROMPTS_DIR / "extraction.txt").read_text(encoding="utf-8")


def _page_to_base64(page: fitz.Page, dpi: int = MAX_IMAGE_DPI) -> str:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    return base64.standard_b64encode(pix.tobytes("png")).decode()


def _call_claude(images_b64: list[str], source_file: str, prompt: str) -> list[dict]:
    content = []
    for img in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img},
        })
    content.append({"type": "text", "text": f"Source file: {source_file}\n\n{prompt}"})

    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": content}],
    )
    raw = response.content[0].text.strip()
    # strip markdown code fences if the model wraps output despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw.strip())
    return json.loads(raw)


def extract_from_pdf(pdf_path: Path, prompt: str) -> list[dict]:
    doc = fitz.open(str(pdf_path))
    source_file = pdf_path.name
    all_products: list[dict] = []

    if len(doc) <= BATCH_SIZE * 2:
        # Small doc: send all pages in one call so Claude can correlate across pages
        # (e.g. page 1-of-2 + page 2-of-2 belong to the same product)
        images = [_page_to_base64(doc[i]) for i in range(len(doc))]
        products = _call_claude(images, source_file, prompt)
        for p in products:
            p.setdefault("source_file", source_file)
        all_products.extend(products)
    else:
        # Large catalog: process in page batches
        for start in range(0, len(doc), BATCH_SIZE):
            end = min(start + BATCH_SIZE, len(doc))
            images = [_page_to_base64(doc[i]) for i in range(start, end)]
            try:
                products = _call_claude(images, source_file, prompt)
                for p in products:
                    p.setdefault("source_file", source_file)
                all_products.extend(products)
                print(f"  pages {start + 1}–{end}: {len(products)} product(s)", flush=True)
            except Exception as exc:
                print(f"  pages {start + 1}–{end}: ERROR — {exc}", flush=True)

    return all_products


def import_pdf(pdf_path: Path, prompt: str):
    print(f"\nExtracting: {pdf_path.name}", flush=True)
    if is_catalog_pdf(pdf_path):
        print("  → catalog detected: using pdfplumber table extraction", flush=True)
        products = extract_catalog(pdf_path)
    else:
        print("  → drawing detected: using Claude vision", flush=True)
        products = extract_from_pdf(pdf_path, prompt)
    print(f"  → {len(products)} product(s) found", flush=True)

    for p in products:
        pid = db.insert_product(p)
        db.insert_dimensions(pid, p.get("dimensions") or {}, p.get("extra_dimensions"))
        db.insert_components(pid, p.get("components") or [])
        db.insert_standards(pid, p.get("related_standards") or [])
        name = p.get("product_name") or p.get("product_name_en") or "?"
        ident = p.get("item_number") or p.get("drawing_number") or p.get("vendor_part_number") or "—"
        print(f"    [id={pid}] {name} / {ident}", flush=True)


def main():
    args = sys.argv[1:]
    reset = "--reset" in args
    args = [a for a in args if a != "--reset"]

    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        print("Database reset.")

    db.init_db()
    prompt = _load_prompt()

    if args:
        targets = [Path(a) for a in args]
    else:
        targets = sorted(PDF_DIR.glob("*.pdf"))

    if not targets:
        print(f"No PDFs found in {PDF_DIR}")
        return

    for pdf in targets:
        if not pdf.exists():
            print(f"Not found: {pdf}")
            continue
        import_pdf(pdf, prompt)

    print("\nDone.")


if __name__ == "__main__":
    main()
