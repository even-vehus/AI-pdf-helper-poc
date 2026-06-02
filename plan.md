# POC-plan: AI-drevet produktsøk for Nøsted &

## Sammendrag

Nøsted & har ca. 8 500 tekniske tegninger (PDF) og produktkataloger som dekker kjetting, kroker, sjakler, løfteåk, løkker, kjettingredskaper, ROV-utstyr, havbruksutstyr m.m. Når kunder spør etter produkter med bestemte spesifikasjoner (f.eks. «krok som tåler 3,5 tonn»), må salg/KSS i dag lete manuelt gjennom filer, kataloger og Business Central.

Målet med denne POC-en er å la Claude svare på slike spørsmål automatisk ved å søke i en strukturert database over produktdata og tekniske tegninger. Vi har en produktkatalog og noen tekniske tegninger som vi bruker som eksempel for POC'en.

---

## Arkitektur (POC)

```
┌──────────────┐
│   Kunde-      │
│  forespørsel  │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   Claude      │  ← bruker MCP-verktøy for å søke
│   (chat)      │
└──────┬───────┘
       │  MCP tool calls
       ▼
┌──────────────────────────────────┐
│   MCP Server (Node.js / Python)  │
│                                  │
│  Verktøy:                        │
│  1. search_products(query)       │
│  2. get_product_details(id)      │
│  3. find_by_spec(wll, dim, ...)  │
│  4. list_categories()            │
└──────┬───────────────────────────┘
       │  SQL queries
       ▼
┌──────────────┐     ┌──────────────┐
│   SQLite DB   │     │  PDF-filer    │
│  (metadata)   │     │  (originaler) │
└──────────────┘     └──────────────┘
```

---

## Fase 0: Utviklingsmiljø (før Uke 1)

Hele POC-en avhenger av PDF-prosessering. Maskinen som ble brukt under planleggingen hadde **kun Windows Store-stubben for Python og ingen poppler/pdftoppm** — det blokkerer både kataloglesing og ekstraksjon. Sett opp før Fase 1:

- **Python 3.11+** (ekte installasjon, ikke Store-stubben)
- **PyMuPDF** (`fitz`) for rasterisering — unngår ekstern poppler-avhengighet
- (valgfritt) **poppler** hvis `pdf2image` foretrekkes
- **anthropic** SDK + `ANTHROPIC_API_KEY`
- **sqlite3** (følger med Python)

---

## Fase 1: Dataekstraksjon (Uke 1–2)

### 1.1 Kartlegging av datakilder

| Kilde | Innhold | Format | Volum |
|---|---|---|---|
| Tekniske tegninger | Produkttegninger med mål, WLL, materialer, standarder | PDF (CAD-eksport) | ~8 500 filer |
| Produktkatalog | Tabeller med varenr, dimensjoner, WLL, vekt, prøvekraft | PDF | 2 versjoner |
| Tidligere tilbud/ordrer | Historikk fra BC | Strukturert data (BC) | — |

**Vedlagte POC-filer (faktiske eksempeldata i `Nosted_data/`):**

| Fil | Sider | Innhold | Type |
|---|---|---|---|
| `PH1Spesial.pdf` | 1 | PH-1 spesial krok, WLL 3,4 t, Varenr 0302601 / Vare nr T1240047, tegning 124-0047, materiale SAE 6620 | Enkeltkomponent |
| `lofteaakStorsekk.pdf` | 4 | **3 produkter i én fil:** Tigrip TTB spredebom (3.parts katalog, Art-No N53156300–303, 1000–2000 kg) + FRAM 634-58251 Kryss åk WLL 2,5 t (T63458251) + FRAM 634-58262 Kryssåk lavtbyggende WLL 2 t (T63458262) | Blandet: 3.part + 2 tegninger |
| `loftearrangement.pdf` | 3 | FRAM 634-40863 Lifting arrangement for PS 21/PS 30, WLL 6 t (T63440863), med komplett stykkliste (8 komponenter m/antall) | Sammenstilling (BOM) |
| `produktkatalogshort.pdf` | 42 | Hovedkatalogen — tabulære produktdata (~500+ varianter) | Katalog |

**Viktige observasjoner fra eksempeldataene (styrer datamodellen):**

