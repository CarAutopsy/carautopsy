import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hive_pr import select_open_research_pr


class SelectOpenResearchPrTests(unittest.TestCase):
    def test_selects_existing_hive_pr_for_same_repository(self):
        pr = {
            "number": 36,
            "headRefName": "hive/research-20261110-210927",
            "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"},
        }
        self.assertEqual(
            select_open_research_pr([pr], "CarAutopsy/carautopsy"), pr
        )

    def test_ignores_other_repositories_and_non_hive_pull_requests(self):
        other_repo = {
            "number": 10,
            "headRefName": "hive/research-elsewhere",
            "headRepository": {"nameWithOwner": "someone/else"},
        }
        ordinary = {
            "number": 11,
            "headRefName": "feature/change",
            "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"},
        }
        self.assertIsNone(
            select_open_research_pr([other_repo, ordinary], "CarAutopsy/carautopsy")
        )

    def test_no_open_hive_pr_returns_none(self):
        self.assertIsNone(select_open_research_pr([], "CarAutopsy/carautopsy"))

    def test_multiple_open_hive_prs_fail_closed(self):
        prs = [
            {"number": 1, "headRefName": "hive/research-a",
             "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"}},
            {"number": 2, "headRefName": "hive/research-b",
             "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"}},
        ]
        with self.assertRaisesRegex(RuntimeError, "multiple open Hive research PRs"):
            select_open_research_pr(prs, "CarAutopsy/carautopsy")


if __name__ == "__main__":
    unittest.main()
