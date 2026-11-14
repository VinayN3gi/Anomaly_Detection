"""Unit and integration tests for synthetic dataset generation."""

from pathlib import Path
import pandas as pd
import pytest

from src.data_generator import (
    REQUIRED_COLUMNS,
    VALID_ANOMALY_TYPES,
    generate_infrastructure_dataset,
    save_dataset,
)


@pytest.fixture(scope="module")
def default_dataset() -> pd.DataFrame:
    """Generate a 10,000 record dataset once for this test module."""
    return generate_infrastructure_dataset(num_records=10000, random_seed=42)


class TestDataGenerator:
    """Validate data generation logic, bounds, schemas, and reproducibility."""

    def test_dataset_generation_returns_dataframe(
        self, default_dataset: pd.DataFrame
    ) -> None:
        """Verify return type is a pandas DataFrame."""
        assert isinstance(default_dataset, pd.DataFrame)

    def test_record_count(self, default_dataset: pd.DataFrame) -> None:
        """Verify dataset contains exactly 10,000 rows."""
        assert len(default_dataset) == 10000

    def test_required_columns_exist(self, default_dataset: pd.DataFrame) -> None:
        """Verify all mandatory columns are present with expected names."""
        for col in REQUIRED_COLUMNS:
            assert col in default_dataset.columns, f"Missing required column: {col}"
        assert list(default_dataset.columns) == REQUIRED_COLUMNS

    def test_normal_and_anomalous_records_exist(
        self, default_dataset: pd.DataFrame
    ) -> None:
        """Verify presence of both normal (label=0) and anomalous (label=1) rows."""
        normal_count = (default_dataset["anomaly_label"] == 0).sum()
        anom_count = (default_dataset["anomaly_label"] == 1).sum()

        assert normal_count > 0, "No normal records found"
        assert anom_count > 0, "No anomalous records found"
        assert normal_count + anom_count == len(default_dataset)

    def test_anomaly_percentage_approximately_five_percent(
        self, default_dataset: pd.DataFrame
    ) -> None:
        """Verify anomaly proportion is calibrated to approximately 5%."""
        anom_pct = (default_dataset["anomaly_label"] == 1).mean()
        assert (
            0.045 <= anom_pct <= 0.055
        ), f"Unexpected anomaly pct: {anom_pct * 100:.2f}%"

    def test_all_metrics_within_valid_bounds(
        self, default_dataset: pd.DataFrame
    ) -> None:
        """Verify metric bounds (percentages, non-negatives, positive latency)."""
        assert (default_dataset["cpu_usage"] >= 0.0).all()
        assert (default_dataset["cpu_usage"] <= 100.0).all()

        assert (default_dataset["memory_usage"] >= 0.0).all()
        assert (default_dataset["memory_usage"] <= 100.0).all()

        assert (default_dataset["disk_usage"] >= 0.0).all()
        assert (default_dataset["disk_usage"] <= 100.0).all()

        assert (default_dataset["network_in"] >= 0.0).all()
        assert (default_dataset["network_out"] >= 0.0).all()

        assert (default_dataset["request_count"] >= 0).all()
        assert (default_dataset["response_time"] > 0.0).all()

    def test_no_duplicate_timestamps(self, default_dataset: pd.DataFrame) -> None:
        """Verify strictly unique timestamps."""
        assert default_dataset["timestamp"].duplicated().sum() == 0

    def test_timestamps_monotonic_increasing(
        self, default_dataset: pd.DataFrame
    ) -> None:
        """Verify timestamps advance sequentially."""
        ts_series = pd.to_datetime(default_dataset["timestamp"])
        assert ts_series.is_monotonic_increasing

    def test_no_missing_values(self, default_dataset: pd.DataFrame) -> None:
        """Verify complete null-free dataset."""
        assert default_dataset.isna().sum().sum() == 0

    def test_anomaly_categories_valid(self, default_dataset: pd.DataFrame) -> None:
        """Verify all anomaly types match recognized categories."""
        unique_types = set(default_dataset["anomaly_type"].unique())
        assert unique_types.issubset(set(VALID_ANOMALY_TYPES))
        for expected_type in VALID_ANOMALY_TYPES:
            assert expected_type in unique_types, (
                f"Missing category: {expected_type}"
            )

    def test_anomaly_labels_consistency(self, default_dataset: pd.DataFrame) -> None:
        """Verify strict bijection between label 0 and normal type."""
        normal_mask = default_dataset["anomaly_type"] == "normal"
        label_zero_mask = default_dataset["anomaly_label"] == 0
        assert (normal_mask == label_zero_mask).all()

        anom_mask = default_dataset["anomaly_type"] != "normal"
        label_one_mask = default_dataset["anomaly_label"] == 1
        assert (anom_mask == label_one_mask).all()

    def test_reproducibility_with_same_random_seed(self) -> None:
        """Verify identical seed produces strictly identical DataFrame values."""
        df1 = generate_infrastructure_dataset(num_records=500, random_seed=123)
        df2 = generate_infrastructure_dataset(num_records=500, random_seed=123)
        pd.testing.assert_frame_equal(df1, df2)

    def test_different_seeds_produce_different_values(self) -> None:
        """Verify different random seeds yield different numeric values."""
        df1 = generate_infrastructure_dataset(num_records=500, random_seed=42)
        df2 = generate_infrastructure_dataset(num_records=500, random_seed=99)
        assert not df1["cpu_usage"].equals(df2["cpu_usage"])
        assert not df1["network_in"].equals(df2["network_in"])

    def test_save_dataset_functionality(
        self, tmp_path: Path, default_dataset: pd.DataFrame
    ) -> None:
        """Verify save_dataset creates files and can be read back."""
        main_file = tmp_path / "test_main.csv"
        sample_file = tmp_path / "test_sample.csv"
        summary_file = tmp_path / "test_summary.txt"

        save_dataset(
            df=default_dataset,
            file_path=main_file,
            sample_path=sample_file,
            summary_path=summary_file,
            sample_size=50,
        )

        assert main_file.exists()
        assert sample_file.exists()
        assert summary_file.exists()

        loaded_sample = pd.read_csv(sample_file)
        assert len(loaded_sample) == 50
        assert list(loaded_sample.columns) == REQUIRED_COLUMNS
