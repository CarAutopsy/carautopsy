# CarAutopsy Vehicle Catalog Protocol
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
