"""
Import Business Central order data from CSV into the orders table.

Usage:
    py import_orders.py                        # import from Nosted_data/BC_ordredata.csv
    py import_orders.py path/to/other.csv      # import a specific file
    py import_orders.py --reset                # clear existing orders before importing

The orders table is cleared and reloaded on each run (without --reset the products
table is untouched — only orders are replaced).
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

import db
from config import PDF_DIR

DEFAULT_CSV = PDF_DIR / "BC_ordredata.csv"


def _parse_date(s: str) -> str:
    """DD.MM.YYYY → YYYY-MM-DD (ISO). Returns original string if unparseable."""
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return s.strip()


def _parse_number(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(s.strip().replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def import_csv(csv_path: Path) -> int:
    imported = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for raw in reader:
            row = {
                "item_number": (raw.get("Varenummer") or "").strip(),
                "order_date":  _parse_date(raw.get("Dato") or ""),
                "order_type":  (raw.get("Ordretype") or "").strip(),
                "customer":    (raw.get("Kunde") or "").strip() or None,
                "qty":         int(_parse_number(raw.get("Qty") or "0") or 0),
                "unit_price":  _parse_number(raw.get("Pris")),
                "order_total": _parse_number(raw.get("Sum ordre")),
            }
            if not row["item_number"] or not row["order_date"]:
                continue
            db.insert_order(row)
            imported += 1
    return imported


def main():
    args = sys.argv[1:]
    reset = "--reset" in args
    args = [a for a in args if a != "--reset"]

    csv_path = Path(args[0]) if args else DEFAULT_CSV
    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        sys.exit(1)

    db.init_db()
    db.init_orders_table()

    if reset:
        db.clear_orders()
        print("Existing orders cleared.")

    print(f"Importing: {csv_path.name}")
    db.clear_orders()
    n = import_csv(csv_path)
    print(f"Done — {n} order rows imported.")


if __name__ == "__main__":
    main()
