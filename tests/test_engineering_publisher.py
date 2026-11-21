"""Offline tests for the inert owner-gated draft publisher (issue #114)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from engineering_publisher import (  # noqa: E402
    PublisherError,
    build_draft_pr_proposal,
    classify_publish_response,
    proposal_digest,
    reconcile_draft_pr,
    verify_proposal_digest,
)


BASE = {
    "task_id": "eng-publish-001",
    "repository": "CarAutopsy/carautopsy",
    "base_sha": "a" * 40,
    "allowed_paths": ["tests/fixtures/example.json"],
    "goal": "Bounded improvement with GITHUB_TOKEN=secret-value",
    "acceptance_criteria": ["tests pass", "review completes"],
    "max_patch_bytes": 1000,
    "max_files_touched": 2,
    "timeout_seconds": 60,
    "max_provider_calls": 2,
    "max_spend_units": 0,
    "requires_owner_approval": True,
}


def recompute_evidence_digest(artifact):
    payload = {key: value for key, value in artifact.items() if key != "evidence_digest"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def valid_artifact():
    artifact = {
        "schema_version": 1,
        "task_id": BASE["task_id"],
        "base_sha": BASE["base_sha"],
        "snapshot_digest": "b" * 64,
        "snapshot_intact_scope": "allowed_paths",
        "working_tree_intact": True,
        "working_tree_scope": "entire checkout (git status --porcelain)",
        "patch_digest": "d" * 64,
        "checks": [],
        "passed": True,
        "snapshot_intact": True,
        "provider_calls": 0,
        "live_source_requests": 0,
        "runtime_isolation_demonstrated": False,
        "execution_enabled": False,
        "draft_pr_created": False,
        "requires_owner_approval": True,
    }
    artifact["evidence_digest"] = recompute_evidence_digest(artifact)
    return artifact


def valid_quorum(artifact):
    return [
        {"vendor": "vendor-a", "verdict": "PASS",
         "bundle_sha256": artifact["snapshot_digest"], "base_sha": artifact["base_sha"]},
        {"vendor": "vendor-b", "verdict": "PASS",
         "bundle_sha256": artifact["snapshot_digest"], "base_sha": artifact["base_sha"]},
    ]


def make_proposal(**overrides):
    artifact = valid_artifact()
    options = {"contract": BASE, "verification_artifact": artifact,
               "audit_quorum": valid_quorum(artifact)}
    options.update(overrides)
    return build_draft_pr_proposal(**options)


def matching_pr(digest, **overrides):
    pr = {"number": 7, "headRefName": "eng/eng-publish-001",
          "baseRefName": "main", "isDraft": True,
          "body": f"proposal_digest: {digest}"}
    pr.update(overrides)
    return pr


class DraftPublisherTests(unittest.TestCase):
    def test_valid_proposal_is_deterministic_and_inert(self):
        first = make_proposal()
        self.assertEqual(first, make_proposal())
        self.assertEqual(first["branch"], "eng/eng-publish-001")
        self.assertTrue(first["draft"])
        for field in ("draft_pr_created", "execution_enabled", "publication_enabled",
                      "direct_main_push"):
            self.assertIs(first[field], False)
        self.assertIs(first["requires_owner_approval"], True)
        self.assertIs(first["owner_approved"], False)
        self.assertEqual(len(first["proposal_digest"]), 64)
        verify_proposal_digest(first)

    def test_secret_patterns_are_redacted_from_untrusted_text(self):
        proposal = make_proposal()
        self.assertNotIn("secret-value", proposal["title"])
        self.assertIn("[REDACTED]", proposal["title"])

    def test_digest_verification_and_tampering_rejection(self):
        proposal = make_proposal()
        self.assertEqual(proposal_digest(proposal), proposal["proposal_digest"])
        verify_proposal_digest(proposal)
        for bad in (
            dict(proposal, title="injected"),
            dict(proposal, direct_main_push=True),
            dict(proposal, proposal_digest="f" * 64),
            dict(proposal, proposal_digest=None),
        ):
            with self.subTest(bad=bad.get("title", bad.get("proposal_digest"))):
                with self.assertRaises(PublisherError):
                    verify_proposal_digest(bad)

    def test_fail_closed_on_unapproved_or_failed_verification(self):
        artifact = valid_artifact()
        with self.assertRaisesRegex(PublisherError, "owner_approved must be a boolean"):
            make_proposal(owner_approved="yes")
        artifact["passed"] = False
        artifact["evidence_digest"] = recompute_evidence_digest(artifact)
        with self.assertRaisesRegex(PublisherError, "verification did not pass"):
            make_proposal(verification_artifact=artifact)
        artifact = valid_artifact()
        artifact["working_tree_intact"] = False
        artifact["evidence_digest"] = recompute_evidence_digest(artifact)
        with self.assertRaises(PublisherError):
            make_proposal(verification_artifact=artifact)

    def test_tampered_or_isolation_claiming_evidence_is_rejected(self):
        artifact = valid_artifact()
        artifact["runtime_isolation_demonstrated"] = True
        artifact["evidence_digest"] = recompute_evidence_digest(artifact)
        with self.assertRaisesRegex(PublisherError, "runtime isolation"):
            make_proposal(verification_artifact=artifact)

        tampered = valid_artifact()
        tampered["provider_calls"] = 1
        with self.assertRaises(PublisherError):
            make_proposal(verification_artifact=tampered)

    def test_unaccepted_or_unbound_quorum_is_rejected(self):
        artifact = valid_artifact()
        quorum = valid_quorum(artifact)
        quorum[0]["verdict"] = "PASS with reservations"
        with self.assertRaisesRegex(PublisherError, "not accepted"):
            make_proposal(audit_quorum=quorum)

        quorum = valid_quorum(artifact)
        quorum[1]["base_sha"] = "c" * 40
        with self.assertRaisesRegex(PublisherError, "not bound"):
            make_proposal(audit_quorum=quorum)

        quorum = valid_quorum(artifact)
        quorum[0]["bundle_sha256"] = "e" * 64
        with self.assertRaisesRegex(PublisherError, "not bound"):
            make_proposal(audit_quorum=quorum)

        with self.assertRaises(PublisherError):
            make_proposal(audit_quorum=[quorum[0]])

    def test_invalid_task_or_branch_identity_is_rejected(self):
        with self.assertRaises(PublisherError):
            make_proposal(contract=dict(BASE, task_id="not-a-safe-id"))
        with self.assertRaises(PublisherError):
            make_proposal(contract=dict(BASE, base_sha="not-a-sha"))
        with self.assertRaises(PublisherError):
            make_proposal(contract=dict(BASE, allowed_paths=["scripts/autonomous_pipeline.py"]))

        artifact = valid_artifact()
        artifact["task_id"] = "eng-other-001"
        artifact["evidence_digest"] = recompute_evidence_digest(artifact)
        with self.assertRaisesRegex(PublisherError, "task identity mismatch"):
            make_proposal(verification_artifact=artifact)

    def test_existing_prs_must_be_well_formed(self):
        with self.assertRaises(PublisherError):
            make_proposal(existing_prs="not-a-list")
        with self.assertRaises(PublisherError):
            make_proposal(existing_prs=[None])


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.proposal = make_proposal()

    def test_no_open_pr_proposes_creation(self):
        result = reconcile_draft_pr(self.proposal, [])
        self.assertEqual(result["status"], "create_draft_proposal")
        self.assertIsNone(result["matched_pr_number"])
        self.assertFalse(result["draft_pr_created"])
        self.assertEqual(reconcile_draft_pr(self.proposal, []), result)

    def test_exact_digest_duplicate_is_idempotent(self):
        pr = matching_pr(self.proposal["proposal_digest"])
        result = reconcile_draft_pr(self.proposal, [pr])
        self.assertEqual(result["status"], "already_open_same_digest")
        self.assertEqual(result["matched_pr_number"], 7)

        body_pr = dict(pr, body=f"notes\nproposal_digest: {self.proposal['proposal_digest']}\n")
        self.assertEqual(reconcile_draft_pr(self.proposal, [body_pr]), result)

    def test_older_digest_draft_proposes_update(self):
        pr = matching_pr("f" * 64)
        result = reconcile_draft_pr(self.proposal, [pr])
        self.assertEqual(result["status"], "needs_update_proposal")

    def test_ambiguous_or_conflicting_states_fail_closed(self):
        digest = self.proposal["proposal_digest"]
        cases = [
            [matching_pr(digest), matching_pr(digest, number=8)],
            [matching_pr(digest, baseRefName="release")],
            [matching_pr(digest, isDraft=False)],
            [matching_pr(digest, body="no digest marker")],
            [matching_pr(digest, number=0)],
        ]
        for open_prs in cases:
            with self.subTest(open_prs=open_prs):
                with self.assertRaises(PublisherError):
                    reconcile_draft_pr(self.proposal, open_prs)

    def test_unrelated_prs_are_ignored(self):
        unrelated = {"number": 9, "headRefName": "feature/other",
                     "baseRefName": "main", "isDraft": True}
        self.assertEqual(reconcile_draft_pr(self.proposal, [unrelated])["status"],
                         "create_draft_proposal")

    def test_tampered_proposal_is_rejected_before_reconciliation(self):
        with self.assertRaises(PublisherError):
            reconcile_draft_pr(dict(self.proposal, publication_enabled=True), [])

    def test_uncertain_response_never_authorizes_retry(self):
        self.assertEqual(classify_publish_response(None), "uncertain")
        self.assertEqual(classify_publish_response({}), "uncertain")
        self.assertEqual(classify_publish_response({"status": "maybe"}), "uncertain")
        self.assertEqual(classify_publish_response({"status": "created", "reconciled": False}),
                         "uncertain")
        self.assertEqual(classify_publish_response({"status": "published"}), "published")
        self.assertEqual(classify_publish_response({"reconciled": True}), "reconciled")


class PublisherPurityTests(unittest.TestCase):
    def test_module_has_no_network_or_write_capabilities(self):
        source = (ROOT / "scripts" / "engineering_publisher.py").read_text(encoding="utf-8")
        for forbidden in ("subprocess", "requests", "urllib", "os.environ", "gh ", "git "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_no_production_script_imports_the_publisher(self):
        imports = []
        for path in (ROOT / "scripts").glob("*.py"):
            if path.name == "engineering_publisher.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "engineering_publisher" in text:
                imports.append(path.name)
        self.assertEqual(imports, [])


if __name__ == "__main__":
    unittest.main()
