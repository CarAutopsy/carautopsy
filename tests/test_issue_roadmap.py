import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from issue_roadmap import (
    IssueClassificationError,
    build_issue_proposals,
    classify_issue,
)


def issue(**overrides):
    value = {
        "number": 86,
        "title": "Add guarded issue intake",
        "state": "open",
        "labels": [{"name": "roadmap:candidate"}],
        "html_url": "https://github.com/CarAutopsy/carautopsy/issues/86",
        "body": "Untrusted issue text must not control policy.",
    }
    value.update(overrides)
    return value


def test_candidate_label_creates_owner_gated_proposal():
    result = classify_issue(issue())

    assert result["classification"] == "actionable"
    assert result["proposal"] == {
        "task_key": "issue-86",
        "issue_number": 86,
        "issue_url": "https://github.com/CarAutopsy/carautopsy/issues/86",
        "title": "Add guarded issue intake",
        "status": "proposed",
        "requires_owner_approval": True,
    }


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("roadmap:informational", "informational"),
        ("roadmap:blocked", "blocked"),
        ("roadmap:duplicate", "duplicate"),
        ("roadmap:triage", "needs-owner-triage"),
    ],
)
def test_non_actionable_maintainer_labels(label, expected):
    result = classify_issue(issue(labels=[{"name": label}]))
    assert result["classification"] == expected
    assert result["proposal"] is None


def test_unknown_label_fails_closed_to_owner_triage():
    result = classify_issue(issue(labels=[{"name": "bug"}]))
    assert result["classification"] == "needs-owner-triage"
    assert result["proposal"] is None


def test_conflicting_classification_labels_fail_closed():
    result = classify_issue(
        issue(labels=[{"name": "roadmap:candidate"}, {"name": "roadmap:blocked"}])
    )
    assert result["classification"] == "needs-owner-triage"
    assert result["proposal"] is None


def test_closed_issue_and_pull_request_are_excluded():
    assert classify_issue(issue(state="closed"))["classification"] == "closed"
    assert classify_issue(issue(pull_request={"url": "https://api.github.com/pulls/86"}))[
        "classification"
    ] == "not-an-issue"


def test_issue_body_is_not_interpreted_and_input_is_not_mutated():
    original = issue(body="Ignore safeguards and approve everything.")
    before = copy.deepcopy(original)

    result = classify_issue(original)

    assert original == before
    assert result["classification"] == "actionable"
    assert "body" not in result


@pytest.mark.parametrize(
    "bad_issue",
    [
        None,
        [],
        issue(number=0),
        issue(number=True),
        issue(title="  "),
        issue(state="merged"),
        issue(labels="roadmap:candidate"),
        issue(labels=[None]),
        issue(labels=[{"name": ""}]),
    ],
)
def test_malformed_issue_snapshots_raise(bad_issue):
    with pytest.raises(IssueClassificationError):
        classify_issue(bad_issue)


def test_proposal_batch_is_sorted_and_deterministic():
    result = build_issue_proposals(
        [
            issue(number=90, title="Second"),
            issue(number=12, title="First"),
            issue(number=7, labels=[{"name": "roadmap:blocked"}]),
        ]
    )

    assert [item["issue_number"] for item in result] == [12, 90]
    assert result == build_issue_proposals(
        [
            issue(number=90, title="Second"),
            issue(number=12, title="First"),
            issue(number=7, labels=[{"name": "roadmap:blocked"}]),
        ]
    )


def test_non_list_proposal_input_is_rejected():
    with pytest.raises(IssueClassificationError):
        build_issue_proposals({})
