"""Chronological walk-forward windows with purge and embargo.

Windows are index based so they work for candles, snapshots or trade records. The final
test slice is never used to choose parameters in this project; the helper only describes
the splits and enforces that a purge/embargo gap exists between partitions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Window:
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int
    purge: int
    embargo: int

    @property
    def train_size(self) -> int:
        return max(0, self.train_end - self.train_start)

    @property
    def validation_size(self) -> int:
        return max(0, self.validation_end - self.validation_start)

    @property
    def test_size(self) -> int:
        return max(0, self.test_end - self.test_start)

    def as_dict(self) -> dict[str, int]:
        return {
            "train_start": self.train_start,
            "train_end": self.train_end,
            "validation_start": self.validation_start,
            "validation_end": self.validation_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "purge": self.purge,
            "embargo": self.embargo,
        }


def build_windows(
    total: int,
    *,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    purge: int = 0,
    embargo: int = 0,
) -> list[Window]:
    """Return one anchored walk-forward window.

    ``train + validation + test`` must consume the whole sample after removing the
    purge/embargo gaps. Indices are half-open: ``[start, end)``.
    """

    if total < 30:
        raise ValueError("at least 30 observations are required for a chronological split")
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("fractions must be between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train + validation fractions must leave a test slice")
    if purge < 0 or embargo < 0:
        raise ValueError("purge and embargo cannot be negative")
    gap = purge + embargo
    usable = total - 2 * gap
    if usable < 30:
        raise ValueError("purge/embargo leave too few observations")
    train_end = int(usable * train_fraction)
    validation_end = int(usable * (train_fraction + validation_fraction))
    validation_start = train_end + gap
    test_start = validation_end + gap
    if train_end < 10 or validation_start >= test_start or test_start >= total:
        raise ValueError("the requested split does not produce three non-empty partitions")
    return [
        Window(
            train_start=0,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
            test_start=test_start,
            test_end=total,
            purge=purge,
            embargo=embargo,
        )
    ]


__all__ = ["Window", "build_windows"]