1. **Én PDF = flere produkter.** `lofteaakStorsekk.pdf` inneholder 3 distinkte produkter (1 tredjepart + 2 FRAM-tegninger). Ekstraksjon må returnere en **liste** med produkter per fil; `source_file` er ikke en unik nøkkel.
2. **Sammenstillinger har stykklister (BOM).** Løftearrangementet og kryssåkene er bygget av katalogkomponenter med antall. Krever en egen `components`-tabell (se 2.1) for å besvare spørsmål som scenario #4.
3. **Flere identifikatorskjemaer:** `Varenr` (0302601), `Vare nr`/`Item No` (T1240047, T63458251), `Drawing nr` (124-0047, 634-58251) og tredjeparts `Art-No` (N53156300). `T`-varenumrene ser ut til å være avledet fra tegningsnummer (`T` + siffer uten bindestrek). Normaliseres og dokumenteres.
4. **Tredjepart vs. FRAM-produsert.** Tredjepart (Tigrip) bruker modellnavn + kapasitet i kg; FRAM bruker WLL i tonn + prøvekraft i kN. Skill med `source_type` og normaliser enheter ved ekstraksjon.
5. **Status/DRAFT.** 634-58251 er stemplet «DRAFT» — fang status, ikke bare `revision`.

### 1.2 Metadataekstraksjon

For POC-en bruker vi Claude API (Sonnet) til å ekstrahere strukturert metadata fra PDF-ene. Hvert dokument sendes som base64 til Claude med en prompt som ber om JSON-output.

**Metadata-skjema per produkt:**

```json
{
  "source_file": "lofteaakStorsekk.pdf",
  "source_page": 2,
  "source_type": "fram_drawing",
  "product_name": "Kryss åk for Storsekk",
  "product_name_en": "Cross yoke for Big Bags",
  "item_number": "T63458251",
  "drawing_number": "634-58251",
  "category": "Løfteåk",
  "wll_tonnes": 2.5,
  "proof_force_kn": 59,
  "weight_kg": 25,
  "standard": "Maskin Direktiv 2006/42/EC",
  "certification": "Løftesertifikat Form 4",
  "surface_treatment": "Lakkert med farge RAL 1004",
  "material": null,
  "dimensions": {
    "length_mm": 900,
    "width_mm": 900,
    "height_mm": null
  },
  "designed_for": "Storsekk / Big Bag",
  "date": "2026-01-17",
  "revision": "GB",
  "status": "draft",
  "manufacturer": "FRAM / Kjættingfabriken AS",
  "related_standards": ["NS-EN 13414-1", "NS-EN 13610-1"],
  "components": [],
  "tags": ["løfteåk", "storsekk", "big bag", "kryss", "4-punkt"]
}
```

`source_type` er én av: `fram_drawing` (FRAM-produsert tegning), `assembly` (sammenstilling m/stykkliste), `third_party` (katalogprodukt fra leverandør, f.eks. Tigrip), `catalog_row` (rad i hovedkatalogen). `status` er `released` eller `draft`. `components` er tom for enkeltkomponenter; for sammenstillinger inneholder den stykklisten:

```json
"components": [
  {"part_number": "0219007", "description": "6.5 t Bow shackle", "qty": 4, "length_mm": null, "grade": "8"},
  {"part_number": "430-40864", "description": "13 x 39mm Chain NS-EN 818", "qty": 2, "length_mm": 3276, "grade": "8"},
  {"part_number": "430-40866", "description": "10 x 30mm Chain NS-EN 818", "qty": 4, "length_mm": 3210, "grade": "8"}
]
```

**Ekstraksjonsmetode:**

1. **PDF → Bilde:** Rasteriser hver side med `pdf2image` / `pymupdf`
2. **Bilde + Tekst → Claude API:** Send som multimodal request med system prompt som ber om JSON. Prompten må be om en **liste** med produkter (en PDF kan inneholde flere — jf. `lofteaakStorsekk.pdf`), og om stykkliste (`components`) der det finnes en BOM-tabell.
3. **Validering:** Sjekk at obligatoriske felt er fylt ut, flagg ufullstendige poster. Normaliser enheter (kg→tonn for tredjeparts kapasitet).
4. **Lagring:** Skriv hvert produkt + tilhørende komponenter til SQLite.

