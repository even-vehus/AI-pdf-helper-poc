"""
Generate and store sentence embeddings for all products in the DB.

Run after any data import:
    py embed.py

Uses paraphrase-multilingual-MiniLM-L12-v2 — a 120 MB model that runs
fully on-machine and handles Norwegian + English natively.
"""

from sentence_transformers import SentenceTransformer

import db

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def build_text(p: dict) -> str:
    parts = []
    for field in ("product_name", "product_name_en", "item_number", "drawing_number",
                  "category", "designed_for", "material", "standard", "manufacturer",
                  "full_description"):
        v = p.get(field)
        if v:
            parts.append(str(v))
    if p.get("wll_tonnes"):
        parts.append(f"WLL {p['wll_tonnes']} tonn")
    if p.get("tags"):
        import json
        tags = p["tags"]
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                pass
        if isinstance(tags, list):
            parts.extend(tags)
    return " ".join(parts)


def main():
    db.init_db()
    db.init_embeddings_table()

    with db.get_conn() as conn:
        rows = conn.execute("SELECT id FROM products").fetchall()
    product_ids = [r["id"] for r in rows]

    if not product_ids:
        print("No products in DB.")
        return

    print(f"Loading model '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)
    print(f"Generating embeddings for {len(product_ids)} products...")

    batch_size = 64
    embedded = 0
    for start in range(0, len(product_ids), batch_size):
        batch_ids = product_ids[start : start + batch_size]
        with db.get_conn() as conn:
            products = [
                dict(conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone())
                for pid in batch_ids
            ]
        texts = [build_text(p) for p in products]
        vectors = model.encode(texts, show_progress_bar=False)
        for pid, vec in zip(batch_ids, vectors):
            db.upsert_embedding(pid, vec.tolist())
        embedded += len(batch_ids)
        print(f"  {embedded}/{len(product_ids)}", end="\r", flush=True)

    print(f"\nDone — {embedded} embeddings stored.")


if __name__ == "__main__":
    main()
