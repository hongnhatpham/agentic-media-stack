from __future__ import annotations

import re
from collections.abc import Iterable

from .adapters import normalise_title
from .models import Download, Match, MediaCandidate, MediaKind, Provenance


def _numbers(name: str) -> tuple[int | None, int | None, int | None]:
    season = episode = year = None
    match = re.search(r"[Ss](\d{1,2})[ ._-]*[Ee](\d{1,3})", name)
    if match:
        season, episode = int(match.group(1)), int(match.group(2))
    year_match = re.search(r"(?:^|[^0-9])(19\d{2}|20\d{2})(?:[^0-9]|$)", name)
    if year_match:
        year = int(year_match.group(1))
    return season, episode, year


def score(download: Download, candidate: MediaCandidate) -> tuple[float, tuple[str, ...]]:
    download_tokens = set(normalise_title(download.name))
    title_tokens = set(normalise_title(candidate.title))
    if not title_tokens:
        return 0.0, ("candidate has no title tokens",)
    overlap = len(download_tokens & title_tokens) / len(title_tokens)
    score_value = overlap * 0.70
    reasons: list[str] = [f"title token overlap {overlap:.2f}"]
    season, episode, year = _numbers(download.name)
    if candidate.season is not None and season == candidate.season:
        score_value += 0.15
        reasons.append("season marker matches")
    elif candidate.season is not None and season is not None:
        score_value -= 0.20
        reasons.append("season marker conflicts")
    if candidate.episode is not None and episode == candidate.episode:
        score_value += 0.10
        reasons.append("episode marker matches")
    elif candidate.episode is not None and episode is not None:
        score_value -= 0.10
        reasons.append("episode marker conflicts")
    if candidate.year is not None and year == candidate.year:
        score_value += 0.10
        reasons.append("year matches")
    elif candidate.year is not None and year is not None:
        score_value -= 0.10
        reasons.append("year conflicts")
    if candidate.kind == MediaKind.MOVIE and season is None and episode is None:
        score_value += 0.05
        reasons.append("movie-shaped filename")
    return max(0.0, min(score_value, 1.0)), tuple(reasons)


def find_matches(
    download: Download, candidates: Iterable[MediaCandidate], *, minimum: float = 0.25
) -> list[Match]:
    provenance = Provenance(
        download.id, download.source, download.client, download.path, download.completed_at
    )
    matches: list[Match] = []
    for candidate in candidates:
        value, reasons = score(download, candidate)
        if value >= minimum:
            matches.append(Match(download, candidate, provenance, value, reasons))
    return sorted(matches, key=lambda item: item.score, reverse=True)