**For katalog-PDFer (tabulære data):**
Katalogene inneholder store tabeller. Her ekstrahere vi rad for rad til databasen — én rad per produkt/variant. Eksempel fra Fram Alloy kjetting:

```
varenr=0101100, dim="6x18", wll=1.12, proof_force=28.3, 
break_force=45.2, D=6.0, L=18, B=8.0, kg_per_m=0.8
```

### 1.3 Ekstraksjonsskript (overordnet)

```python
# Pseudokode for batch-ekstraksjon
for pdf_file in all_pdfs:
    pages = render_pdf_to_images(pdf_file)   # alle sider

    response = claude_api.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[{
            "role": "user",
            "content": [
                *[{"type": "image", "source": {"type": "base64", ...}} for p in pages],
                {"type": "text", "text": EXTRACTION_PROMPT}
            ]
        }],
        max_tokens=8000
    )

    products = parse_json(response)          # LISTE med produkter (kan være flere per fil)
    for product in products:
        product_id = insert_product(product)
        insert_components(product_id, product.get("components", []))
        insert_dimensions(product_id, product.get("dimensions", {}))
```

---

## Fase 2: Database (Uke 2)

### 2.1 SQLite-skjema

```sql
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    source_page INTEGER,           -- side i PDF (flere produkter kan dele fil)
    source_type TEXT,              -- fram_drawing | assembly | third_party | catalog_row
    product_name TEXT,
    product_name_en TEXT,
    item_number TEXT,
    drawing_number TEXT,
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
    status TEXT,                   -- released | draft
    manufacturer TEXT,
    tags TEXT,  -- JSON array som tekst
    full_description TEXT  -- fritekst-beskrivelse for søk
);

-- Stykkliste (BOM): kobler en sammenstilling til komponentene den består av
CREATE TABLE components (
    id INTEGER PRIMARY KEY,
    assembly_id INTEGER REFERENCES products(id),  -- sammenstillingen (f.eks. 634-40863)
    part_number TEXT,             -- komponentens varenr (f.eks. 0219007)
    description TEXT,             -- f.eks. "6.5 t Bow shackle" / "13 x 39mm Chain NS-EN 818"
    qty INTEGER,
    length_mm REAL,               -- for kjetting/wire med oppgitt lengde
    grade TEXT,                   -- f.eks. "8"
    component_product_id INTEGER REFERENCES products(id)  -- kobles til katalogprodukt hvis det finnes
);

CREATE TABLE dimensions (
    id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    dimension_key TEXT,  -- f.eks. "D", "L", "B", "length", "width"
    value_mm REAL,
    description TEXT
);

CREATE TABLE product_standards (
    product_id INTEGER REFERENCES products(id),
    standard_code TEXT  -- f.eks. "NS-EN 818-2"
);

-- Indekser for rask søking
CREATE INDEX idx_wll ON products(wll_tonnes);
CREATE INDEX idx_category ON products(category);
CREATE INDEX idx_item_number ON products(item_number);
CREATE INDEX idx_drawing_number ON products(drawing_number);
CREATE INDEX idx_product_name ON products(product_name);
CREATE INDEX idx_comp_assembly ON components(assembly_id);
CREATE INDEX idx_comp_part ON components(part_number);
```

### 2.2 Kategorier (basert på katalogen)

Basert på den vedlagte produktkatalogen definerer vi disse kategoriene:

| Kategori | Eksempler |
|---|---|
| Kjetting | Kortlenket, langlenket, halvlanglenket, kalibrert, varmforsinket, rustfri |
| Koplingselementer | YA, YO, EC, YG, YW |
| Sjakler | Kort type A/B/C, lang type A/C, offshore, alloy |
| Løkker | B-løkker, A-løkker, ringer, sjakkelløkker, løftehoder |
| Kroker | Selvlukkende (YC/YE/YD/YEN), slavekrok (SK/YP/YSW/YM), innkortningskrok (YH), støperikrok, containerkrok, gravemaskinkrok, PH-krok, storsekk-krok, ROV-kroker |
| Løftepunkt | Øyebolter, Lifting Points |
| Kjettingredskaper | 1-part, 2-part, 3-4 part stropper, plateklyper, trommelløftere |
| Løfteåk | Spredebom, kryssåk |
| Surringsutstyr | Bennebjønn, strekkfisker, surrekjetting, lastesurringer |
| Kabelarer | Type L, K, H |
| Mykløft | Rundsling, båndstropper |
| Ståltau | Wireropes |
| ROV-produkter | Modifiserte kroker, ROV-sjakler, twist-lock |
| Havbruk | Aquaculture-kjetting, fortøyningsplater, dregger |
| Grade 100 | G-100 kjetting og komponenter |
| Rustfritt | Syrefast kjetting og komponenter |

