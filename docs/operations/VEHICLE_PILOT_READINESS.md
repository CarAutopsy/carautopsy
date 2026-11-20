# Fixture-only Austrian vehicle-data pilot — readiness checklist

**Status:** Offline demonstration and design input. **Not authorized, not accepted, not activated.** No value in these fixtures is a verified vehicle fact.
**Tracking:** issue #119 Job 7. **Baseline:** `main` at `c3aad866d255e8b040d96e08c90a3705fb854a04`.

## 1. Minimum vehicle record schema

The repository schema `schemas/vehicle-variant.schema.json` (Draft 7) is authoritative. At minimum a record needs:

| Level | Required | Notes |
|---|---|---|
| Root | `schema_version`, `variant_id`, `status`, `identity`, `provenance` | Additional properties are permitted; schema validity is not data quality. |
| `identity` | `make` | Reserved task identity (`variant_id`, `make`, `model`) is checked against the reserved task, not inferred from model output. |
| `provenance` | `confidence` ∈ `low`, `medium`, `high`, `official` | `sources`, `claim_evidence` are arrays; spans are shape-validated by schema, coverage by `hive_candidate`. |

For an Austrian TCO pilot, the following non-null decision fields are the minimum evidence-bound set (per `hive_candidate._decision_claim_paths`):

- `identity.powertrain`, `identity.model_year_from`, `identity.vehicle_class`
- `performance.electric_motor_continuous_power_w` (M1 BEV motor tax)
- `dimensions.own_weight_kg`, `dimensions.max_permissible_mass_kg` (motor tax, 3500 kg schedule)
- `offers[0].country`, `offers[0].currency`, `offers[0].list_price_minor`

`identity.make`, `identity.model` and `offers[].offer_id` are task-supplied and exempt from claim evidence. Unknown external values must remain omitted/null rather than fabricated.

## 2. Fixture inventory (all synthetic)

| File | Purpose |
|---|---|
| `tests/fixtures/pilot/at_bev_synthetic.json` | Synthetic Austrian BEV record with nine claim bindings and owner-pipeline provenance fields. |
| `tests/fixtures/pilot/at_bev_evidence.json` | One bounded evidence item with exact quoted spans and a `document` locator. |
| `tests/fixtures/pilot/at_bev_source_policy.json` | Owner-controlled policy fixture: exact host/URL, automated access, terms review date. |
| `tests/test_vehicle_pilot.py` | Eight offline tests exercising the gates below. |

No fixture contains a real OEM URL, real specification, secret, or live provider reference. `oem.example` is reserved for documentation.

## 3. Gates demonstrated offline

| Gate | Test | Result |
|---|---|---|
| Schema validity | `test_minimum_record_validates_against_repository_schema` | PASS |
| Source-to-claim provenance and non-mutation | `test_source_to_claim_provenance_passes_deterministic_gate` | PASS; all nine bindings required, input unchanged |
| Conflicting specification | `test_conflicting_specification_quote_is_rejected` | FAIL CLOSED: quote not an exact span |
| Missing field / missing binding | `test_missing_schema_field_and_missing_claim_binding_are_rejected` | FAIL CLOSED at schema and coverage layers |
| Evidence / terms expiry | `test_expired_source_terms_are_denied_before_any_target_fetch` | FAIL CLOSED before fetch |
| Source-policy enforcement | `test_unapproved_host_is_denied_before_any_fetch` | FAIL CLOSED, fetcher never called |
| Approved exact source + robots | `test_approved_host_and_url_allow_with_robots_permission` | PASS; only `/robots.txt` bootstrap requested |
| Dual-auditor quorum | `test_dual_auditor_acceptance_requires_two_independent_exact_passes` | Two distinct vendors with exact `PASS` required; ambiguous/single/same-vendor rejected |

Local verification: `python -m pytest tests/test_vehicle_pilot.py -q` → **8 passed**; `compileall -q scripts tests` → exit 0.

## 4. Dual-auditor acceptance and owner approval

- Each auditor verdict must be parsed by `hive_audit.concise_audit_verdict`: exactly standalone `PASS`, or a single-line `FAIL: <reason>`. Anything else is `INVALID_AUDIT_RESPONSE` and cannot satisfy the gate.
- Acceptance requires **two different vendors** returning exact `PASS` over the same immutable candidate/evidence bundle. The five-service AI cross-review is advisory and is not a substitute.
- Proof of traceability (an exact quote at a stated locator) is **not** proof of factual truth, source authenticity, market/year identity or legal compliance.
- Publication requires a recorded owner decision on an exact SHA. No proposal reaches `done` on the basis of a PR, a green check or an AI review alone. The approved-source manifest stays empty until the owner reviews each exact host, URL, relevance and automated-access term.

## 5. Pilot readiness checklist

- [x] Minimum schema and evidence-bound decision-field set documented.
- [x] Synthetic record, evidence and policy fixtures created and locally validated.
- [x] Source-to-claim traceability and fail-closed behavior demonstrated offline.
- [x] Conflicting specifications, missing fields and expired terms rejected.
- [x] Dual-auditor quorum and owner-approval criteria defined.
- [ ] Owner reviews and accepts the pilot design on an exact SHA.
- [ ] Owner reviews each proposed exact source host/URL/terms before any manifest entry.
- [ ] Issue #37 owner security verdict and five-service cross-review recorded at an exact integrated SHA.
- [ ] Exact-head CI and Repository Audit green on the final SHA.
- [ ] Separate explicit owner authorization before any live retrieval, provider call or queue dispatch.

## 6. Safety boundary

The research pause stays active, `VERIFIED_RETRIEVAL_AVAILABLE = False`, and the approved-source manifest stays empty. This demonstration performs no live OEM request, no paid provider call, no queue dispatch, no roadmap write and no merge. It does not establish that any vehicle record is complete, accurate or legally usable in Austria.
