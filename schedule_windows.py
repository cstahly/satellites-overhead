"""Helpers for resolving single-device SDR capture window conflicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Generic, Iterable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class WindowChoice(Generic[T]):
    item: T
    start: datetime
    end: datetime
    score: tuple[float, ...]
    order: int


def windows_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def priority_score(priority: float = 0.0, max_el: float = 0.0, duration_s: float = 0.0) -> tuple[float, float, float]:
    return (float(priority or 0.0), float(max_el or 0.0), float(duration_s or 0.0))


def select_non_overlapping(
    items: Iterable[T],
    start_fn: Callable[[T], datetime],
    end_fn: Callable[[T], datetime],
    score_fn: Callable[[T], tuple[float, ...] | float],
) -> tuple[list[T], list[T]]:
    """Pick the highest-scoring item from each overlapping capture window.

    The returned selected list is sorted chronologically. Skipped items are also
    chronological so callers can log or expose conflict diagnostics if needed.
    """
    choices: list[WindowChoice[T]] = []
    for order, item in enumerate(items):
        start = start_fn(item)
        end = end_fn(item)
        if end <= start:
            continue
        raw_score = score_fn(item)
        score = tuple(float(v) for v in raw_score) if isinstance(raw_score, tuple) else (float(raw_score),)
        choices.append(WindowChoice(item=item, start=start, end=end, score=score, order=order))

    selected: list[WindowChoice[T]] = []
    skipped: list[WindowChoice[T]] = []
    ranked = sorted(
        choices,
        key=lambda choice: (tuple(-value for value in choice.score), choice.start, choice.order),
    )
    for choice in ranked:
        if any(windows_overlap(choice.start, choice.end, kept.start, kept.end) for kept in selected):
            skipped.append(choice)
        else:
            selected.append(choice)

    selected.sort(key=lambda choice: (choice.start, choice.order))
    skipped.sort(key=lambda choice: (choice.start, choice.order))
    return [choice.item for choice in selected], [choice.item for choice in skipped]


def _subtract_interval(
    segments: list[tuple[datetime, datetime]],
    blocker_start: datetime,
    blocker_end: datetime,
) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for start, end in segments:
        if not windows_overlap(start, end, blocker_start, blocker_end):
            out.append((start, end))
            continue
        if start < blocker_start:
            out.append((start, blocker_start))
        if blocker_end < end:
            out.append((blocker_end, end))
    return out


def trim_overlapping_windows(
    items: Iterable[T],
    start_fn: Callable[[T], datetime],
    end_fn: Callable[[T], datetime],
    score_fn: Callable[[T], tuple[float, ...] | float],
    trim_fn: Callable[[T, datetime, datetime, int, int], T],
    min_duration_s: int = 60,
) -> tuple[list[T], list[T]]:
    """Trim lower-priority windows around better overlaps.

    Items are considered from highest to lowest score. Higher-scoring windows
    keep their full duration; lower-scoring windows are split/trimmed to the
    remaining non-overlapping segments. Segments shorter than min_duration_s are
    discarded.
    """
    choices: list[WindowChoice[T]] = []
    for order, item in enumerate(items):
        start = start_fn(item)
        end = end_fn(item)
        if end <= start:
            continue
        raw_score = score_fn(item)
        score = tuple(float(v) for v in raw_score) if isinstance(raw_score, tuple) else (float(raw_score),)
        choices.append(WindowChoice(item=item, start=start, end=end, score=score, order=order))

    selected: list[WindowChoice[T]] = []
    skipped: list[WindowChoice[T]] = []
    ranked = sorted(
        choices,
        key=lambda choice: (tuple(-value for value in choice.score), choice.start, choice.order),
    )
    for choice in ranked:
        segments = [(choice.start, choice.end)]
        for kept in selected:
            segments = _subtract_interval(segments, kept.start, kept.end)
            if not segments:
                break
        segments = [
            (start, end)
            for start, end in segments
            if (end - start).total_seconds() >= min_duration_s
        ]
        if not segments:
            skipped.append(choice)
            continue
        part_count = len(segments)
        for idx, (start, end) in enumerate(segments, start=1):
            item = trim_fn(choice.item, start, end, idx, part_count)
            selected.append(WindowChoice(item=item, start=start, end=end, score=choice.score, order=choice.order))

    selected.sort(key=lambda choice: (choice.start, choice.order))
    skipped.sort(key=lambda choice: (choice.start, choice.order))
    return [choice.item for choice in selected], [choice.item for choice in skipped]
