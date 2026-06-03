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

            CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
                product_name,
                product_name_en,
                item_number,
                drawing_number,
                full_description,
                tags,
                content=products,
                content_rowid=id,
                tokenize='unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS products_fts_insert
                AFTER INSERT ON products BEGIN
                    INSERT INTO products_fts(rowid, product_name, product_name_en,
                        item_number, drawing_number, full_description, tags)
                    VALUES (new.id, new.product_name, new.product_name_en,
                        new.item_number, new.drawing_number, new.full_description, new.tags);
                END;

            CREATE TRIGGER IF NOT EXISTS products_fts_update
                AFTER UPDATE ON products BEGIN
                    INSERT INTO products_fts(products_fts, rowid, product_name, product_name_en,
                        item_number, drawing_number, full_description, tags)
                    VALUES ('delete', old.id, old.product_name, old.product_name_en,
                        old.item_number, old.drawing_number, old.full_description, old.tags);
                    INSERT INTO products_fts(rowid, product_name, product_name_en,
                        item_number, drawing_number, full_description, tags)
                    VALUES (new.id, new.product_name, new.product_name_en,
                        new.item_number, new.drawing_number, new.full_description, new.tags);
                END;

            CREATE TRIGGER IF NOT EXISTS products_fts_delete
                AFTER DELETE ON products BEGIN
                    INSERT INTO products_fts(products_fts, rowid, product_name, product_name_en,
                        item_number, drawing_number, full_description, tags)
                    VALUES ('delete', old.id, old.product_name, old.product_name_en,
                        old.item_number, old.drawing_number, old.full_description, old.tags);
                END;
        """)


def init_orders_table():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id          INTEGER PRIMARY KEY,
                item_number TEXT NOT NULL,
                order_date  TEXT NOT NULL,
                order_type  TEXT NOT NULL,
                customer    TEXT,
                qty         INTEGER,
                unit_price  REAL,
                order_total REAL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_item ON orders(item_number);
            CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
            CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer);
            CREATE INDEX IF NOT EXISTS idx_orders_type ON orders(order_type);
        """)


def insert_order(row: dict):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO orders (item_number, order_date, order_type, customer, qty, unit_price, order_total)"
            " VALUES (:item_number, :order_date, :order_type, :customer, :qty, :unit_price, :order_total)",
            row,
        )


def clear_orders():
    with get_conn() as conn:
        conn.execute("DELETE FROM orders")


def get_sales_summary(item_number: str, include_quotes: bool = False) -> dict:
    types = ("'Quote'", "'Order'") if include_quotes else ("'Order'",)
    type_filter = f"AND order_type IN ({', '.join(types)})"
    with get_conn() as conn:
        row = conn.execute(
            f"""SELECT
                COUNT(*) as transaction_count,
                COALESCE(SUM(qty), 0) as total_units,
                COALESCE(SUM(order_total), 0) as total_revenue,
                COALESCE(AVG(unit_price), 0) as avg_unit_price,
                MIN(order_date) as first_order,
                MAX(order_date) as last_order
            FROM orders
            WHERE item_number = ? {type_filter}""",
            (item_number,),
        ).fetchone()
        customers = conn.execute(
            f"SELECT COUNT(DISTINCT customer) as n FROM orders WHERE item_number = ? {type_filter}",
            (item_number,),
        ).fetchone()
    result = dict(row)
    result["unique_customers"] = customers["n"]
    result["item_number"] = item_number
    result["includes_quotes"] = include_quotes
    return result


def get_customer_orders(
    customer: str,
    item_number: str = None,
    from_date: str = None,
    to_date: str = None,
    include_quotes: bool = False,
    limit: int = 50,
) -> list[dict]:
    types = ("'Quote'", "'Order'") if include_quotes else ("'Order'",)
    conditions = [f"customer LIKE ?", f"order_type IN ({', '.join(types)})"]
    params: list = [f"%{customer}%"]
    if item_number:
        conditions.append("item_number = ?")
        params.append(item_number)
    if from_date:
        conditions.append("order_date >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("order_date <= ?")
        params.append(to_date)
    where = "WHERE " + " AND ".join(conditions)
    params.append(limit)
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT item_number, order_date, order_type, customer, qty, unit_price, order_total"
                f" FROM orders {where} ORDER BY order_date DESC LIMIT ?",
                params,
            ).fetchall()
        ]


