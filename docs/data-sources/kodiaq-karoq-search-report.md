# Kodiaq / Karoq price-source search — exhaustive, negative result

**Status:** Exhaustive public-archive search completed **without finding a verified price**.
All 22 Kodiaq/Karoq variants remain unresolved with reason
`no_source_found_after_exhaustive_search`. No value was invented.
**Date:** 2026-11-21.
**Reproduce:** `python scripts/search_kodiaq_karoq_prices.py --output <local-temp>/search.json`
(raw responses are cached only in the system temp directory; no crawl dumps are committed).

## 1. What was searched

All requests used an identified User-Agent, robots.txt validation, and a 2-second
per-host rate limit. CDX queries used `output=json`, `filter=statuscode:200`, no
mimetype filter for the primary patterns, and `limit=100` (300/60 for the broad
host queries), with two windows per pattern: **2017** and **2018–2019**.

| # | URL pattern | 2017 | 2018–2019 |
|---|---|---:|---:|
| 1 | `www.skoda.at/kodiaq*` | 85 | 100 |
| 2 | `www.skoda.at/karoq*` | 5 | 100 |
| 3 | `www.skoda.at/modelle/kodiaq*` | 0 | 0 |
| 4 | `www.skoda.at/modelle/karoq*` | 0 | 0 |
| 5 | `www.skoda.at/preisliste*` | 0 | 0 |
| 6 | `www.skoda.at/preise*` | 0 | 0 |
| 7 | `www.skoda.at/*` (all types, limit 300) | 300 | 300 |
| 8 | `www.skoda.at/*` (PDF only, limit 60) | 15 | timed out, retried separately → 24 |

**Totals:** 16 queries attempted, 15 succeeded within the script run (one PDF
query timed out and was re-run manually), **905 snapshots**, **558 unique URLs**.

Additional attempts: CDX `matchType=regex` for `.*(kodiaq|karoq).*` and
`.*streuer.*` returned HTTP 400 in this environment and could not be used; the
broad host queries above cover the same document set by a different route.

## 2. Documents extracted

15 snapshots were downloaded and passed through the
**pdfplumber → PyMuPDF → OCR** fallback chain: 14 `text/html` model pages
(`kodiaq`, `kodiaq/der-neue-kodiaq/6:preise-technische-daten`, `karoq-scout`,
`karoq-sportline`, `kodiaq-rs`, …) and 1 PDF. All 15 yielded text
(`text_ok=15`), but **zero** contained a `PREISE KODIAQ` or `PREISE KAROQ`
table header, and **zero** yielded a price.

The HTML "prices and technical data" pages are dynamically rendered shells:
their archived source contains only markup and layout JavaScript (e.g.
`data-width-steps="[1,101,201,…]"`). No `EUR`, `€`, or German-format list
price appears in them.

The complete archived Škoda PDF library for 2017 (15 PDFs) and 2018–2019
(24 PDFs, retrieved on retry) was enumerated. It contains price lists only for
**Citigo, Fabia, Rapid, Octavia, Superb and Scala**, plus the
`FABIA20-Streuer-03-2019.pdf` that resolved Fabia. **No Kodiaq or Karoq price
list, brochure with a price table, or tax guide ("Streuer") exists** in the
archived set.

## 3. Conclusion

No compliant, dated, attributable Austrian price source for Kodiaq or Karoq
was found in the permitted public archive set. Per the no-fabrication rule,
the 22 variants (12 Kodiaq + 10 Karoq) stay unresolved:

- `docs/data-sources/price-evidence/v1.json` — unchanged (36 rows).
- `docs/data-sources/price-evidence/unresolved.json` — 22 rows, all now
  `no_source_found_after_exhaustive_search`.
- Coverage remains identity 154/154, price 114/154, catalog-eligible 114,
  TCO-ready 0.

**Next options (owner decision required):** supply an owner-approved price
source with documented terms; accept a manual-curation row with an attributed
source document; or leave these 22 variants out of the catalog. No batch PR or
catalog write is created by this research.
