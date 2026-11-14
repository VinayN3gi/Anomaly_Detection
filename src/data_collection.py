"""Data Collection and Ingestion Module for Cloud Infrastructure Metrics.

Provides interfaces to ingest raw telemetry datasets or orchestrate
the generation of synthetic monitoring data.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import pandas as pd

from src.data_generator import generate_infrastructure_dataset
from src.data_validation import validate_dataset, ValidationReport


def collect_synthetic_metrics(
    num_records: int = 10000,
    random_seed: int = 42,
    start_time: str = "2026-03-01 00:00:00",
    instance_id: str = "i-0f8b3c4a2d1e98765",
    validate: bool = True,
) -> tuple[pd.DataFrame, ValidationReport | None]:
    """Generate and optionally validate synthetic cloud infrastructure metrics.

    Args:
        num_records: Total records to generate (default 10,000).
        random_seed: Deterministic seed.
        start_time: Starting timestamp string.
        instance_id: Simulated AWS EC2 instance identifier.
        validate: Whether to execute all validation checks on output.

    Returns:
        Tuple of (DataFrame, ValidationReport or None).
    """
    df = generate_infrastructure_dataset(
        num_records=num_records,
        random_seed=random_seed,
        start_time=start_time,
        instance_id=instance_id,
    )

    report = None
    if validate:
        report = validate_dataset(df, expected_records=num_records)
        if not report.is_valid:
            error_details = "\n".join(report.errors)
            raise ValueError(
                f"Generated synthetic dataset failed validation:\n{error_details}"
            )

    return df, report


def load_raw_metrics(file_path: Path | str) -> pd.DataFrame:
    """Load infrastructure metrics from a CSV file.

    Args:
        file_path: Path to the CSV file.

    Returns:
        DataFrame containing infrastructure metrics.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Metric dataset not found at: {p}")

    df = pd.read_csv(p)
    return df


def get_dataset_metadata(df: pd.DataFrame) -> dict[str, Any]:
    """Extract descriptive metadata and distribution metrics from DataFrame.

    Args:
        df: Input DataFrame.

    Returns:
        Dictionary of dataset statistics and parameters.
    """
    total = len(df)
    anom_count = int((df["anomaly_label"] == 1).sum()) if "anomaly_label" in df else 0
    normal_count = total - anom_count

    return {
        "record_count": total,
        "normal_count": normal_count,
        "anomalous_count": anom_count,
        "anomaly_percentage": (anom_count / total * 100) if total > 0 else 0.0,
        "columns": list(df.columns),
        "start_time": df["timestamp"].iloc[0] if total > 0 else None,
        "end_time": df["timestamp"].iloc[-1] if total > 0 else None,
        "instances": df["instance_id"].unique().tolist()
        if "instance_id" in df
        else [],
    }
