"""
Catalog PDF extraction using pdfplumber table parsing.

Used for structured tabular catalogs (produktkatalogshort.pdf) instead of
Claude vision — far more accurate on dense tables and essentially free to run.
"""

import re
from pathlib import Path

import pdfplumber

# ── category detection ──────────────────────────────────────────────────────

_CATEGORY_PATTERNS: list[tuple[str, str]] = [
    # Specific compound terms first, broad terms last
    (r"\bkjettingredskap|\bchain sling|\blifting sling", "Kjettingredskaper"),
    (r"\bkoplingselementer\b|\bcoupling comp", "Koplingselementer"),
    (r"\bl.fteåk|\bspreader beam|\bspredebom", "Løfteåk"),
    (r"\bl.ftepunkt|\blifting point|\beye bolt|\b.yebolt", "Løftepunkt"),
    (r"\bsjakkel|\bshackle", "Sjakler"),
    (r"\bmykl.ft|\bwebsling|\bround sling|\brundsling|\bb.ndstropp", "Mykløft"),
    (r"\bst.ltau|\bwire rope", "Ståltau"),
    (r"\brov\b", "ROV-produkter"),
    (r"\bhavbruk|\baquaculture|\bfortøy", "Havbruk"),
    (r"\bgrade 100\b|\bg-100\b", "Grade 100"),
    (r"\brustfri|\bstainless|\bsyrefast", "Rustfritt"),
    (r"\bsurring|\blashing", "Surringsutstyr"),
    # Kroker/Løkker: use specific Norwegian terms, not generic 'link'/'ring'
    (r"\bkrok\b|\bhook\b|\bkarabinkrok", "Kroker"),
    (r"\bkoplingsløkke|\bB-l.kke|\bA-l.kke|\bsl.yfe|\bsl.ife|\bl.kker\b", "Løkker"),
    # Kjetting: broad match, but after all more-specific categories
    (r"\bkjetting|\bchain\b", "Kjetting"),
]


def _detect_category(text: str) -> str | None:
    t = text.lower()
    for pattern, cat in _CATEGORY_PATTERNS:
        if re.search(pattern, t):
            return cat
    return None


# ── header normalization ─────────────────────────────────────────────────────

# Maps normalized column label → schema field name
_HEADER_MAP: dict[str, str] = {
    # item number
    "varenr": "item_number",
    "item no": "item_number",
    "item no.": "item_number",
    "art.nr": "item_number",
    "art. nr": "item_number",
    "art no": "item_number",
    # model / product name
    "modell": "model_name",
    "model": "model_name",
    "type": "model_name",
    "betegnelse": "product_name_col",
    "description": "product_name_col",
    # chain dimension string
    "dim.": "dim_str",
    "dim": "dim_str",
    "dimensjon": "dim_str",
    "code": "dim_str",
    # for-chain dimension
    "for kjetting": "for_chain_dim",
    "forchaindim.": "for_chain_dim",
    "for chain dim.": "for_chain_dim",
    # WLL
    "wll": "wll_tonnes",
    "wll 4:1 tonn": "wll_tonnes",
    "wll 4:1 tonn/ton": "wll_tonnes",
    "4:1 tonn/ton": "wll_tonnes",
    "4:1 tonn": "wll_tonnes",
    "tonn": "wll_tonnes",
    "ton": "wll_tonnes",
    "swl": "wll_tonnes",
    "swl [1]": "wll_raw",          # aquaculture tables: sub-col may be kN; tonn col follows
    "maks brukslast": "wll_raw",   # may be in kN or tonn (see sub-header)
    "maks brukslast [1]": "wll_raw",
    "working load limit": "wll_tonnes",
    "capacity": "wll_raw",
    # proof force
    "pr vekraft": "proof_force_kn",  # ø stripped
    "prvekraft": "proof_force_kn",
    "prøvekraft": "proof_force_kn",
    "proof force": "proof_force_kn",
    "sf": "proof_force_kn",
    # break force
    "min. bruddkraft": "min_break_force_kn",
    "bruddkraft": "min_break_force_kn",
    "break force": "min_break_force_kn",
    "breaking force": "min_break_force_kn",
    "min. break force": "min_break_force_kn",
    "mbl": "min_break_force_kn",
    # weight
    "vekt": "weight_kg",
    "weight": "weight_kg",
    "n.w.": "weight_kg",
    "kg": "weight_kg",
    # dimensional columns
    "kg/m": "kg_per_m",
    "d": "dim_d_mm",
    "d mm": "dim_d_mm",
    "d, mm": "dim_d_mm",
    "l": "dim_l_mm",
    "l mm": "dim_l_mm",
    "l, mm": "dim_l_mm",
    "b": "dim_b_mm",
    "b mm": "dim_b_mm",
    "b, mm": "dim_b_mm",
    "t": "dim_t_mm",
    "a": "dim_a_mm",
    "k": "dim_k_mm",
    "h": "dim_h_mm",
    "p": "dim_p_mm",
    "n": "dim_n_mm",
    "r": "dim_r_mm",
    "e": "dim_e_mm",
    "working width": "dim_working_width_mm",
    "working width z": "dim_working_width_mm",
}


