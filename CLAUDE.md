# Nosted POC — Claude Code Context

## What this is
A local MCP server that lets Claude Desktop search a SQLite database of Nøsted & lifting-equipment products extracted from PDF technical drawings and product catalogs.

**Goal**: Demonstrate AI-powered product search as a POC for KSS/Salg teams at Nøsted. Not production — no auth, no web UI, single-user local setup.

## Architecture
```
Claude Desktop  →  server.py (FastMCP)  →  db.py (SQLite)  →  database/superdatabase.db
```
Data flows in via:
- `extract.py` — Claude Vision API on technical drawing PDFs (single-product and assembly drawings)
- `extract_catalog.py` — pdfplumber table parsing on tabular catalog PDFs (cheaper, more accurate for dense tables)
- `embed.py` — sentence-transformers for semantic search embeddings

## Running things

```bash
# One-time: extract all PDFs from Nosted_data/ into the DB
py extract.py

# Recreate DB from scratch
py extract.py --reset

# Extract a single file
py extract.py Nosted_data/somefile.pdf

# Generate/refresh semantic embeddings (run after any data import)
py embed.py

# Import Business Central order data from Nosted_data/BC_ordredata.csv
py import_orders.py

# Import from a different CSV file
py import_orders.py path/to/file.csv

# The MCP server is started automatically by Claude Desktop
py server.py
```

## Key files
| File | Purpose |
|---|---|
| `server.py` | MCP tool definitions — what Claude Desktop sees |
| `db.py` | All DB logic: schema, insert, FTS5 search, semantic search |
| `config.py` | Paths, model name, API key |
| `extract.py` | Drawing PDFs → Claude Vision → DB |
| `extract_catalog.py` | Catalog PDFs → pdfplumber → DB |
| `embed.py` | Generate sentence embeddings for all products |
| `import_orders.py` | Import BC_ordredata.csv into the orders table |
| `prompts/extraction.txt` | Prompt controlling Claude Vision extraction |
| `database/superdatabase.db` | SQLite DB — not in git, generated locally |
| `Nosted_data/` | Source PDFs — not in git |

## Data sources
- **Drawings** (`source_type=fram_drawing|assembly|third_party`): extracted via Claude Vision. Have `drawing_number`, dimensions, BOM components.
- **Catalog rows** (`source_type=catalog_row`): extracted via pdfplumber. Have `item_number`, WLL, weight. `drawing_number` is always null — this is a known gap.

## Database schema
- `products`: all product metadata
- `dimensions`: key/value dimension pairs per product
- `components`: BOM lines (assembly → parts)
- `product_standards`: normalized standards per product (one row per standard)
- `embeddings`: binary float32 vectors for semantic search
- `orders`: Business Central order/quote lines — keyed on `item_number` (joins to `products`)

FTS5 virtual table `products_fts` covers: product_name, product_name_en, item_number, drawing_number, full_description, tags.

## Search strategy
`search_products` uses FTS5 AND (all terms required) first, falls back to OR if no results. Semantic search via cosine similarity over sentence-transformer embeddings.

## Known limitations
- `get_products_in_assembly` relies on `component_product_id` being populated — this often isn't set, so falls back to `part_number` string matching.
- Semantic search loads all embeddings into memory on each call — fine for POC scale, will need sqlite-vec or similar at 8,500+ products.
- Catalog rows have no `drawing_number`, so `get_drawing()` won't work for them.
- Only PDFs loaded into `Nosted_data/` are searchable — not the full ~8,500 drawing catalogue.

## Development notes
- After changing what gets extracted, run `py extract.py --reset` then `py embed.py`.
- After changing embedding `build_text()`, run `py embed.py` to refresh vectors.
- Claude Desktop must be restarted to pick up server.py changes.
- No test suite yet — validate manually via Claude Desktop.
