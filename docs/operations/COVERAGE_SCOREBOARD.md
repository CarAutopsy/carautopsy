# Austrian Coverage Scoreboard

## Pilot target

Achieve at least 95 percent practical coverage of Austrian passenger vehicles
from model years 2017–2026, prioritized by recent registration share.

Coverage is a pilot metric, not a claim that every trim, engine, market,
or historical variant has been cataloged.

## Metrics

| Metric | Definition | Target |
|---|---|---:|
| Registration-weighted model coverage | Share of 2025 Austrian new passenger-car registrations represented by cataloged models | 95% |
| Top-brand coverage | Share of the top 10 Austrian brands with at least one represented current/recent model | 100% |
| Top-model coverage | Share of the top 25 Austrian models represented | 95% |
| Powertrain coverage | Separate coverage for ICE, hybrid, PHEV, and BEV priority models | 95% |
| Price-quality coverage | Share of priority records with a usable price tier | 95% |
| TCO readiness | Share of priority records that are TCO-ready or provisionally TCO-ready | 90% |
| Correction backlog | Count of approximate, cross-market, range, or unavailable records requiring review | Tracked |

## Price-quality distribution

Track records separately by:

- `verified`
- `derived`
- `approximate`
- `approximate_cross_market`
- `range`
- `unavailable`

## Reporting rules

- Report the exact catalog record count and the population used for each
  percentage.
- Never count an approximate price as verified.
- Never count a provisional TCO result as fully TCO-ready.
- Include the report generation date and the catalog commit SHA.
- Identify the highest-impact missing models in every report.

## First milestone

Represent the 2025 Austrian top-selling models, the top 10 brands, and the
leading BEV and hybrid models at least at `approximate` price quality.

## Safeguards

This scoreboard is documentation only. It does not authorize catalog writes,
network retrieval, provider calls, workflow changes, CI changes, approval-gate
changes, or secret access.
