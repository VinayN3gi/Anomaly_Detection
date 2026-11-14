"""Standalone CLI Dataset Generation Pipeline.

Generates, validates, persists, and visualizes synthetic cloud infrastructure
metric telemetry for AIOps anomaly detection.

Usage:
    python scripts/generate_dataset.py [--records 10000] [--seed 42]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.data_generator import (
    generate_infrastructure_dataset,
    save_dataset,
)
from src.data_validation import validate_dataset
from src.visualization import generate_all_visualizations


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate synthetic cloud infrastructure metrics dataset."
    )
    parser.add_argument(
        "--records",
        type=int,
        default=config.DEFAULT_NUM_RECORDS,
        help="Number of records to generate (default: 10,000).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=config.DEFAULT_RANDOM_SEED,
        help="Random seed for reproducibility (default: 42).",
    )
    parser.add_argument(
        "--skip-viz",
        action="store_true",
        help="Skip generating PNG visualization charts.",
    )
    return parser.parse_args()


def main() -> int:
    """Orchestrate full dataset generation, validation, and visualization."""
    args = parse_arguments()
    start_wall_time = time.time()

    print("=" * 75)
    print("  AIOPS CLOUD INFRASTRUCTURE ANOMALY DETECTION - DATASET GENERATION")
    print("=" * 75)
    print(f"Target Record Count : {args.records:,}")
    print(f"Random Seed         : {args.seed}")
    print(f"Output Directory    : {config.RAW_DATA_DIR}")
    print(f"Visualizations Dir  : {config.VISUALIZATIONS_DIR}")
    print("-" * 75)

    # 1. Ensure required directories exist
    config.ensure_directories_exist()

    # 2. Generate Dataset
    print("[1/5] Generating normal metrics and injecting anomalies...")
    gen_start = time.time()
    df = generate_infrastructure_dataset(
        num_records=args.records,
        random_seed=args.seed,
        start_time=config.DEFAULT_START_TIME,
        instance_id=config.DEFAULT_INSTANCE_ID,
    )
    gen_duration = time.time() - gen_start
    print(
        f"      -> Generated {len(df):,} records across 11 features "
        f"in {gen_duration:.2f}s."
    )

    # 3. Validate Dataset
    print("[2/5] Running comprehensive 16-point dataset validation checks...")
    report = validate_dataset(
        df=df,
        expected_records=args.records,
        target_anomaly_pct=config.DEFAULT_ANOMALY_PERCENTAGE,
    )
    if not report.is_valid:
        print("\n" + report.summary_text())
        print(
            "ERROR: Dataset validation failed! Aborting save process.",
            file=sys.stderr,
        )
        return 1

    print(
        f"      -> Validation PASSED ({report.passed_checks}/"
        f"{report.total_checks} checks)."
    )
    print(
        f"      -> Normal: {report.metrics_summary['Normal Records']:,} | "
        f"Anomalous: {report.metrics_summary['Anomalous Records']:,} "
        f"({report.metrics_summary['Anomaly Percentage']})"
    )

    # 4. Save Main CSV, Sample CSV, and Textual Summary
    print("[3/5] Persisting datasets to data/raw/...")
    main_p, samp_p, sum_p = save_dataset(
        df=df,
        file_path=config.RAW_DATA_FILE,
        sample_path=config.SAMPLE_DATA_FILE,
        summary_path=config.DATASET_SUMMARY_FILE,
        sample_size=100,
    )
    csv_mb = main_p.stat().st_size / (1024 * 1024)
    print(f"      -> Saved full CSV   : {main_p} ({csv_mb:.2f} MB)")
    print(f"      -> Saved sample CSV : {samp_p}")
    print(f"      -> Saved summary    : {sum_p}")

    # 5. Generate Exploratory Visualizations
    if not args.skip_viz:
        print("[4/5] Rendering 10 high-resolution visualization charts...")
        viz_start = time.time()
        viz_files = generate_all_visualizations(
            df=df,
            visualizations_dir=config.VISUALIZATIONS_DIR,
        )
        viz_duration = time.time() - viz_start
        print(
            f"      -> Successfully created {len(viz_files)} PNG figures "
            f"in {viz_duration:.2f}s:"
        )
        for name, path in viz_files.items():
            print(f"         * {path.name}")
    else:
        print("[4/5] Skipping visualization generation (--skip-viz supplied).")

    # 6. Print Final Completion Summary
    total_elapsed = time.time() - start_wall_time
    print("-" * 75)
    print(f"[5/5] Pipeline successfully completed in {total_elapsed:.2f}s!")
    print("=" * 75)
    print("Summary of Generated Data:")
    print(f"  - Record Count      : {len(df):,}")
    print(f"  - Start Timestamp   : {df['timestamp'].iloc[0]}")
    print(f"  - End Timestamp     : {df['timestamp'].iloc[-1]}")
    print(f"  - Instance ID       : {df['instance_id'].iloc[0]}")
    print(f"  - Anomaly Types     : {sorted(df['anomaly_type'].unique())}")
    print("=" * 75)

    return 0


if __name__ == "__main__":
    sys.exit(main())
