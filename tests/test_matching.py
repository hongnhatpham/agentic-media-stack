from agentic_media_stack.matching import find_matches
from agentic_media_stack.models import Download, MediaCandidate, MediaKind
from agentic_media_stack.planner import build_plan


def test_ambiguous_candidates_are_ranked():
    download = Download("x", "Chi's Sweet Home S01E01.mkv", "/x", 1, "now")
    matches = find_matches(
        download,
        [
            MediaCandidate(
                "sonarr", MediaKind.SERIES, "a", "Chi's Sweet Home", season=1, episode=1
            ),
            MediaCandidate(
                "sonarr", MediaKind.SERIES, "b", "Chi's Sweet Home", season=2, episode=1
            ),
        ],
    )
    assert matches[0].candidate.media_id == "a"
    assert matches[0].score > matches[1].score


def test_close_candidates_become_review_work():
    download = Download("x", "Chi's Sweet Home.mkv", "/x", 1, "now")
    matches = find_matches(
        download,
        [
            MediaCandidate("sonarr", MediaKind.SERIES, "a", "Chi's Sweet Home"),
            MediaCandidate("sonarr", MediaKind.SERIES, "b", "Chi's Sweet Home"),
        ],
    )
    plan = build_plan(matches)
    assert len(plan) == 1
    assert plan[0].action.value == "review"