def _norm_header(s: str | None) -> str:
    if not s:
        return ""
    # strip PDF encoding artifacts (ø→?, å→?, etc.)
    s = re.sub(r"[�\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    return s.strip().lower()


def _flatten_headers(rows: list[list]) -> list[str]:
    """
    Merge two header rows (with None for merged cells) into flat column labels.
    row0 = top-level labels; row1 = sub-labels or units.
    None in row0 means the cell is a continuation of the previous non-None label.
    """
    if not rows:
        return []
    row0 = rows[0]
    row1 = rows[1] if len(rows) > 1 else [None] * len(row0)
    # Pad to same length
    maxlen = max(len(row0), len(row1))
    row0 = list(row0) + [None] * (maxlen - len(row0))
    row1 = list(row1) + [None] * (maxlen - len(row1))

    # Forward-fill None cells in row0 (merged header spans)
    last_top = ""
    filled = []
    for top in row0:
        if top is not None:
            last_top = _norm_header(top)
        filled.append(last_top)

    result = []
    for top, sub in zip(filled, row1):
        sub_n = _norm_header(sub)
        if sub_n and sub_n != top:
            # combine only if sub adds information (not just units like kN/mm)
            result.append(sub_n)
        else:
            result.append(top)
    return result


def _map_headers(flat: list[str]) -> list[str]:
    """Map each flat header string to a schema field name."""
    result = []
    for h in flat:
        # Exact match first
        mapped = _HEADER_MAP.get(h)
        if mapped is None:
            # Strip trailing bracket annotations like "[1]" and retry
            stripped = re.sub(r"\s*\[.*?\]$", "", h).strip()
            mapped = _HEADER_MAP.get(stripped)
        result.append(mapped or f"_extra_{h[:20]}")
    return result


# ── numeric helpers ──────────────────────────────────────────────────────────

def _to_float(s: str | None) -> float | None:
    if not s:
        return None
    s = str(s).strip().replace(",", ".").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _looks_like_item_number(s: str | None) -> bool:
    if not s:
        return False
    s = s.strip()
    return bool(re.match(r"^[0-9A-Z][0-9A-Z/\-]{3,}", s))


# ── section title extraction ─────────────────────────────────────────────────

_SKIP_LINES = re.compile(
    r"^(nosted\.com|www\.|nnnooosssttteeeddd|page \d|\d+$|\s*$)", re.IGNORECASE
)
_WATERMARK = re.compile(r"[a-z]{3,}\.\.\.[a-z]{3,}", re.IGNORECASE)  # "nnn...ccc" logo artifacts
_HEADER_LINE = re.compile(
    r"^(varenr|item no|code|dim\.|wll|pr[øo]ve|min\.|mål|m.l|kg/m)",
    re.IGNORECASE,
)


def _extract_sections_from_text(text: str) -> list[str]:
    """Return plausible section-title lines from page text."""
    lines = [l.strip() for l in text.split("\n")]
    sections = []
    for line in lines:
        if not line or _SKIP_LINES.search(line):
            continue
        if _WATERMARK.search(line):
            continue
        if _HEADER_LINE.search(line):
            continue
        # Keep lines that look like product names (mixed case, >8 chars, not all numbers)
        if len(line) > 8 and not re.match(r"^[\d\s.,]+$", line):
            sections.append(line)
    return sections


# ── main extraction ──────────────────────────────────────────────────────────

def extract_catalog(pdf_path: Path) -> list[dict]:
    """Extract all product rows from a tabular catalog PDF."""
    source_file = pdf_path.name
    products: list[dict] = []
    current_category: str | None = None
    current_section: str | None = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            sections = _extract_sections_from_text(text)

            # Detect category from the TOP of the page only (first ~300 chars)
            # Avoids false positives from description text (e.g. "surring" in chain pages)
            cat = _detect_category(text[:300])
            if cat:
                current_category = cat

            if sections:
                # Skip lines that are just the category header ("Kroker / Hooks", etc.)
                # — these contain a "/" or are very short (≤ 20 chars)
                meaningful = [
                    s for s in sections
                    if len(s) > 20 and " / " not in s and not s.lower().startswith(("kjetting", "chain", "koplings"))
                ]
                current_section = meaningful[0] if meaningful else sections[0] if sections else current_section

            tables = page.extract_tables()
            # Only process tables with at least 4 columns and 3 rows (header + 2 data)
            for table in tables:
                if not table or len(table) < 3:
                    continue
                # Skip tables that are clearly layout frames
                max_cols = max(len(r) for r in table if r)
                if max_cols < 4:
                    continue

                rows = _parse_table(
                    table, source_file, page_num,
                    current_category, current_section,
                )
                products.extend(rows)

    return products


def _parse_table(
    table: list[list],
    source_file: str,
    page_num: int,
    category: str | None,
    section: str | None,
) -> list[dict]:
    """Turn a single pdfplumber table into a list of product dicts."""
    if not table:
        return []

    # Detect header rows: rows before the first row whose first cell looks like a part number
    header_rows: list[list] = []
    data_start = 0
    for i, row in enumerate(table):
        first_cell = (row[0] or "").strip() if row else ""
        if _looks_like_item_number(first_cell):
            data_start = i
            break
        header_rows.append(row)

    if not header_rows or data_start == 0:
        return []  # no recognizable header → skip table

    flat_headers = _flatten_headers(header_rows[:2])  # use first two header rows
    field_names = _map_headers(flat_headers)

    results: list[dict] = []
    for row in table[data_start:]:
        if not row:
            continue
        # Skip sub-header rows that repeat inside the table
        first = (row[0] or "").strip()
        if not _looks_like_item_number(first):
            continue

        p = _row_to_product(row, field_names, source_file, page_num, category, section)
        if p:
            results.append(p)

    return results


def _row_to_product(
    row: list,
    field_names: list[str],
    source_file: str,
    page_num: int,
    category: str | None,
    section: str | None,
) -> dict | None:
    raw: dict[str, str | None] = {}
    for i, field in enumerate(field_names):
        val = row[i] if i < len(row) else None
        raw[field] = (val or "").strip() or None

    item_number = raw.get("item_number")
    if not item_number:
        return None

    # WLL: may be directly in wll_tonnes or in wll_raw (which might be kN)
    wll = _to_float(raw.get("wll_tonnes"))
    if wll is None:
        wll_raw = _to_float(raw.get("wll_raw"))
        if wll_raw and wll_raw > 100:
            # Likely in kN → convert to tonnes (÷ 9.81)
            wll = round(wll_raw / 9.81, 3)
        elif wll_raw:
            wll = wll_raw  # already tonnes

    # Derive product name: section heading + dim, or model column if present
    model = raw.get("model_name") or raw.get("product_name_col")
    dim = raw.get("dim_str")
    if model and dim:
        name = f"{section or ''} {model} {dim}".strip()
    elif model:
        name = f"{section or ''} {model}".strip()
    elif dim:
        name = f"{section or ''} {dim}".strip()
    else:
        name = section or item_number or ""

    # Extra dimensions (dim_* fields) + kg/m as a named attribute
    extra_dims = []
    for k, v in raw.items():
        if k.startswith("dim_") and k != "dim_str":
            fv = _to_float(v)
            if fv is not None:
                extra_dims.append({"key": k.replace("dim_", "").replace("_mm", ""), "value_mm": fv})
    kg_per_m = _to_float(raw.get("kg_per_m"))
    if kg_per_m is not None:
        extra_dims.append({"key": "kg_per_m", "value_mm": kg_per_m})  # stored as value_mm for simplicity

    tags = []
    if category:
        tags.append(category.lower())
    if dim:
        tags.append(dim.lower())
    if wll:
        tags.append(f"{wll}t")
    for_chain = raw.get("for_chain_dim")
    if for_chain:
        tags.append(f"for {for_chain}mm chain")
    # Add normalised Norwegian search synonyms so both spellings are searchable
    _SYNONYMS = {
        "sjakler": "sjakkel",
        "sjakkel": "sjakler",
        "krok": "hook",
        "hook": "krok",
        "kjetting": "chain",
        "chain": "kjetting",
        "løkke": "link",
        "link": "løkke",
    }
    extra_tags = []
    for tag in list(tags):
        syn = _SYNONYMS.get(tag.lower())
        if syn and syn not in tags:
            extra_tags.append(syn)
    tags.extend(extra_tags)

    description_parts = []
    if section:
        description_parts.append(section)
    if dim:
        description_parts.append(f"dim {dim}")
    if wll:
        description_parts.append(f"WLL {wll} t")
    weight = _to_float(raw.get("weight_kg"))
    if weight:
        description_parts.append(f"{weight} kg")

    return {
        "source_file": source_file,
        "source_page": page_num,
        "source_type": "catalog_row",
        "product_name": name,
        "product_name_en": None,
        "item_number": item_number,
        "drawing_number": None,
        "vendor_part_number": None,
        "category": category,
        "wll_tonnes": wll,
        "proof_force_kn": _to_float(raw.get("proof_force_kn")),
        "min_break_force_kn": _to_float(raw.get("min_break_force_kn")),
        "weight_kg": weight,
        "standard": None,
        "certification": None,
        "surface_treatment": None,
        "material": None,
        "designed_for": raw.get("for_chain_dim"),
        "date": None,
        "revision": None,
        "status": "released",
        "manufacturer": "Nøsted &",
        "related_standards": [],
        "dimensions": {},
        "extra_dimensions": extra_dims,
        "components": [],
        "tags": tags,
        "full_description": ". ".join(description_parts) + ".",
    }


def is_catalog_pdf(pdf_path: Path) -> bool:
    """Return True if pdfplumber finds substantial product tables in the first few pages."""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages_to_check = min(3, len(pdf.pages))
            big_table_pages = 0
            for i in range(pages_to_check):
                tables = pdf.pages[i].extract_tables()
                if any(t and len(t) >= 3 and t[0] and len(t[0]) >= 4 for t in tables):
                    big_table_pages += 1
            return big_table_pages >= 2
    except Exception:
        return False
