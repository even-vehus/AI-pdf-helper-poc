import json
import sqlite3

from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
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
        """)


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
    sql = f"""
        SELECT id, product_name, product_name_en, item_number, drawing_number,
               category, wll_tonnes, weight_kg, source_type, manufacturer, status
        FROM products {where}
        ORDER BY wll_tonnes DESC
        LIMIT ?
    """
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_product_details(
    product_id: int = None,
    item_number: str = None,
    drawing_number: str = None,
) -> dict | None:
    with get_conn() as conn:
        if product_id:
            row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        elif item_number:
            row = conn.execute(
                "SELECT * FROM products WHERE item_number=?", (item_number,)
            ).fetchone()
        elif drawing_number:
            row = conn.execute(
                "SELECT * FROM products WHERE drawing_number=?", (drawing_number,)
            ).fetchone()
        else:
            return None

        if not row:
            return None

        product = dict(row)
        pid = product["id"]

        product["dimensions"] = [
            dict(r)
            for r in conn.execute(
                "SELECT dimension_key, value_mm, description FROM dimensions WHERE product_id=?",
                (pid,),
            ).fetchall()
        ]
        product["components"] = [
            dict(r)
            for r in conn.execute(
                "SELECT part_number, description, qty, length_mm, grade"
                " FROM components WHERE assembly_id=?",
                (pid,),
            ).fetchall()
        ]
        product["standards"] = [
            r["standard_code"]
            for r in conn.execute(
                "SELECT standard_code FROM product_standards WHERE product_id=?", (pid,)
            ).fetchall()
        ]

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
        ORDER BY wll_tonnes ASC
        LIMIT 20
    """
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_categories() -> list[dict]:
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT category, COUNT(*) as count FROM products"
                " WHERE category IS NOT NULL GROUP BY category ORDER BY count DESC"
            ).fetchall()
        ]


def get_assembly_components(
    product_id: int = None, drawing_number: str = None
) -> list[dict]:
    with get_conn() as conn:
        if drawing_number and not product_id:
            row = conn.execute(
                "SELECT id FROM products WHERE drawing_number=?", (drawing_number,)
            ).fetchone()
            if row:
                product_id = row["id"]
        if not product_id:
            return []
        return [
            dict(r)
            for r in conn.execute(
                "SELECT part_number, description, qty, length_mm, grade"
                " FROM components WHERE assembly_id=?",
                (product_id,),
            ).fetchall()
        ]
