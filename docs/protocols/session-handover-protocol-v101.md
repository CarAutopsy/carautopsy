# Project Session Handover Protocol
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
