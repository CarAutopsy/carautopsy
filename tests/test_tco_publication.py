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
    canonical_bytes,
    catalog_digest,
    draft_publication_proposal,
    parse_status_paths,
)


SHA = "a" * 40
DIGEST = "b" * 64
PAYLOAD = {"results": [{"variant_id": "synthetic.at.bev.model-x"}], "summary": {"variants": 1}}
ATTESTATION = build_attestation(
    payload=PAYLOAD,
    base_sha=SHA,
    catalog_sha256=DIGEST,
    country_pack="AT@2026.1",
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
            country_pack="AT@2026.1", engine_version="1.0.0",
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
                    country_pack="AT@2026.1", engine_version="1.0.0",
                )
                values.update(kwargs)
                with self.assertRaises(PublicationBlocked):
                    build_attestation(**values)

    def test_attestation_mismatch_is_detected(self):
        assert_attestation({"attestation": ATTESTATION}, ATTESTATION)
        for bad in (
            {},
            {"attestation": None},
            {"attestation": dict(ATTESTATION, base_sha="c" * 40)},
            {"attestation": dict(ATTESTATION, payload_sha256="d" * 64)},
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


if __name__ == "__main__":
    unittest.main()