---

## Fase 3: MCP Server (Uke 2–3)

### 3.1 Verktøy-definisjon

MCP-serveren eksponerer følgende 6 verktøy til Claude:

**1. `search_products`** — Fritekst/parametersøk
```
Input:  query (string), category (optional), min_wll (optional), max_wll (optional)
Output: Liste med matchende produkter (maks 20)
```

**2. `get_product_details`** — Hent all info om ett produkt
```
Input:  product_id ELLER item_number ELLER drawing_number
Output: Komplett produktinfo inkl. dimensjoner
```

**3. `find_by_specification`** — Spesifikasjonssøk
```
Input:  wll_tonnes, chain_dim, for_chain_dim, hook_type, material, standard, ...
Output: Produkter som matcher (sortert etter relevans)
```

**4. `list_categories`** — Vis tilgjengelige kategorier
```
Input:  (ingen)
Output: Liste med kategorier og antall produkter
```

**5. `get_drawing`** — Hent PDF-fil for et produkt
```
Input:  product_id ELLER drawing_number
Output: Filsti til PDF (+ sidetall hvis flere produkter deler fil)
```

**6. `get_assembly_components`** — Hent stykkliste for en sammenstilling
```
Input:  product_id ELLER drawing_number (f.eks. 634-40863)
Output: Liste med komponenter (varenr, beskrivelse, antall, lengde, grade)
```

### 3.2 Teknologivalg

| Komponent | Valg | Begrunnelse |
|---|---|---|
| MCP Server | Python (`mcp` SDK) | Raskest å utvikle, god SQLite-støtte |
| Database | SQLite | Ingen infrastruktur, filbasert, perfekt for POC |
| PDF-prosessering | PyMuPDF + Claude API | Håndterer både tekst og bilde-baserte tegninger |
| Hosting (POC) | Lokalt / Claude Desktop | Enklest for demo |

### 3.3 MCP Server-struktur

```
nosted-product-search/
├── server.py              # MCP server med tool-definisjoner
├── db.py                  # Database-tilgang (SQLite)
├── extract.py             # PDF metadata-ekstraksjon
├── config.py              # Konfigurasjon
├── data/
│   ├── products.db        # SQLite database
│   └── pdfs/              # Originale PDF-filer
├── prompts/
│   ├── extraction.txt     # Prompt for metadata-ekstraksjon
│   └── catalog_extraction.txt
├── requirements.txt
└── README.md
```

---

## Fase 4: Integrasjon og testing (Uke 3–4)

### 4.1 Test-scenarioer

Basert på den vedlagte arbeidsflyten («Håndtering av forespørsler») og produktkatalogene. Kolonnen «Dekkes av POC-data» viser hvilke scenarioer som kan testes med de 4 vedlagte filene allerede nå:

| # | Spørsmål (norsk) | Forventet resultat | Dekkes av POC-data |
|---|---|---|---|
| 1 | «Jeg trenger en krok som tåler 3,5 tonn» | Viser slavekrok SK-42 (4,3t), YP-10 (3,15t), selvlukkende YC-10 (3,15t) m.fl. | Delvis — PH-1 (3,4t) finnes; øvrige krever katalog |
| 2 | «Har dere løfteåk for storsekk?» | Viser Kryssåk T63458251 (2,5t) og T63458262 (2t lavtbyggende) | ✅ `lofteaakStorsekk.pdf` |
| 3 | «Trenger 13mm kjetting, grade 80, hva er WLL?» | 5,3 tonn (varenr 0101100 rad 4) | Krever katalog |
| 4 | «Vi skal løfte 6 tonn fra en PS 21 slipp, hva har dere?» | Lifting arrangement T63440863 (+ stykkliste) | ✅ `loftearrangement.pdf` |
| 5 | «Hva er varenummeret for en YE-13 krok?» | 0312812, WLL 5,3 tonn | Krever katalog |
| 6 | «Trenger en sjakkel rated for offshore, 20 tonn» | Sjakkel lang type 32/4A (0207001) eller 32/4C (0207101) | Krever katalog |
| 7 | «Hva har dere i rustfritt for løft opp til 5 tonn?» | Rustfri kjetting 16x48 (5,0t), COHF 16 krok, CSA 13 sjakkel | Krever katalog |
| 8 | «Kjettingredskap, 4-part, 45° vinkel, 13mm kjetting — hva er WLL?» | 11,2 tonn | Krever katalog |

