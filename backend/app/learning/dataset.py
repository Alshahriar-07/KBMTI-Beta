"""Dataset construction with chronological splits and leakage auditing.

Cases are immutable snapshots keyed by snapshot id. The builder never uses a label to
choose a split and never shuffles. Duplicate snapshot ids, non-increasing timestamps,
empty partitions and any test case earlier than a training case are blocking errors.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.learning.contracts import (
    DatasetAudit,
    DatasetCase,
    DatasetManifest,
    SplitName,
)


def _as_case(snapshot: dict[str, Any], split: SplitName) -> DatasetCase:
    data_as_of = snapshot.get("data_as_of")
    generated_at = snapshot.get("generated_at")
    if not data_as_of and generated_at:
        data_as_of = generated_at
    return DatasetCase(
        case_id=str(snapshot.get("snapshot_id") or snapshot.get("case_id")),
        snapshot_id=str(snapshot.get("snapshot_id") or snapshot.get("case_id")),
        data_as_of=data_as_of,
        symbol=str(snapshot.get("symbol") or "BTCUSDT"),
        timeframe=str(snapshot.get("timeframe") or "M15"),
        split=split,
        synthetic=bool(snapshot.get("synthetic", False)),
        payload={
            key: snapshot.get(key)
            for key in (
                "snapshot_id",
                "data_as_of",
                "provider",
                "feature_version",
                "validation_status",
                "last_price",
                "trend",
                "structure",
                "momentum",
                "volatility",
                "liquidity",
                "regime",
            )
            if key in snapshot
        },
    )


def _manifest_hash(cases: list[DatasetCase]) -> str:
    rows = [
        f"{case.case_id}|{case.split.value}|{case.data_as_of.isoformat()}"
        for case in sorted(cases, key=lambda item: (item.data_as_of, item.case_id))
    ]
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


class DatasetBuilder:
    def build(
        self,
        snapshots: list[dict[str, Any]],
        *,
        name: str = "market-intelligence",
        train_fraction: float = 0.6,
        validation_fraction: float = 0.2,
        purge: int = 2,
    ) -> DatasetManifest:
        ordered = sorted(snapshots, key=lambda row: str(row.get("data_as_of") or row.get("generated_at") or ""))
        total = len(ordered)
        errors: list[str] = []
        warnings: list[str] = []
        if total < 30:
            errors.append("at least 30 snapshots are required")
        if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
            errors.append("split fractions must be between 0 and 1")
        elif train_fraction + validation_fraction >= 1:
            errors.append("train + validation must leave a test slice")

        seen_ids: set[str] = set()
        duplicates = 0
        for row in ordered:
            case_id = str(row.get("snapshot_id") or "")
            if not case_id:
                errors.append("a snapshot is missing snapshot_id")
                continue
            if case_id in seen_ids:
                duplicates += 1
                errors.append(f"duplicate snapshot id {case_id}")
            seen_ids.add(case_id)
            if row.get("validation_status") not in {None, "OK"}:
                errors.append(f"snapshot {case_id} has validation_status={row.get('validation_status')}")
            if row.get("is_stale"):
                warnings.append(f"stale snapshot {case_id} included; verify its label provenance")

        gap = max(0, int(purge))
        usable = total - 2 * gap
        if usable >= 30 and not errors:
            train_end = int(usable * train_fraction)
            validation_size = int(usable * validation_fraction)
            validation_start = train_end + gap
            validation_end = validation_start + validation_size
            test_start = validation_end + gap
            splits: list[SplitName] = []
            for index in range(total):
                if index < train_end:
                    splits.append(SplitName.TRAIN)
                elif index < validation_start:
                    splits.append(SplitName.PURGED)
                elif index < validation_end:
                    splits.append(SplitName.VALIDATION)
                elif index < test_start:
                    splits.append(SplitName.PURGED)
                else:
                    splits.append(SplitName.TEST)
        else:
            splits = [SplitName.PURGED for _ in ordered]

        cases = [
            _as_case(row, split)
            for row, split in zip(ordered, splits, strict=True)
            if row.get("snapshot_id")
        ]
        train = [case for case in cases if case.split is SplitName.TRAIN]
        validation = [case for case in cases if case.split is SplitName.VALIDATION]
        test = [case for case in cases if case.split is SplitName.TEST]
        purged = [case for case in cases if case.split is SplitName.PURGED]

        if cases:
            if not train:
                errors.append("training split is empty")
            if not validation:
                errors.append("validation split is empty")
            if not test:
                errors.append("test split is empty")
            if train and test and min(case.data_as_of for case in test) <= max(case.data_as_of for case in train):
                errors.append("test data overlaps or precedes training data")
            if train and validation and min(case.data_as_of for case in validation) <= max(
                case.data_as_of for case in train
            ):
                errors.append("validation data overlaps or precedes training data")
        if len(cases) < 30:
            warnings.append("fewer than 30 cases; metrics are descriptive, not statistically conclusive")
        if duplicates:
            errors.append(f"{duplicates} duplicate snapshot id(s)")

        audit = DatasetAudit(
            valid=not errors,
            errors=list(dict.fromkeys(errors)),
            warnings=list(dict.fromkeys(warnings)),
            cases=len(cases),
            duplicates=duplicates,
            train_cases=len(train),
            validation_cases=len(validation),
            test_cases=len(test),
            purge_cases=len(purged),
        )
        now = datetime.now(UTC)
        manifest_hash = _manifest_hash(cases)
        dataset_id = f"ds_{hashlib.sha256((name + manifest_hash + now.isoformat()).encode()).hexdigest()[:20]}"
        return DatasetManifest(
            dataset_id=dataset_id,
            name=name,
            version="1.0.0",
            manifest_hash=manifest_hash,
            created_at=now,
            status="VALID" if audit.valid else "BLOCKED",
            cases=cases,
            audit=audit,
            summary={
                "splits": audit.model_dump(mode="json"),
                "feature_version": next((str(row.get("feature_version")) for row in ordered if row.get("feature_version")), None),
                "manifest_hash": manifest_hash,
                "leakage_control": "chronological split with purge gaps; no shuffling; test sealed",
                "labels": "none; market-context dataset only",
                "cost_model": "not applicable to this dataset",
            },
        )

    @staticmethod
    def manifest_json(manifest: DatasetManifest) -> str:
        return json.dumps(manifest.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)


__all__ = ["DatasetBuilder"]