def get_sales_trend(item_number: str, include_quotes: bool = False) -> list[dict]:
    types = ("'Quote'", "'Order'") if include_quotes else ("'Order'",)
    type_filter = f"AND order_type IN ({', '.join(types)})"
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"""SELECT
                    SUBSTR(order_date, 1, 4) as year,
                    SUM(qty) as total_units,
                    SUM(order_total) as total_revenue,
                    COUNT(*) as transaction_count,
                    ROUND(AVG(unit_price), 0) as avg_unit_price
                FROM orders
                WHERE item_number = ? {type_filter}
                GROUP BY year
                ORDER BY year""",
                (item_number,),
            ).fetchall()
        ]


def search_order_history(
    from_date: str = None,
    to_date: str = None,
    customer: str = None,
    order_type: str = None,
    limit: int = 20,
) -> list[dict]:
    conditions, params = [], []
    if from_date:
        conditions.append("order_date >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("order_date <= ?")
        params.append(to_date)
    if customer:
        conditions.append("customer LIKE ?")
        params.append(f"%{customer}%")
    if order_type:
        conditions.append("order_type = ?")
        params.append(order_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"""SELECT
                    item_number,
                    SUM(qty) as total_units,
                    SUM(order_total) as total_revenue,
                    COUNT(*) as transaction_count,
                    COUNT(DISTINCT customer) as unique_customers
                FROM orders {where}
                GROUP BY item_number
                ORDER BY total_units DESC
                LIMIT ?""",
                params,
            ).fetchall()
        ]


def rebuild_fts_index():
    """Populate FTS index from existing products — run once after init_db on an existing DB."""
    with get_conn() as conn:
        conn.execute("INSERT INTO products_fts(products_fts) VALUES ('rebuild')")


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

    if category:
        conditions.append("p.category = ?")
        params.append(category)
    if min_wll is not None:
        conditions.append("p.wll_tonnes >= ?")
        params.append(min_wll)
    if max_wll is not None:
        conditions.append("p.wll_tonnes <= ?")
        params.append(max_wll)

    with get_conn() as conn:
        if query:
            # Terms with hyphens are phrase-searched exactly; plain terms use prefix match.
            def _fts_term(t: str) -> str:
                return f'"{t}"' if "-" in t else f'"{t}"*'
            terms = [_fts_term(t) for t in query.split()]
            fts_where = ("AND " + " AND ".join(conditions)) if conditions else ""
            fts_sql = f"""
                SELECT p.id, p.product_name, p.product_name_en, p.item_number, p.drawing_number,
                       p.category, p.wll_tonnes, p.weight_kg, p.source_type, p.manufacturer, p.status
                FROM products_fts
                JOIN products p ON p.id = products_fts.rowid
                WHERE products_fts MATCH ? {fts_where}
                ORDER BY rank, p.wll_tonnes DESC
                LIMIT ?
            """
            # Prefer AND (all terms must match) — fall back to OR if no results.
            and_params = [" AND ".join(terms)] + params + [limit]
            rows = conn.execute(fts_sql, and_params).fetchall()
            if not rows and len(terms) > 1:
                or_params = [" OR ".join(terms)] + params + [limit]
                rows = conn.execute(fts_sql, or_params).fetchall()
            return [dict(r) for r in rows]
        else:
            plain_where = ("WHERE " + " AND ".join(c.replace("p.", "") for c in conditions)) if conditions else ""
            sql = f"""
                SELECT id, product_name, product_name_en, item_number, drawing_number,
                       category, wll_tonnes, weight_kg, source_type, manufacturer, status
                FROM products {plain_where}
                ORDER BY wll_tonnes DESC
                LIMIT ?
            """
            return [dict(r) for r in conn.execute(sql, params + [limit]).fetchall()]


def get_product_details(
    product_id: int = None,
    item_number: str = None,
    drawing_number: str = None,
) -> dict | None:
    with get_conn() as conn:
        if product_id is not None:
            row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        elif item_number:
            row = conn.execute("SELECT * FROM products WHERE item_number=?", (item_number,)).fetchone()
        elif drawing_number:
            row = conn.execute("SELECT * FROM products WHERE drawing_number=?", (drawing_number,)).fetchone()
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
    import numpy as np

    rows = get_all_embeddings()
    if not rows:
        return []

    pids = [pid for pid, _ in rows]
    matrix = np.array([vec for _, vec in rows], dtype=np.float32)
    q = np.array(query_vec, dtype=np.float32)

    norms = np.linalg.norm(matrix, axis=1)
    q_norm = np.linalg.norm(q)
    scores = (matrix @ q) / (norms * q_norm + 1e-10)

    top_indices = np.argpartition(scores, -min(top_k, len(scores)))[-top_k:]
    top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

    with get_conn() as conn:
        results = []
        for i in top_indices:
            row = conn.execute(
                "SELECT id, product_name, product_name_en, item_number, drawing_number,"
                " category, wll_tonnes, weight_kg, source_type, manufacturer, status"
                " FROM products WHERE id=?",
                (pids[i],),
            ).fetchone()
            if row:
                d = dict(row)
                d["similarity_score"] = round(float(scores[i]), 4)
                results.append(d)
    return results