> Scenarioene som er merket «Krever katalog» kan ikke verifiseres før `produktkatalogshort.pdf` er lest inn (krever PDF-verktøy fra Fase 0).

### 4.2 Evaluering

| Metrikk | Mål | Metode |
|---|---|---|
| Treffrate | ≥80% relevante resultater | Manuell gjennomgang av 20 test-spørsmål |
| Responstid | <5 sekunder | Tidsmåling |
| Datakvalitet | ≥90% korrekt metadata | Stikkprøvekontroll mot kilde-PDF |
| Brukertilfredshet | Kvalitativ | Demo med KSS/Salg |

---

## Fase 5: Utvidelser (etter POC)

Disse punktene er utenfor POC-scope, men bør planlegges:

### 5.1 Vektordatabase for semantisk søk
For å håndtere vage spørsmål («noe å løfte tønner med» → fatbeslag/fatstropper) kan vi legge til vektorsøk med embeddings. Dette kombineres med det strukturerte SQL-søket.

### 5.2 Business Central-integrasjon
Koble til BC for lager/pris/ordrehistorikk. Kan gjøres via BC API eller MCP-connector. Muliggjør spørsmål som «har vi dette på lager?» og «hva kostet dette sist?».

### 5.3 Automatisk klassifisering av nye forespørsler
Koble til workflow-prosessen fra «Håndtering av forespørsler» — la Claude automatisk klassifisere innkommende forespørsler som Standard / Repeat / ETO General / ETO Prosjekt.

### 5.4 Multi-bruker web-grensesnitt
Bygg en enkel web-app der KSS/Salg kan stille spørsmål og få svar med produktkort og lenker til tegninger.

---

## Tidsplan

| Uke | Fase | Leveranse |
|---|---|---|
| 1 | Dataekstraksjon — katalogdata | SQLite DB med alle katalogprodukter (~500+ varianter) |
| 2 | Dataekstraksjon — tegninger + DB ferdig | SQLite DB med metadata fra tilgjengelige tegninger |
| 2–3 | MCP Server utvikling | Fungerende MCP-server med alle 6 verktøy |
| 3–4 | Integrasjon, testing, demo | Fungerende POC med Claude Desktop, testresultater |
| 4 | Dokumentasjon og evaluering | Rapport, anbefaling for videre utvikling |

---

## Risiko og forutsetninger

| Risiko | Konsekvens | Tiltak |
|---|---|---|
| PDF-er er rene bilder (skannet) uten tekst-lag | Ekstraksjon krever OCR/bildeanalyse, lavere nøyaktighet | Bruk Claude vision capabilities — fungerer godt på tekniske tegninger |
| Inkonsistent navngiving i filer | Vanskelig å koble tegning → produkt | Ekstraher identifikatorer fra tittelblokkene i tegningene |
| 8 500 filer koster mye i API-kall | Kostnad kan bli 500-2000 USD for full ekstraksjon | Start med POC-utvalg (vedlagte filer), skalér gradvis |
| Metadata-kvalitet varierer | Noen produkter mangler WLL, dimensjoner | Implementér validering og manuell review-workflow |

---

## Neste steg

1. **Godkjenn plan** — Gå gjennom denne planen med prosjektteamet
2. **Sett opp utviklingsmiljø** — Python, SQLite, Claude API-nøkkel
3. **Start med de vedlagte filene** — Ekstraher metadata fra de 4 tilgjengelige PDF-ene (3 tegninger + 1 katalog på 42 sider) som proof of concept
4. **Bygg MCP-server** — Implementer søkeverktøyene
5. **Demo med KSS/Salg** — Vis at konseptet fungerer, samle feedback
