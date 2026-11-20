"""Offline tests for the fail-closed TCO publication guard (issue #129)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tco_publication import (  # noqa: E402
    PUBLICATION_PATH,
    PublicationBlocked,
    assert_attestation,
    assert_only_publication_paths_changed,
    assert_publication_gate,
    build_attestation,
    build_run_url,
    canonical_bytes,
    catalog_digest,
    country_pack_digest,
    classify_publication_response,
    draft_publication_proposal,
    is_duplicate_publication,
    parse_status_paths,
    publication_needs_refresh,
)


SHA = "a" * 40
DIGEST = "b" * 64
PAYLOAD = {"results": [{"variant_id": "synthetic.at.bev.model-x"}], "summary": {"variants": 1}}
ATTESTATION = build_attestation(
    payload=PAYLOAD,
    base_sha=SHA,
    catalog_sha256=DIGEST,
    country_pack="AT@2026.1",
    country_pack_sha256="d" * 64,
    engine_version="1.0.0",
    run_url="https://github.com/CarAutopsy/carautopsy/actions/runs/1",
)


class TcoPublicationGuardTests(unittest.TestCase):
    def test_catalog_digest_is_deterministic_and_content_bound(self):
        with self.assertRaises(PublicationBlocked):
            catalog_digest(ROOT / "does-not-exist")

        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            variants = root / "catalog" / "variants"
            variants.mkdir(parents=True)
            (variants / "a.json").write_text('{"x": 1}', encoding="utf-8")
            first = catalog_digest(root)
            self.assertEqual(first, catalog_digest(root))
            (variants / "b.json").write_text('{"y": 2}', encoding="utf-8")
            self.assertNotEqual(first, catalog_digest(root))

    def test_attestation_binds_payload_and_rejects_bad_inputs(self):
        self.assertEqual(
            ATTESTATION["payload_sha256"],
            hashlib.sha256(canonical_bytes(PAYLOAD)).hexdigest(),
        )
        changed = dict(PAYLOAD, summary={"variants": 2})
        other = build_attestation(
            payload=changed, base_sha=SHA, catalog_sha256=DIGEST,
            country_pack="AT@2026.1", country_pack_sha256="d" * 64,
            engine_version="1.0.0",
        )
        self.assertNotEqual(ATTESTATION["payload_sha256"], other["payload_sha256"])
        for kwargs in (
            {"base_sha": "not-a-sha"},
            {"catalog_sha256": "xyz"},
            {"country_pack": ""},
            {"engine_version": 3},
            {"run_url": 5},
        ):
            with self.subTest(kwargs=kwargs):
                values = dict(
                    payload=PAYLOAD, base_sha=SHA, catalog_sha256=DIGEST,
                    country_pack="AT@2026.1", country_pack_sha256="d" * 64,
                    engine_version="1.0.0",
                )
                values.update(kwargs)
                with self.assertRaises(PublicationBlocked):
                    build_attestation(**values)

    def test_run_specific_evidence_does_not_change_binding(self):
        relaxed = dict(ATTESTATION, base_sha="c" * 40,
                       run_url="https://github.com/CarAutopsy/carautopsy/actions/runs/999")
        assert_attestation({"attestation": relaxed}, ATTESTATION)

    def test_attestation_mismatch_is_detected(self):
        assert_attestation({"attestation": ATTESTATION}, ATTESTATION)
        for bad in (
            {},
            {"attestation": None},
            {"attestation": dict(ATTESTATION, payload_sha256="d" * 64)},
            {"attestation": dict(ATTESTATION, catalog_sha256="e" * 64)},
            {"attestation": dict(ATTESTATION, country_pack_sha256="1" * 64)},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(PublicationBlocked):
                    assert_attestation(bad, ATTESTATION)

    def test_status_parser_handles_quoted_and_renamed_paths(self):
        status = (
            f" M {PUBLICATION_PATH}\n?? stray.txt\n"
            f'R  "old name.json" -> "{PUBLICATION_PATH}"\n'
        )
        self.assertEqual(
            parse_status_paths(status),
            [PUBLICATION_PATH, "stray.txt", PUBLICATION_PATH],
        )

    def test_only_explicit_publication_path_may_change(self):
        self.assertEqual(
            assert_only_publication_paths_changed(f"M  {PUBLICATION_PATH}\n"),
            [PUBLICATION_PATH],
        )
        for status in (
            f"M  {PUBLICATION_PATH}\n?? unrelated.txt\n",
            "M  tasks/queue.json\n",
            "A  secrets.txt\n",
        ):
            with self.subTest(status=status):
                with self.assertRaisesRegex(PublicationBlocked, "unrelated working-tree changes"):
                    assert_only_publication_paths_changed(status)

    def test_publication_gate_blocks_before_writes(self):
        with self.assertRaisesRegex(PublicationBlocked, "audit failures prevent publication"):
            assert_publication_gate(
                audit_failures=1,
                status_output=f"M  {PUBLICATION_PATH}\n",
                attestation=ATTESTATION,
                expected_attestation=ATTESTATION,
            )
        with self.assertRaises(PublicationBlocked):
            assert_publication_gate(
                audit_failures=0,
                status_output=f"M  {PUBLICATION_PATH}\nM  tasks/queue.json\n",
                attestation=ATTESTATION,
                expected_attestation=ATTESTATION,
            )
        with self.assertRaises(PublicationBlocked):
            assert_publication_gate(
                audit_failures=-1,
                status_output="",
                attestation=ATTESTATION,
                expected_attestation=ATTESTATION,
            )

    def test_draft_publication_proposal_never_enables_publication(self):
        proposal = draft_publication_proposal(base_sha=SHA, attestation=ATTESTATION)
        self.assertTrue(proposal["requires_owner_approval"])
        self.assertFalse(proposal["draft_pr_created"])
        self.assertFalse(proposal["direct_main_push"])
        approved = draft_publication_proposal(
            base_sha=SHA, attestation=ATTESTATION, owner_approved=True
        )
        self.assertTrue(approved["owner_approved"])
        self.assertFalse(approved["publication_enabled"])

    def test_script_uses_guard_and_has_no_direct_main_write(self):
        source = (ROOT / "scripts" / "autonomous_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("assert_publication_gate", source)
        self.assertIn("draft_publication_proposal", source)
        self.assertNotIn('"-A"', source)
        self.assertNotIn('push", "origin", "main"', source)
        self.assertLess(
            source.index("publication blocked before writes"),
            source.index("json.dumps(published"),
        )


class TcoPublicationSecurityRegressionTests(unittest.TestCase):
    """Phase 2 proof list for issue #129 (offline, mocked only)."""

    def test_no_duplicate_publication_when_inputs_unchanged(self):
        existing = {"results": PAYLOAD["results"], "attestation": ATTESTATION}
        self.assertTrue(is_duplicate_publication(existing, ATTESTATION))
        same_payload_new_head = dict(ATTESTATION, base_sha="c" * 40)
        self.assertTrue(is_duplicate_publication(existing, same_payload_new_head))
        changed_payload = dict(ATTESTATION, payload_sha256="f" * 64)
        self.assertFalse(is_duplicate_publication(existing, changed_payload))
        changed_catalog = dict(ATTESTATION, catalog_sha256="e" * 64)
        self.assertFalse(is_duplicate_publication(existing, changed_catalog))
        changed_pack = dict(ATTESTATION, country_pack_sha256="1" * 64)
        self.assertFalse(is_duplicate_publication(existing, changed_pack))
        self.assertFalse(is_duplicate_publication({}, ATTESTATION))

    def test_unchanged_inputs_do_not_rewrite_on_new_head_or_run(self):
        envelope = {"country_pack": "AT@2026.1", "engine_version": "1.0.0",
                    "generated_utc": "2026-11-20T12:00:00Z"}
        payload = dict(PAYLOAD, envelope=envelope)
        new_evidence = dict(ATTESTATION, base_sha="c" * 40,
                            run_url="https://github.com/CarAutopsy/carautopsy/actions/runs/999")
        existing = {"results": payload["results"], "summary": payload["summary"],
                    "envelope": envelope, "attestation": new_evidence}
        self.assertTrue(is_duplicate_publication(existing, new_evidence))
        self.assertFalse(publication_needs_refresh(existing, payload, new_evidence))
        assert_attestation(existing, new_evidence)

    def test_changed_input_binding_forces_refresh_and_blocks_stale_artifact(self):
        envelope = {"country_pack": "AT@2026.1", "engine_version": "1.0.0",
                    "generated_utc": "2026-11-20T12:00:00Z"}
        payload = dict(PAYLOAD, envelope=envelope)
        stale = {"results": payload["results"], "summary": payload["summary"],
                 "envelope": envelope,
                 "attestation": dict(ATTESTATION, catalog_sha256="e" * 64)}
        self.assertTrue(publication_needs_refresh(stale, payload, ATTESTATION))
        with self.assertRaises(PublicationBlocked):
            assert_attestation(stale, ATTESTATION)

    def test_engine_import_is_local_and_pack_digest_is_bounded(self):
        source = (ROOT / "scripts" / "tco_publication.py").read_text(encoding="utf-8")
        self.assertNotIn("\nfrom tco_engine import", source)
        self.assertIn("    from tco_engine import publication_artifact_is_current", source)
        self.assertIn("MAX_PACK_FILES", source)
        self.assertIn("not path.is_symlink()", source)

    def test_run_url_builder_is_pure_and_bounded(self):
        self.assertEqual(
            build_run_url("https://github.com", "CarAutopsy/carautopsy", "123"),
            "https://github.com/CarAutopsy/carautopsy/actions/runs/123",
        )
        self.assertEqual(
            build_run_url("https://github.com/", "CarAutopsy/carautopsy", "123"),
            "https://github.com/CarAutopsy/carautopsy/actions/runs/123",
        )
        for args in (
            ("http://github.com", "CarAutopsy/carautopsy", "123"),
            ("https://github.com", "../repo", "123"),
            ("https://github.com", "CarAutopsy/carautopsy", "not-a-number"),
            (None, "CarAutopsy/carautopsy", "123"),
        ):
            with self.subTest(args=args):
                self.assertIsNone(build_run_url(*args))

    def test_uncertain_response_never_authorizes_retry(self):
        self.assertEqual(classify_publication_response(None), "uncertain")
        self.assertEqual(classify_publication_response({}), "uncertain")
        self.assertEqual(classify_publication_response({"status": "maybe"}), "uncertain")
        self.assertEqual(classify_publication_response({"status": "created", "reconciled": False}), "uncertain")
        self.assertEqual(classify_publication_response({"status": "published"}), "published")
        self.assertEqual(classify_publication_response({"reconciled": True}), "reconciled")
        proposal = draft_publication_proposal(base_sha=SHA, attestation=ATTESTATION)
        self.assertNotIn("retry", proposal)
        self.assertFalse(proposal["direct_main_push"])

    def test_publication_module_has_no_secrets_or_environment_access(self):
        source = (ROOT / "scripts" / "tco_publication.py").read_text(encoding="utf-8")
        self.assertNotIn("secrets.", source)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("requests", source)

    def test_workflow_has_no_scheduled_or_research_mode_publication(self):
        import yaml

        workflow = yaml.load(
            (ROOT / ".github" / "workflows" / "autonomous-pipeline.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        run_job = workflow["jobs"]["run"]
        tco = next(step for step in run_job["steps"] if step.get("name") == "Gated TCO pipeline")
        self.assertIn("workflow_dispatch", tco["if"])
        self.assertIn("'full'", tco["if"])
        self.assertNotIn("schedule", tco["if"])
        self.assertNotIn("research-only", tco["if"])

    def test_research_only_path_exits_before_publication_block(self):
        source = (ROOT / "scripts" / "autonomous_pipeline.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index("Research cycle completed successfully"),
            source.index("Fail-closed TCO publication"),
        )

    def test_audit_failure_exits_before_any_publication_write(self):
        source = (ROOT / "scripts" / "autonomous_pipeline.py").read_text(encoding="utf-8")
        failure = source.index("publication blocked before writes")
        for marker in ("build_attestation(", "json.dumps(published", "assert_publication_gate("):
            with self.subTest(marker=marker):
                self.assertLess(failure, source.index(marker))


    def test_country_pack_rules_are_bound_into_attestation(self):
        digest = country_pack_digest(ROOT)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, country_pack_digest(ROOT))
        attestation = dict(ATTESTATION, country_pack_sha256=digest)
        self.assertEqual(attestation["country_pack_sha256"], digest)
        with self.assertRaises(PublicationBlocked):
            build_attestation(
                payload=PAYLOAD, base_sha=SHA, catalog_sha256=DIGEST,
                country_pack="AT@2026.1", engine_version="1.0.0",
                country_pack_sha256="not-a-digest",
            )

    def test_runtime_uses_wired_helpers_and_standard_run_url(self):
        source = (ROOT / "scripts" / "autonomous_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("publication_needs_refresh(old, payload, attestation)", source)
        self.assertIn("country_pack_sha256=country_pack_digest(ROOT, country)", source)
        self.assertIn('os.environ.get("GITHUB_RUN_ID"', source)
        self.assertNotIn("GITHUB_RUN_URL", source)
        self.assertIn("status_output=post_write_status", source)
        self.assertLess(
            source.index("assert_only_publication_paths_changed(status_output)"),
            source.index("json.dumps(published"),
        )


if __name__ == "__main__":
    unittest.main()
