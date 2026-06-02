"""
Nøsted & product search MCP server.

Run:  py server.py
Claude Desktop config:
  {
    "mcpServers": {
      "nosted-product-search": {
        "command": "py",
        "args": ["C:/path/to/Nosted_poc/server.py"]
      }
    }
  }
"""

from mcp.server.fastmcp import FastMCP

import db
from config import PDF_DIR

mcp = FastMCP("nosted-product-search")


@mcp.tool()
def search_products(
    query: str,
    category: str = None,
    min_wll: float = None,
    max_wll: float = None,
) -> list:
    """Search Nøsted & products by free text and optional filters.

    Args:
        query: Text to search across name, item number, drawing number, description and tags.
               Example: "krok storsekk", "634-40863", "T63458251"
        category: Limit to one category. Options: Kjetting, Koplingselementer, Sjakler,
                  Løkker, Kroker, Løftepunkt, Kjettingredskaper, Løfteåk, Surringsutstyr,
                  Kabelarer, Mykløft, Ståltau, ROV-produkter, Havbruk, Grade 100, Rustfritt
        min_wll: Minimum WLL in tonnes (e.g. 3.5)
        max_wll: Maximum WLL in tonnes

    Returns up to 20 matching products with id, name, item_number, drawing_number,
    category, wll_tonnes, weight_kg, source_type, manufacturer, status.
    """
    db.init_db()
    return db.search_products(query=query, category=category, min_wll=min_wll, max_wll=max_wll)


@mcp.tool()
def get_product_details(
    product_id: int = None,
    item_number: str = None,
    drawing_number: str = None,
) -> dict:
    """Get complete information about one product.

    Provide exactly one identifier: product_id (database id), item_number (e.g. T63458251),
    or drawing_number (e.g. 634-58251).

    Returns all fields including dimensions, bill-of-materials components, and standards.
    """
    db.init_db()
    result = db.get_product_details(
        product_id=product_id,
        item_number=item_number,
        drawing_number=drawing_number,
    )
    return result if result is not None else {"error": "Product not found"}


@mcp.tool()
def find_by_specification(
    wll_tonnes: float = None,
    category: str = None,
    material: str = None,
    standard: str = None,
    manufacturer: str = None,
) -> list:
    """Find products matching specific technical requirements.

    Args:
        wll_tonnes: Minimum required WLL in tonnes (e.g. 3.5 for a 3.5-tonne requirement)
        category: Product category (e.g. "Kroker", "Løfteåk", "Sjakler")
        material: Material filter (e.g. "SAE 6620", "rustfritt", "Grade 8")
        standard: Standard filter (e.g. "NS-EN 818", "offshore")
        manufacturer: Manufacturer name filter (e.g. "FRAM", "Tigrip")

    Returns products sorted by WLL ascending — lowest sufficient capacity first.
    """
    db.init_db()
    return db.find_by_specification(
        wll_tonnes=wll_tonnes,
        category=category,
        material=material,
        standard=standard,
        manufacturer=manufacturer,
    )


@mcp.tool()
def list_categories() -> list:
    """List all product categories present in the database with product counts.

    Use this to understand what types of products are available before searching.
    """
    db.init_db()
    return db.list_categories()


@mcp.tool()
def get_drawing(
    product_id: int = None,
    drawing_number: str = None,
) -> dict:
    """Get the PDF file path and page number for a product's technical drawing.

    Args:
        product_id: Database id of the product
        drawing_number: Drawing number (e.g. "634-58251")

    Returns file_path, source_file, source_page, product_name, drawing_number,
    and exists (whether the PDF file is present on disk).
    """
    db.init_db()
    product = db.get_product_details(product_id=product_id, drawing_number=drawing_number)
    if not product:
        return {"error": "Product not found"}

    pdf_path = PDF_DIR / product["source_file"]
    return {
        "file_path": str(pdf_path),
        "source_file": product["source_file"],
        "source_page": product.get("source_page"),
        "product_name": product.get("product_name"),
        "drawing_number": product.get("drawing_number"),
        "exists": pdf_path.exists(),
    }


@mcp.tool()
def get_assembly_components(
    product_id: int = None,
    drawing_number: str = None,
) -> list:
    """Get the bill of materials (stykkliste) for an assembly product.

    Args:
        product_id: Database id of the assembly
        drawing_number: Drawing number of the assembly (e.g. "634-40863")

    Returns a list of components, each with part_number, description, qty,
    length_mm (for chain/wire), and grade.
    """
    db.init_db()
    return db.get_assembly_components(product_id=product_id, drawing_number=drawing_number)


_embedding_model = None

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        except ImportError:
            return None
    return _embedding_model


@mcp.tool()
def semantic_search(query: str, top_k: int = 10) -> list:
    """Find products by meaning rather than exact keywords (semantic / vector search).

    Use this when keyword search returns nothing, or when the customer describes
    what they want without using exact product terms.

    Examples:
      "noe å løfte tønner med"     → finds fatbeslag / fatstropper
      "krok for løft i trange rom" → finds lavtbyggende kryssåk
      "festepunkt på dekk"         → finds løftepunkt / øyebolter

    Args:
        query: Natural language description of what the customer needs (Norwegian or English)
        top_k: Number of results to return (default 10)

    Returns products ranked by semantic similarity with a similarity_score (0–1).
    """
    db.init_db()
    model = _get_model()
    if model is None:
        return [{"error": "sentence-transformers not installed. Run: py -m pip install sentence-transformers"}]
    vec = model.encode(query).tolist()
    return db.semantic_search(vec, top_k=top_k)


if __name__ == "__main__":
    mcp.run()
