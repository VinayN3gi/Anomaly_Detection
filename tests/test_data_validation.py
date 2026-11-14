"""Unit tests for the 16-point dataset validation engine."""

import pandas as pd
import pytest

from src.data_generator import generate_infrastructure_dataset
from src.data_validation import validate_dataset


@pytest.fixture(scope="module")
def valid_df() -> pd.DataFrame:
    """Provide a verified valid dataset for test mutation."""
    return generate_infrastructure_dataset(num_records=1000, random_seed=42)


class TestDataValidation:
    """Validate that validation checks catch all error modes and pass valid data."""

    def test_valid_dataset_passes_all_checks(self, valid_df: pd.DataFrame) -> None:
        """Verify pristine dataset passes with is_valid=True and 16/16 checks."""
        report = validate_dataset(valid_df, expected_records=1000)
        assert report.is_valid is True
        assert report.passed_checks == 16
        assert report.failed_checks == 0
        assert len(report.errors) == 0

    def test_record_count_mismatch_detected(self, valid_df: pd.DataFrame) -> None:
        """Verify check 1 triggers when row count differs from expected."""
        report = validate_dataset(valid_df, expected_records=5000)
        assert report.is_valid is False
        assert any("Check 1 Failed" in err for err in report.errors)

    def test_missing_column_detected(self, valid_df: pd.DataFrame) -> None:
        """Verify check 2 triggers when a mandatory column is dropped."""
        mutated = valid_df.drop(columns=["cpu_usage"])
        report = validate_dataset(mutated, expected_records=len(mutated))
        assert report.is_valid is False
        assert any("Check 2 Failed" in err for err in report.errors)

    def test_duplicate_timestamp_detected(self, valid_df: pd.DataFrame) -> None:
        """Verify check 3 triggers when timestamps are duplicated."""
        mutated = valid_df.copy()
        mutated.loc[1, "timestamp"] = mutated.loc[0, "timestamp"]
        report = validate_dataset(mutated, expected_records=len(mutated))
        assert report.is_valid is False
        assert any("Check 3 Failed" in err for err in report.errors)

    def test_unsorted_timestamp_detected(self, valid_df: pd.DataFrame) -> None:
        """Verify check 4 triggers when order is not strictly monotonic."""
        mutated = valid_df.copy()
        temp = mutated.loc[0, "timestamp"]
        mutated.loc[0, "timestamp"] = mutated.loc[10, "timestamp"]
        mutated.loc[10, "timestamp"] = temp
        report = validate_dataset(mutated, expected_records=len(mutated))
        assert report.is_valid is False
        assert any("Check 4 Failed" in err for err in report.errors)

    def test_null_value_detected(self, valid_df: pd.DataFrame) -> None:
        """Verify check 5 triggers when missing values exist."""
        mutated = valid_df.copy()
        mutated.loc[5, "memory_usage"] = None
        report = validate_dataset(mutated, expected_records=len(mutated))
        assert report.is_valid is False
        assert any("Check 5 Failed" in err for err in report.errors)

    def test_out_of_bounds_metrics_detected(self, valid_df: pd.DataFrame) -> None:
        """Verify checks 6, 7, 8 trigger on invalid utilization percentages."""
        # CPU > 100
        cpu_bad = valid_df.copy()
        cpu_bad.loc[3, "cpu_usage"] = 105.0
        rep_cpu = validate_dataset(cpu_bad, expected_records=len(cpu_bad))
        assert any("Check 6 Failed" in err for err in rep_cpu.errors)

        # Memory < 0
        mem_bad = valid_df.copy()
        mem_bad.loc[3, "memory_usage"] = -5.0
        rep_mem = validate_dataset(mem_bad, expected_records=len(mem_bad))
        assert any("Check 7 Failed" in err for err in rep_mem.errors)

        # Disk > 100
        disk_bad = valid_df.copy()
        disk_bad.loc[3, "disk_usage"] = 101.2
        rep_disk = validate_dataset(disk_bad, expected_records=len(disk_bad))
        assert any("Check 8 Failed" in err for err in rep_disk.errors)

    def test_negative_network_and_requests_detected(
        self, valid_df: pd.DataFrame
    ) -> None:
        """Verify checks 9 and 10 catch negative network and request values."""
        net_bad = valid_df.copy()
        net_bad.loc[2, "network_in"] = -10.0
        rep_net = validate_dataset(net_bad, expected_records=len(net_bad))
        assert any("Check 9 Failed" in err for err in rep_net.errors)

        req_bad = valid_df.copy()
        req_bad.loc[2, "request_count"] = -1
        rep_req = validate_dataset(req_bad, expected_records=len(req_bad))
        assert any("Check 10 Failed" in err for err in rep_req.errors)

    def test_non_positive_response_time_detected(
        self, valid_df: pd.DataFrame
    ) -> None:
        """Verify check 11 catches non-positive response times."""
        rt_bad = valid_df.copy()
        rt_bad.loc[4, "response_time"] = 0.0
        rep_rt = validate_dataset(rt_bad, expected_records=len(rt_bad))
        assert any("Check 11 Failed" in err for err in rep_rt.errors)

    def test_mismatched_anomaly_label_and_type(
        self, valid_df: pd.DataFrame
    ) -> None:
        """Verify checks 14 and 15 catch desynchronized label/type pairs."""
        # Normal type but label 1
        mismatch1 = valid_df.copy()
        normal_idx = (mismatch1["anomaly_type"] == "normal").idxmax()
        mismatch1.loc[normal_idx, "anomaly_label"] = 1
        rep1 = validate_dataset(mismatch1, expected_records=len(mismatch1))
        assert any("Check 14 Failed" in err for err in rep1.errors)

        # Spike type but label 0
        mismatch2 = valid_df.copy()
        anom_idx = (mismatch2["anomaly_type"] != "normal").idxmax()
        mismatch2.loc[anom_idx, "anomaly_label"] = 0
        rep2 = validate_dataset(mismatch2, expected_records=len(mismatch2))
        assert any("Check 15 Failed" in err for err in rep2.errors)

    def test_summary_report_text(self, valid_df: pd.DataFrame) -> None:
        """Verify formatted summary text contains key sections."""
        report = validate_dataset(valid_df, expected_records=1000)
        summary = report.summary_text()
        assert "DATASET VALIDATION REPORT - STATUS: PASSED" in summary
        assert "Checks Executed   : 16" in summary
        assert "Checks Passed     : 16" in summary
