import json
import sqlite3

from config import DB_PATH, DRAWINGS_DB_PATH, USE_CATALOG_DB

# IDs from extracted_drawings.db are offset by this value to avoid collision with products.db
_DRAWINGS_OFFSET = 1_000_000


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_drawings_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DRAWINGS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _is_drawings_id(product_id: int) -> bool:
    return product_id >= _DRAWINGS_OFFSET


def _to_drawings_local(product_id: int) -> int:
    return product_id - _DRAWINGS_OFFSET


_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        source_file TEXT NOT NULL,
        source_page INTEGER,
        source_type TEXT,
        product_name TEXT,
        product_name_en TEXT,
        item_number TEXT,
        drawing_number TEXT,
        vendor_part_number TEXT,
        category TEXT,
        wll_tonnes REAL,
        proof_force_kn REAL,
        min_break_force_kn REAL,
        weight_kg REAL,
        standard TEXT,
        certification TEXT,
        surface_treatment TEXT,
        material TEXT,
        designed_for TEXT,
        date TEXT,
        revision TEXT,
        status TEXT DEFAULT 'released',
        manufacturer TEXT,
        tags TEXT,
        full_description TEXT
    );

    CREATE TABLE IF NOT EXISTS dimensions (
        id INTEGER PRIMARY KEY,
        product_id INTEGER REFERENCES products(id),
        dimension_key TEXT,
        value_mm REAL,
        description TEXT
    );

    CREATE TABLE IF NOT EXISTS components (
        id INTEGER PRIMARY KEY,
        assembly_id INTEGER REFERENCES products(id),
        part_number TEXT,
        description TEXT,
        qty INTEGER,
        length_mm REAL,
        grade TEXT,
        component_product_id INTEGER REFERENCES products(id)
    );

    CREATE TABLE IF NOT EXISTS product_standards (
        product_id INTEGER REFERENCES products(id),
        standard_code TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_wll ON products(wll_tonnes);
    CREATE INDEX IF NOT EXISTS idx_category ON products(category);
    CREATE INDEX IF NOT EXISTS idx_item_number ON products(item_number);
    CREATE INDEX IF NOT EXISTS idx_drawing_number ON products(drawing_number);
    CREATE INDEX IF NOT EXISTS idx_product_name ON products(product_name);
    CREATE INDEX IF NOT EXISTS idx_comp_assembly ON components(assembly_id);
    CREATE INDEX IF NOT EXISTS idx_comp_part ON components(part_number);
"""


def init_db():
    if USE_CATALOG_DB:
        with get_conn() as conn:
            conn.executescript(_SCHEMA)
    if DRAWINGS_DB_PATH.exists():
        with get_drawings_conn() as conn:
            conn.executescript(_SCHEMA)


def insert_product(p: dict) -> int:
    cols = [
        "source_file", "source_page", "source_type", "product_name",
        "product_name_en", "item_number", "drawing_number", "vendor_part_number",
        "category", "wll_tonnes", "proof_force_kn", "min_break_force_kn",
        "weight_kg", "standard", "certification", "surface_treatment",
        "material", "designed_for", "date", "revision", "status",
        "manufacturer", "tags", "full_description",
    ]
    row = {c: p.get(c) for c in cols}
    if isinstance(row.get("tags"), list):
        row["tags"] = json.dumps(row["tags"], ensure_ascii=False)

    placeholders = ", ".join(f":{c}" for c in cols)
    col_names = ", ".join(cols)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO products ({col_names}) VALUES ({placeholders})", row
        )
        return cur.lastrowid


def insert_dimensions(product_id: int, dimensions: dict, extra: list = None):
    rows = []
    for key, val in (dimensions or {}).items():
        if val is not None:
            rows.append((product_id, key, val, None))
    for d in (extra or []):
        if d.get("value_mm") is not None:
            rows.append((product_id, d.get("key"), d.get("value_mm"), d.get("description")))
    if rows:
        with get_conn() as conn:
            conn.executemany(
                "INSERT INTO dimensions (product_id, dimension_key, value_mm, description) VALUES (?,?,?,?)",
                rows,
            )


def insert_components(assembly_id: int, components: list):
    if not components:
        return
    rows = [
        (
            assembly_id,
            c.get("part_number"),
            c.get("description"),
            c.get("qty"),
            c.get("length_mm"),
            c.get("grade"),
        )
        for c in components
    ]
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO components (assembly_id, part_number, description, qty, length_mm, grade)"
            " VALUES (?,?,?,?,?,?)",
            rows,
        )


def insert_standards(product_id: int, standards: list):
    if not standards:
        return
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO product_standards (product_id, standard_code) VALUES (?,?)",
            [(product_id, s) for s in standards],
        )


def _build_search_sql(where: str) -> str:
    return f"""
        SELECT id, product_name, product_name_en, item_number, drawing_number,
               category, wll_tonnes, weight_kg, source_type, manufacturer, status
        FROM products {where}
    """


def search_products(
    query: str = None,
    category: str = None,
    min_wll: float = None,
    max_wll: float = None,
    limit: int = 20,
) -> list[dict]:
    conditions, params = [], []

    if query:
        conditions.append(
            "(product_name LIKE ? OR product_name_en LIKE ? OR item_number LIKE ?"
            " OR drawing_number LIKE ? OR full_description LIKE ? OR tags LIKE ?)"
        )
        q = f"%{query}%"
        params.extend([q, q, q, q, q, q])
    if category:
        conditions.append("category = ?")
        params.append(category)
    if min_wll is not None:
        conditions.append("wll_tonnes >= ?")
        params.append(min_wll)
    if max_wll is not None:
        conditions.append("wll_tonnes <= ?")
        params.append(max_wll)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = _build_search_sql(where)

    results = []
    if USE_CATALOG_DB:
        with get_conn() as conn:
            for r in conn.execute(sql, params).fetchall():
                d = dict(r)
                d["source_db"] = "catalog"
                results.append(d)

    if DRAWINGS_DB_PATH.exists():
        with get_drawings_conn() as conn:
            for r in conn.execute(sql, params).fetchall():
                d = dict(r)
                d["id"] = d["id"] + _DRAWINGS_OFFSET
                d["source_db"] = "drawings"
                results.append(d)

    results.sort(key=lambda x: (x.get("wll_tonnes") or 0), reverse=True)
    return results[:limit]


def _fetch_product_row(conn, product_id=None, item_number=None, drawing_number=None):
    if product_id is not None:
        return conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if item_number:
        return conn.execute("SELECT * FROM products WHERE item_number=?", (item_number,)).fetchone()
    if drawing_number:
        return conn.execute("SELECT * FROM products WHERE drawing_number=?", (drawing_number,)).fetchone()
    return None


def _fetch_related(conn, local_id: int) -> dict:
    dimensions = [
        dict(r)
        for r in conn.execute(
            "SELECT dimension_key, value_mm, description FROM dimensions WHERE product_id=?",
            (local_id,),
        ).fetchall()
    ]
    components = [
        dict(r)
        for r in conn.execute(
            "SELECT part_number, description, qty, length_mm, grade"
            " FROM components WHERE assembly_id=?",
            (local_id,),
        ).fetchall()
    ]
    standards = [
        r["standard_code"]
        for r in conn.execute(
            "SELECT standard_code FROM product_standards WHERE product_id=?", (local_id,)
        ).fetchall()
    ]
    return {"dimensions": dimensions, "components": components, "standards": standards}


def get_product_details(
    product_id: int = None,
    item_number: str = None,
    drawing_number: str = None,
) -> dict | None:
    # Route by ID if provided
    if product_id is not None and not _is_drawings_id(product_id) and not USE_CATALOG_DB:
        return None
    if product_id is not None:
        if _is_drawings_id(product_id):
            local_id = _to_drawings_local(product_id)
            if not DRAWINGS_DB_PATH.exists():
                return None
            with get_drawings_conn() as conn:
                row = conn.execute("SELECT * FROM products WHERE id=?", (local_id,)).fetchone()
                if not row:
                    return None
                product = dict(row)
                product["id"] = product_id
                product["source_db"] = "drawings"
                product.update(_fetch_related(conn, local_id))
        else:
            if not USE_CATALOG_DB:
                return None
            with get_conn() as conn:
                row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
                if not row:
                    return None
                product = dict(row)
                product["source_db"] = "catalog"
                product.update(_fetch_related(conn, product_id))
    else:
        # Search by item_number or drawing_number — try catalog first, then drawings
        product = None
        if USE_CATALOG_DB:
            with get_conn() as conn:
                row = _fetch_product_row(conn, item_number=item_number, drawing_number=drawing_number)
                if row:
                    product = dict(row)
                    local_id = product["id"]
                    product["source_db"] = "catalog"
                    product.update(_fetch_related(conn, local_id))

        if product is None and DRAWINGS_DB_PATH.exists():
            with get_drawings_conn() as conn:
                row = _fetch_product_row(conn, item_number=item_number, drawing_number=drawing_number)
                if row:
                    product = dict(row)
                    local_id = product["id"]
                    product["id"] = local_id + _DRAWINGS_OFFSET
                    product["source_db"] = "drawings"
                    product.update(_fetch_related(conn, local_id))

    if product is None:
        return None

    if isinstance(product.get("tags"), str):
        try:
            product["tags"] = json.loads(product["tags"])
        except Exception:
            pass

    return product


def find_by_specification(
    wll_tonnes: float = None,
    category: str = None,
    material: str = None,
    standard: str = None,
    manufacturer: str = None,
) -> list[dict]:
    conditions, params = [], []

    if wll_tonnes is not None:
        conditions.append("wll_tonnes >= ?")
        params.append(wll_tonnes)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if material:
        conditions.append("material LIKE ?")
        params.append(f"%{material}%")
    if standard:
        conditions.append("(standard LIKE ? OR id IN (SELECT product_id FROM product_standards WHERE standard_code LIKE ?))")
        params.extend([f"%{standard}%", f"%{standard}%"])
    if manufacturer:
        conditions.append("manufacturer LIKE ?")
        params.append(f"%{manufacturer}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT id, product_name, product_name_en, item_number, drawing_number,
               category, wll_tonnes, proof_force_kn, weight_kg, source_type, manufacturer
        FROM products {where}
    """

    results = []
    if USE_CATALOG_DB:
        with get_conn() as conn:
            for r in conn.execute(sql, params).fetchall():
                d = dict(r)
                d["source_db"] = "catalog"
                results.append(d)

    if DRAWINGS_DB_PATH.exists():
        with get_drawings_conn() as conn:
            for r in conn.execute(sql, params).fetchall():
                d = dict(r)
                d["id"] = d["id"] + _DRAWINGS_OFFSET
                d["source_db"] = "drawings"
                results.append(d)

    results.sort(key=lambda x: (x.get("wll_tonnes") or 0))
    return results[:20]


def list_categories() -> list[dict]:
    category_counts: dict[str, int] = {}

    if USE_CATALOG_DB:
        with get_conn() as conn:
            for r in conn.execute(
                "SELECT category, COUNT(*) as count FROM products"
                " WHERE category IS NOT NULL GROUP BY category"
            ).fetchall():
                category_counts[r["category"]] = category_counts.get(r["category"], 0) + r["count"]

    if DRAWINGS_DB_PATH.exists():
        with get_drawings_conn() as conn:
            for r in conn.execute(
                "SELECT category, COUNT(*) as count FROM products"
                " WHERE category IS NOT NULL GROUP BY category"
            ).fetchall():
                category_counts[r["category"]] = category_counts.get(r["category"], 0) + r["count"]

    return sorted(
        [{"category": cat, "count": cnt} for cat, cnt in category_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


def init_embeddings_table():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS embeddings (
                product_id INTEGER PRIMARY KEY REFERENCES products(id),
                embedding BLOB NOT NULL
            );
        """)


def upsert_embedding(product_id: int, vector: list[float]):
    import struct
    blob = struct.pack(f"{len(vector)}f", *vector)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (product_id, embedding) VALUES (?, ?)",
            (product_id, blob),
        )


def get_all_embeddings() -> list[tuple[int, list[float]]]:
    import struct
    with get_conn() as conn:
        rows = conn.execute("SELECT product_id, embedding FROM embeddings").fetchall()
    result = []
    for pid, blob in rows:
        n = len(blob) // 4
        vec = list(struct.unpack(f"{n}f", blob))
        result.append((pid, vec))
    return result


def semantic_search(query_vec: list[float], top_k: int = 10) -> list[dict]:
    import math

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0

    rows = get_all_embeddings()
    if not rows:
        return []

    scored = sorted(
        [(pid, cosine(query_vec, vec)) for pid, vec in rows],
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]

    with get_conn() as conn:
        results = []
        for pid, score in scored:
            row = conn.execute(
                "SELECT id, product_name, product_name_en, item_number, drawing_number,"
                " category, wll_tonnes, weight_kg, source_type, manufacturer, status"
                " FROM products WHERE id=?",
                (pid,),
            ).fetchone()
            if row:
                d = dict(row)
                d["similarity_score"] = round(score, 4)
                d["source_db"] = "catalog"
                results.append(d)
    return results


def get_assembly_components(
    product_id: int = None, drawing_number: str = None
) -> list[dict]:
    # Resolve drawing_number to a product_id
    if drawing_number and product_id is None:
        if USE_CATALOG_DB:
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT id FROM products WHERE drawing_number=?", (drawing_number,)
                ).fetchone()
                if row:
                    product_id = row["id"]

        if product_id is None and DRAWINGS_DB_PATH.exists():
            with get_drawings_conn() as conn:
                row = conn.execute(
                    "SELECT id FROM products WHERE drawing_number=?", (drawing_number,)
                ).fetchone()
                if row:
                    product_id = row["id"] + _DRAWINGS_OFFSET

    if product_id is None:
        return []

    if _is_drawings_id(product_id):
        local_id = _to_drawings_local(product_id)
        if not DRAWINGS_DB_PATH.exists():
            return []
        with get_drawings_conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT part_number, description, qty, length_mm, grade"
                    " FROM components WHERE assembly_id=?",
                    (local_id,),
                ).fetchall()
            ]
    else:
        with get_conn() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT part_number, description, qty, length_mm, grade"
                    " FROM components WHERE assembly_id=?",
                    (product_id,),
                ).fetchall()
            ]
