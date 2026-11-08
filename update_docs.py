import os
import subprocess

def run(cmd):
    print(f"  > {cmd}")
    subprocess.run(cmd, shell=True)

def write(path, content):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"Created: {path}")

print("Building CarAutopsy Documentation & Protocols...")

write("README.md", '''# CarAutopsy

**Dissect your car's true ownership cost and market value—calculated for where you actually live.**

A web-first financial diagnostic platform combining transparent TCO calculation with market-informed vehicle valuation. Launch market: Austria.

## Architecture

| Layer | Tech | Status |
|:---|:---|:---|
| Frontend | Next.js, TypeScript, Tailwind CSS | Scaffold |
| API & Engine | Python, FastAPI, Pydantic | Scaffold |
| Vehicle Catalog | Version-controlled JSON (Git) | Active |
| Country Packs | YAML rule files | AT in progress |

## Quick Start

~~~bash
git clone git@github.com:CarAutopsy/carautopsy.git
cd carautopsy
python scripts/validate_catalog.py
~~~

## Documentation & Protocols

All operational protocols, business plans, and writing guidelines live in the `docs/` folder. Strict adherence is required for all contributors and AI agents.

| Document | Version | Description |
|:---|:---|:---|
| [Vehicle Catalog Protocol](docs/protocols/vehicle-catalog-protocol-v104.md) | v1.04 | Canonical spec storage, identity model, source policy |
| [Article-Writing Protocol](docs/protocols/article-writing-protocol-v104.md) | v1.04 | Content voice, formatting, citation, image specs |
| [Session Handover Protocol](docs/protocols/session-handover-protocol-v101.md) | v1.01 | Operational continuity between AI agents and sessions |
| [Business Plan](docs/business-plan-v103.md) | v1.03 | Product vision, architecture, phased rollout |
| [Data Rights Policy](docs/data-rights-policy-v101.md) | v1.01 | Per-source licence and compliance framework |

## Data Policy

This project **strictly prohibits** bypassing site terms or access controls.
See [Source Policy](docs/protocols/vehicle-catalog-protocol-v104.md#2-source-policy).

## Author

- **GitHub:** [@realarchitekt](https://github.com/realarchitekt)
- **ORCID:** [0009-0006-5245-6431](https://orcid.org/0009-0006-5245-6431)

## Licence

Proprietary. All rights reserved. See [LICENSE](LICENSE).
''')

write("docs/protocols/vehicle-catalog-protocol-v104.md", '''# CarAutopsy Vehicle Catalog Protocol
Version: 1.04 | Date: 23 August 2026 | Status: Working draft

This document defines how CarAutopsy stores canonical vehicle specifications. It is separate from market listings, country-pack tax rules, and TCO calculations.

## 1. Purpose
The catalog answers: what is this exact variant?
It does not answer: what is this used car worth in Vienna today?

## 2. Source Policy
CarAutopsy strictly prohibits designing ingestion pipelines around bypassing site terms or access controls. EV Database is used strictly as a field checklist.

## 3. Identity Model
Make > Model > Generation > Variant > Trim > Market-year offer

## 4. File Layout
Start with version-controlled JSON files in Git; migrate to PostgreSQL when cross-table joins become necessary.

## 5. Units and Data Types
All values use SI units. Unknown values must be set to `null`, never `0`.

## 8. Provenance & Confidence Tiers
- official: Primary OEM or type-approval dataset.
- high: Two independent authorities.
- medium: Single compiled source, verified.
- low: Unstructured listing placeholder.
''')

write("docs/protocols/article-writing-protocol-v104.md", '''# Article-Writing Protocol
Document ID: AWP | Version: v104 (1.04) | Date: 2026-10-11

## 1. Preserve my purpose and argument
Identify the central observation before writing. Preserve the intended angle.

## 2. Use clean, categorised Markdown
Use one clear # title and descriptive ## section headings.

## 3. Write with wit, bite and a human voice
Default voice is skeptical: witty, critical and occasionally salty.

## 7. Use numbered IEEE-style references
Place numbered citations in the text and a matching References section at the end.

## 10. Design platform-specific covers and preview images
Create separate exports for X (5:2), LinkedIn (16:9), Medium (2:1), Substack, and Reddit.
''')

write("docs/protocols/session-handover-protocol-v101.md", '''# Project Session Handover Protocol
Document ID: SHP | Version: v1.01 (1.01) | Date: 2026-10-27

## 1. Purpose
Makes every work session recoverable by the next AI agent or human contributor. Preserves operational state across chat resets and long gaps.

## 3. Precedence Rules
1. Explicit written owner decision.
2. Repository state at the recorded commit SHA.
3. Audit evidence tied to that commit.
4. Latest valid session handover.

## 5. Session Record Location
Store in: .civlab/sessions/
Format: CIVLAB-SESSION-{AGENT}-{YYYYMMDD}-{HHMM}-{SEQ}.md
''')

write("docs/business-plan-v103.md", '''# CarAutopsy Business Plan
Version: 1.03 (draft) | Date: 23 August 2026 | Launch Market: Austria

## 1. Executive Summary
CarAutopsy is a web-first financial diagnostic platform combining TCO calculation with asking-price valuation ranges.

## 4. Product Scope (MVP)
Inputs: Vehicle identity, odometer, condition, postal code, mileage, timeframe.
Outputs: 3-point value range, granular TCO autopsy, assumptions editor, PDF report.

## 6. Phased Rollout
Phase 1: Consumer Validation (Free Calc / €9-19 Report)
Phase 2: Retention (Premium €49-79/yr)
Phase 3: Commercial Scaling (B2B API)
''')

write("docs/data-rights-policy-v101.md", '''# Data Rights Policy
Version: 1.01 (draft) | Date: 2026-11-08 | Owner: @realarchitekt

## Principle
CarAutopsy does not design ingestion pipelines around bypassing site terms or access controls.

## Rules
1. Never store scraped content from sources that prohibit automated access.
2. Always record retrieved date, licence status, and role in provenance.
3. All statutory calculations must trace to an official government publication.
''')

write("docs/changelog.md", '''# CarAutopsy — Document Changelog

| Version | Date | Document | Change |
|:---|:---|:---|:---|
| v1.04 | 2026-08-23 | Vehicle Catalog Protocol | Initial specification |
| v1.03 | 2026-08-23 | Business Plan | Renamed to CarAutopsy |
| v1.04 | 2026-10-11 | Article-Writing Protocol | Image presets |
| v1.01 | 2026-10-27 | Session Handover Protocol | AI continuity standard |
| v0.2.0 | 2026-11-08 | Repository | Populated docs/protocols/ structure |
''')

print("\nCommitting and pushing to GitHub...")
run("git add -A")
run('git commit -m "docs: establish official protocols and documentation structure"')
run("git push origin main")

print("\n✅ Documentation successfully built and pushed!")