def search_by_drawing_prefix(prefix: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, product_name, item_number, drawing_number, category,"
                " wll_tonnes, weight_kg, manufacturer, status"
                " FROM products WHERE drawing_number LIKE ? ORDER BY drawing_number LIMIT ?",
                (f"{prefix}%", limit),
            ).fetchall()
        ]


def get_similar_products(product_id: int, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        base = conn.execute(
            "SELECT category, wll_tonnes FROM products WHERE id=?", (product_id,)
        ).fetchone()
        if not base:
            return []
        category, wll = base["category"], base["wll_tonnes"]
        conditions = ["id != ?"]
        where_params: list = [product_id]
        if category:
            conditions.append("category = ?")
            where_params.append(category)
        if wll is not None:
            conditions.append("wll_tonnes BETWEEN ? AND ?")
            where_params.extend([wll * 0.5, wll * 2.0])
        where = "WHERE " + " AND ".join(conditions)
        order_param = wll if wll is not None else 0
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT id, product_name, item_number, drawing_number, category,"
                f" wll_tonnes, weight_kg, manufacturer, status"
                f" FROM products {where} ORDER BY ABS(wll_tonnes - ?) LIMIT ?",
                where_params + [order_param, limit],
            ).fetchall()
        ]


def search_by_weight_range(
    min_kg: float = None, max_kg: float = None, limit: int = 20
) -> list[dict]:
    conditions, params = [], []
    if min_kg is not None:
        conditions.append("weight_kg >= ?")
        params.append(min_kg)
    if max_kg is not None:
        conditions.append("weight_kg <= ?")
        params.append(max_kg)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT id, product_name, item_number, drawing_number, category,"
                f" wll_tonnes, weight_kg, manufacturer, status"
                f" FROM products {where} ORDER BY weight_kg ASC LIMIT ?",
                params,
            ).fetchall()
        ]


def search_by_standard(standard: str, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT DISTINCT p.id, p.product_name, p.item_number, p.drawing_number,"
                " p.category, p.wll_tonnes, p.weight_kg, p.manufacturer, p.status"
                " FROM products p"
                " LEFT JOIN product_standards ps ON ps.product_id = p.id"
                " WHERE p.standard LIKE ? OR ps.standard_code LIKE ?"
                " ORDER BY p.category, p.wll_tonnes LIMIT ?",
                (f"%{standard}%", f"%{standard}%", limit),
            ).fetchall()
        ]


def get_products_in_assembly(
    part_drawing_number: str = None, part_item_number: str = None, limit: int = 20
) -> list[dict]:
    with get_conn() as conn:
        if part_drawing_number:
            part_row = conn.execute(
                "SELECT id FROM products WHERE drawing_number=?", (part_drawing_number,)
            ).fetchone()
            part_id = part_row["id"] if part_row else None
            assemblies = conn.execute(
                "SELECT DISTINCT assembly_id FROM components"
                " WHERE component_product_id=? OR part_number=?",
                (part_id, part_drawing_number),
            ).fetchall() if part_id else conn.execute(
                "SELECT DISTINCT assembly_id FROM components WHERE part_number=?",
                (part_drawing_number,),
            ).fetchall()
        elif part_item_number:
            assemblies = conn.execute(
                "SELECT DISTINCT assembly_id FROM components WHERE part_number=?",
                (part_item_number,),
            ).fetchall()
        else:
            return []

        assembly_ids = [r["assembly_id"] for r in assemblies]
        if not assembly_ids:
            return []

        placeholders = ",".join("?" * len(assembly_ids))
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT id, product_name, item_number, drawing_number, category,"
                f" wll_tonnes, weight_kg, manufacturer, status"
                f" FROM products WHERE id IN ({placeholders}) LIMIT ?",
                assembly_ids + [limit],
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
