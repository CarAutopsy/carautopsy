"""Tests for verified Hive owner-digest snapshot selection."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import hive_owner_digest_snapshot as snapshot


class HiveOwnerDigestSnapshotTests(unittest.TestCase):
    def test_only_final_git_trailer_block_is_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            digest = "a" * 64
            body_only = (
                "commit subject\n\n"
                f"{snapshot.DIGEST_TRAILER}: {digest}\n\n"
                "This is a later ordinary body paragraph, not a trailer block.\n"
            ).encode("utf-8")
            self.assertIsNone(snapshot.final_trailer(root, body_only, snapshot.DIGEST_TRAILER))

            final = (
                "commit subject\n\n"
                "A body paragraph.\n\n"
                f"{snapshot.DIGEST_TRAILER}: {digest}\n"
            ).encode("utf-8")
            self.assertEqual(
                snapshot.final_trailer(root, final, snapshot.DIGEST_TRAILER),
                digest,
            )

    @patch("scripts.hive_owner_digest_snapshot.subprocess.run")
    def test_non_main_checkout_is_rejected_before_snapshot_selection(self, run):
        run.return_value = subprocess.CompletedProcess(
            ["git", "branch", "--show-current"],
            0,
            stdout=b"feature/test-branch\\n",
            stderr=b"",
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(snapshot.SnapshotError):
                snapshot.select_snapshot(Path(directory))
        run.assert_called_once()

    def test_duplicate_final_digest_trailers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            message = (
                "subject\n\n"
                f"{snapshot.DIGEST_TRAILER}: {'a' * 64}\n"
                f"{snapshot.DIGEST_TRAILER}: {'b' * 64}\n"
            ).encode("utf-8")
            self.assertIsNone(snapshot.final_trailer(root, message, snapshot.DIGEST_TRAILER))


if __name__ == "__main__":
    unittest.main()
