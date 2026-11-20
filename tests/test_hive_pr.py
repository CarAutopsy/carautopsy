import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hive_pr import MAX_FETCH_LIMIT, fetch_all_open_pull_requests, select_open_research_pr


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

    def test_fetches_beyond_first_result_window_before_selecting(self):
        first_window = [
            {"number": number, "headRefName": f"feature/{number}",
             "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"}}
            for number in range(100)
        ]
        older_hive_pr = {
            "number": 36,
            "headRefName": "hive/research-20261110-210927",
            "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"},
        }
        limits = []

        def fetch_page(limit):
            limits.append(limit)
            return first_window if limit == 100 else first_window + [older_hive_pr]

        complete = fetch_all_open_pull_requests(fetch_page)
        self.assertEqual(limits, [100, 200])
        self.assertEqual(
            select_open_research_pr(complete, "CarAutopsy/carautopsy"),
            older_hive_pr,
        )

    def test_rejects_multiple_hive_prs_even_when_one_is_beyond_first_window(self):
        first_window = [
            {"number": number, "headRefName": f"feature/{number}",
             "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"}}
            for number in range(100)
        ]
        hive_prs = [
            {"number": 36, "headRefName": "hive/research-a",
             "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"}},
            {"number": 37, "headRefName": "hive/research-b",
             "headRepository": {"nameWithOwner": "CarAutopsy/carautopsy"}},
        ]

        def fetch_page(limit):
            return first_window if limit == 100 else first_window + hive_prs

        complete = fetch_all_open_pull_requests(fetch_page)
        with self.assertRaisesRegex(RuntimeError, "multiple open Hive research PRs"):
            select_open_research_pr(complete, "CarAutopsy/carautopsy")


class BoundedOpenPrFetchTests(unittest.TestCase):
    """Regressions for the previously unbounded duplicate-PR fetch loop."""

    def test_rejects_invalid_initial_limits(self):
        for bad in (0, -1, True, "100", None, 1.5):
            with self.subTest(limit=bad):
                with self.assertRaises(ValueError):
                    fetch_all_open_pull_requests(Mock(), initial_limit=bad)

    def test_rejects_non_list_page(self):
        with self.assertRaisesRegex(RuntimeError, "must be a list"):
            fetch_all_open_pull_requests(lambda limit: {"message": "rate limited"})

    def test_full_page_at_ceiling_fails_closed_instead_of_looping(self):
        calls = []

        def full_page(limit):
            calls.append(limit)
            return [{"number": number} for number in range(limit)]

        with self.assertRaisesRegex(RuntimeError, "exceeded the .* result bound"):
            fetch_all_open_pull_requests(full_page)
        self.assertLessEqual(len(calls), 8)
        self.assertEqual(calls[-1], MAX_FETCH_LIMIT)

    def test_ceiling_is_reached_without_skipping_intermediate_limits(self):
        calls = []

        def full_page(limit):
            calls.append(limit)
            return [{"number": number} for number in range(limit)]

        with self.assertRaisesRegex(RuntimeError, "result bound"):
            fetch_all_open_pull_requests(full_page, initial_limit=750)
        self.assertEqual(calls[:2], [750, 1500])


if __name__ == "__main__":
    unittest.main()
