# Nøsted & AI-produktsøk — POC-status

## Hva er bygget

En lokal MCP-server som lar Claude søke i en strukturert SQLite-database over Nøsted &-produkter ekstrahert fra PDF-er.

### Arkitektur

```
Bruker (Claude Desktop)
        │  MCP tool calls
        ▼
server.py  (FastMCP)
        │
        ▼
db.py  (SQLite via sqlite3)
        │
        ▼
New_data/superdatabase.db
```

### Dataflyten

```
PDF-filer (Nosted_data/)
        │
        ▼
extract.py + extract_catalog.py  →  Claude Vision API (claude-sonnet-4-6)
        │
        ▼
db.py insert-funksjoner  →  superdatabase.db
        │
        ▼
embed.py  →  sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
        │
        ▼
embeddings-tabell i superdatabase.db
```

---

## MCP-verktøy (server.py)

| Verktøy | Beskrivelse |
|---|---|
| `search_products` | Fritekst + kategori/WLL-filter, maks 20 treff |
| `get_product_details` | Komplett produktinfo inkl. dimensjoner, stykkliste, standarder |
| `find_by_specification` | Søk på WLL, kategori, material, standard, produsent |
| `list_categories` | Alle kategorier med antall produkter |
| `get_drawing` | PDF-filsti og sidetall for et produkt |
| `get_assembly_components` | Stykkliste (BOM) for en sammenstilling |
| `search_by_drawing_prefix` | Finn alle produkter i en tegningsserie (f.eks. "634-") |
| `get_similar_products` | Alternativer i samme kategori og WLL-område |
| `search_by_weight_range` | Filtrer på produktvekt i kg |
| `semantic_search` | Vektorsøk — finner produkter basert på mening, ikke nøkkelord |
| `search_by_standard` | Finn produkter sertifisert til en gitt standard (f.eks. "NS-EN 818") |
| `get_products_in_assembly` | Hvilke assemblies bruker en gitt del? (omvendt BOM-oppslag) |

---

## Databaseskjema (db.py)

| Tabell | Innhold |
|---|---|
| `products` | Alle produkter med metadata (WLL, kategori, tegningsnr, varenr, material osv.) |
| `dimensions` | Dimensjonsverdier per produkt (key/value) |
| `components` | Stykkliste — kobler sammenstillinger til deler |
| `product_standards` | Standarder per produkt (normalisert, én rad per standard) |
| `embeddings` | Binære vektorer (float32) for semantisk søk |

---

## Filer

| Fil | Formål |
|---|---|
| `server.py` | MCP-server med alle tool-definisjoner |
| `db.py` | All databaselogikk — insert, søk, semantisk søk |
| `config.py` | Stier, modellnavn, API-nøkkel |
| `extract.py` | PDF → Claude Vision API → SQLite (tegninger og enkeltprodukter) |
| `extract_catalog.py` | Katalog-PDF → pdfplumber tabellparsing → SQLite |
| `embed.py` | Generer og lagre sentence-embeddings for alle produkter |
| `prompts/extraction.txt` | Prompt som styrer Claude-ekstraksjon fra PDF |
| `requirements.txt` | Python-avhengigheter |
| `New_data/superdatabase.db` | SQLite-databasen (ikke i git) |
| `Nosted_data/` | Kilde-PDF-er (ikke i git) |

---

## Kjøring

```bash
# Ekstraher data fra PDF-er
py extract.py

# Generer embeddings for semantisk søk
py embed.py

# Start MCP-serveren (startes automatisk av Claude Desktop)
py server.py
```

**Claude Desktop config** (`%LOCALAPPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "nosted-product-search": {
      "command": "py",
      "args": ["C:\\Users\\even.vehus\\Documents\\Visual-Studio-Code-stuff\\Nosted_poc\\server.py"]
    }
  }
}
```

---

## Kjente begrensninger

- `get_products_in_assembly` er avhengig av at `component_product_id` er populert under ekstraksjon — fungerer delvis på `part_number`-matching som fallback
- Semantisk søk laster embeddingsmodellen (120 MB) ved første kall — tar noen sekunder
- Datakvaliteten fra PDF-ekstraksjon varierer med PDF-layout; tabulære kataloger er mer pålitelig enn frihåndstegninger
- Databasen inneholder kun de PDF-ene som er lastet inn — ikke hele Nøsteds katalog på ~8 500 tegninger

---

## Mulige neste steg

- Business Central-integrasjon (lager, pris, ordrehistorikk)
- Web-grensesnitt for KSS/Salg
- Automatisk klassifisering av innkommende forespørsler (Standard / Repeat / ETO)
- Skalering til full tegningsbase (~8 500 filer)
