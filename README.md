# CarAutopsy

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
| [Engineering Roadmap](docs/operations/ROADMAP.md) | Current | Dependency-ordered engineering roadmap and Hive activation gates |
| [Current Project State](docs/operations/CURRENT_STATE.md) | Current | Verified project status and operational constraints |
| [Next Actions](docs/operations/NEXT_ACTIONS.md) | Current | Immediate implementation sequence |
| [Hive Pipeline Integration](docs/operations/HIVE_PIPELINE_INTEGRATION.md) | Current | Zero-bypass runtime integration contract |
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
