"""Data Validation Engine for Cloud Infrastructure Metrics.

Performs comprehensive data quality, integrity, bounding, and labeling
verifications on generated or ingested infrastructure datasets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from src.data_generator import REQUIRED_COLUMNS, VALID_ANOMALY_TYPES


@dataclass
class ValidationReport:
    """Encapsulates the result of dataset validation checks."""

    is_valid: bool
    total_checks: int
    passed_checks: int
    failed_checks: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics_summary: dict[str, Any] = field(default_factory=dict)

    def summary_text(self) -> str:
        """Render a readable multi-line validation summary."""
        status_str = "PASSED" if self.is_valid else "FAILED"
        lines = [
            "=" * 70,
            f"DATASET VALIDATION REPORT - STATUS: {status_str}",
            "=" * 70,
            f"Checks Executed   : {self.total_checks}",
            f"Checks Passed     : {self.passed_checks}",
            f"Checks Failed     : {self.failed_checks}",
            "-" * 70,
        ]

        if self.metrics_summary:
            lines.append("Metrics Summary:")
            for k, v in self.metrics_summary.items():
                lines.append(f"  - {k:<25}: {v}")
            lines.append("-" * 70)

        if self.errors:
            lines.append("Validation Failures:")
            for err in self.errors:
                lines.append(f"  [X] {err}")
            lines.append("-" * 70)

        if self.warnings:
            lines.append("Validation Warnings:")
            for warn in self.warnings:
                lines.append(f"  [!] {warn}")
            lines.append("-" * 70)

        if self.is_valid:
            lines.append("All 16 dataset integrity and quality checks passed!")
            lines.append("=" * 70)

        return "\n".join(lines)


def validate_dataset(
    df: pd.DataFrame,
    expected_records: int = 10000,
    target_anomaly_pct: float = 0.05,
    tolerance_pct: float = 0.01,
) -> ValidationReport:
    """Execute all 16 integrity and quality checks on an infrastructure dataset.

    Checks performed:
    1. Total record count equals expected.
    2. Required columns exist.
    3. No duplicate timestamps exist.
    4. Timestamps are sorted correctly (monotonic increasing).
    5. No missing values exist across any column.
    6. CPU utilization is strictly within [0.0, 100.0].
    7. Memory utilization is strictly within [0.0, 100.0].
    8. Disk utilization is strictly within [0.0, 100.0].
    9. Network metrics (network_in, network_out) are non-negative.
    10. Request counts are non-negative integers.
    11. Response times are strictly positive (> 0.0).
    12. anomaly_label contains only binary values {0, 1}.
    13. anomaly_type contains only recognized valid categories.
    14. Normal records strictly adhere to label=0 and type='normal'.
    15. Anomalous records strictly adhere to label=1 and type!='normal'.
    16. Anomaly percentage is approximately target_anomaly_pct.

    Args:
        df: Input DataFrame.
        expected_records: Expected total row count.
        target_anomaly_pct: Target anomaly proportion (default 0.05).
        tolerance_pct: Acceptable variation from target anomaly proportion.

    Returns:
        ValidationReport instance containing detailed check outcomes.
    """
    errors: list[str] = []
    warnings: list[str] = []
    total_checks = 16
    passed_checks = 0

    # Check 1: Record count
    actual_records = len(df)
    if actual_records == expected_records:
        passed_checks += 1
    else:
        errors.append(
            f"Check 1 Failed: Expected {expected_records} records, "
            f"found {actual_records}."
        )

    # Check 2: Required columns exist
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if not missing_cols:
        passed_checks += 1
    else:
        errors.append(
            f"Check 2 Failed: Missing required columns: {missing_cols}"
        )

    # Check 3: Duplicate timestamps
    if "timestamp" in df.columns:
        dup_count = int(df["timestamp"].duplicated().sum())
        if dup_count == 0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 3 Failed: Found {dup_count} duplicate timestamps."
            )
    else:
        errors.append("Check 3 Failed: Cannot verify duplicates (timestamp missing).")

    # Check 4: Timestamps sorted correctly
    if "timestamp" in df.columns:
        ts_series = pd.to_datetime(df["timestamp"])
        if ts_series.is_monotonic_increasing:
            passed_checks += 1
        else:
            errors.append(
                "Check 4 Failed: Timestamps are not monotonically increasing."
            )
    else:
        errors.append("Check 4 Failed: Cannot check sorting (timestamp missing).")

    # Check 5: No missing values
    null_counts = df.isna().sum().sum()
    if null_counts == 0:
        passed_checks += 1
    else:
        errors.append(
            f"Check 5 Failed: Found {null_counts} missing/null values."
        )

    # Check 6: CPU utilization in [0, 100]
    if "cpu_usage" in df.columns:
        cpu_min, cpu_max = df["cpu_usage"].min(), df["cpu_usage"].max()
        if 0.0 <= cpu_min and cpu_max <= 100.0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 6 Failed: CPU usage out of bounds [0, 100]: "
                f"min={cpu_min}, max={cpu_max}."
            )
    else:
        errors.append("Check 6 Failed: cpu_usage column missing.")

    # Check 7: Memory utilization in [0, 100]
    if "memory_usage" in df.columns:
        mem_min, mem_max = df["memory_usage"].min(), df["memory_usage"].max()
        if 0.0 <= mem_min and mem_max <= 100.0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 7 Failed: Memory usage out of bounds [0, 100]: "
                f"min={mem_min}, max={mem_max}."
            )
    else:
        errors.append("Check 7 Failed: memory_usage column missing.")

    # Check 8: Disk utilization in [0, 100]
    if "disk_usage" in df.columns:
        disk_min, disk_max = df["disk_usage"].min(), df["disk_usage"].max()
        if 0.0 <= disk_min and disk_max <= 100.0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 8 Failed: Disk usage out of bounds [0, 100]: "
                f"min={disk_min}, max={disk_max}."
            )
    else:
        errors.append("Check 8 Failed: disk_usage column missing.")

    # Check 9: Network metrics are non-negative
    if "network_in" in df.columns and "network_out" in df.columns:
        net_in_min = df["network_in"].min()
        net_out_min = df["network_out"].min()
        if net_in_min >= 0.0 and net_out_min >= 0.0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 9 Failed: Negative network values found: "
                f"network_in min={net_in_min}, network_out min={net_out_min}."
            )
    else:
        errors.append("Check 9 Failed: network columns missing.")

    # Check 10: Request counts are non-negative
    if "request_count" in df.columns:
        req_min = df["request_count"].min()
        if req_min >= 0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 10 Failed: Negative request count found: min={req_min}."
            )
    else:
        errors.append("Check 10 Failed: request_count column missing.")

    # Check 11: Response times are strictly positive
    if "response_time" in df.columns:
        rt_min = df["response_time"].min()
        if rt_min > 0.0:
            passed_checks += 1
        else:
            errors.append(
                f"Check 11 Failed: Non-positive response time: min={rt_min}."
            )
    else:
        errors.append("Check 11 Failed: response_time column missing.")

    # Check 12: anomaly_label contains only binary {0, 1}
    if "anomaly_label" in df.columns:
        unique_labels = set(df["anomaly_label"].unique())
        if unique_labels.issubset({0, 1}):
            passed_checks += 1
        else:
            errors.append(
                f"Check 12 Failed: Invalid anomaly_label values: {unique_labels}."
            )
    else:
        errors.append("Check 12 Failed: anomaly_label column missing.")

    # Check 13: anomaly_type contains valid categories
    if "anomaly_type" in df.columns:
        unique_types = set(df["anomaly_type"].unique())
        invalid_types = unique_types - set(VALID_ANOMALY_TYPES)
        if not invalid_types:
            passed_checks += 1
        else:
            errors.append(
                f"Check 13 Failed: Unrecognized anomaly_type categories: "
                f"{invalid_types}."
            )
    else:
        errors.append("Check 13 Failed: anomaly_type column missing.")

    # Check 14: Normal records have label=0 and type='normal'
    if "anomaly_label" in df.columns and "anomaly_type" in df.columns:
        normal_mask = df["anomaly_type"] == "normal"
        label_zero_mask = df["anomaly_label"] == 0
        if (normal_mask == label_zero_mask).all():
            passed_checks += 1
        else:
            mismatches = int((normal_mask != label_zero_mask).sum())
            errors.append(
                f"Check 14 Failed: Found {mismatches} records with mismatched "
                f"normal label and type."
            )
    else:
        errors.append("Check 14 Failed: label or type column missing.")

    # Check 15: Anomalous records have label=1 and type!='normal'
    if "anomaly_label" in df.columns and "anomaly_type" in df.columns:
        anom_mask = df["anomaly_label"] == 1
        non_normal_mask = df["anomaly_type"] != "normal"
        if (anom_mask == non_normal_mask).all():
            passed_checks += 1
        else:
            mismatches = int((anom_mask != non_normal_mask).sum())
            errors.append(
                f"Check 15 Failed: Found {mismatches} records with mismatched "
                f"anomaly label and non-normal type."
            )
    else:
        errors.append("Check 15 Failed: label or type column missing.")

    # Check 16: Anomaly percentage approximately target (within tolerance)
    if "anomaly_label" in df.columns and actual_records > 0:
        actual_anom_count = int((df["anomaly_label"] == 1).sum())
        actual_anom_pct = actual_anom_count / actual_records
        min_allowed = target_anomaly_pct - tolerance_pct
        max_allowed = target_anomaly_pct + tolerance_pct

        if min_allowed <= actual_anom_pct <= max_allowed:
            passed_checks += 1
        else:
            errors.append(
                f"Check 16 Failed: Anomaly percentage {actual_anom_pct * 100:.2f}% "
                f"outside target range [{min_allowed * 100:.2f}%, "
                f"{max_allowed * 100:.2f}%]."
            )
    else:
        errors.append("Check 16 Failed: Cannot compute anomaly percentage.")

    failed_checks = total_checks - passed_checks
    is_valid = len(errors) == 0

    metrics_summary: dict[str, Any] = {
        "Total Records": actual_records,
        "Normal Records": int((df["anomaly_label"] == 0).sum())
        if "anomaly_label" in df.columns
        else 0,
        "Anomalous Records": int((df["anomaly_label"] == 1).sum())
        if "anomaly_label" in df.columns
        else 0,
        "Anomaly Percentage": f"{(df['anomaly_label'] == 1).mean() * 100:.2f}%"
        if "anomaly_label" in df.columns and actual_records > 0
        else "N/A",
    }

    return ValidationReport(
        is_valid=is_valid,
        total_checks=total_checks,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        errors=errors,
        warnings=warnings,
        metrics_summary=metrics_summary,
    )

