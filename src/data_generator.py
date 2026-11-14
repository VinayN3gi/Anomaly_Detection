"""Synthetic Cloud Infrastructure Metrics Generator.

Generates realistic time-series metrics simulating AWS EC2 instances under
normal operating conditions and various infrastructure anomaly scenarios.
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

# Supported anomaly types
VALID_ANOMALY_TYPES: tuple[str, ...] = (
    "normal",
    "cpu_spike",
    "memory_spike",
    "disk_anomaly",
    "network_spike",
    "combined_anomaly",
    "gradual_degradation",
)

# Overlap precedence rule: higher index indicates higher precedence
ANOMALY_PRECEDENCE: dict[str, int] = {
    "normal": 0,
    "network_spike": 1,
    "disk_anomaly": 2,
    "memory_spike": 3,
    "cpu_spike": 4,
    "gradual_degradation": 5,
    "combined_anomaly": 6,
}

# Required columns in generated dataset
REQUIRED_COLUMNS: list[str] = [
    "timestamp",
    "instance_id",
    "cpu_usage",
    "memory_usage",
    "disk_usage",
    "network_in",
    "network_out",
    "request_count",
    "response_time",
    "anomaly_label",
    "anomaly_type",
]


def generate_timestamps(
    start_time: str = "2026-03-01 00:00:00",
    num_records: int = 10000,
    freq: str = "1min",
) -> pd.DatetimeIndex:
    """Generate a continuous sequential DatetimeIndex.

    Args:
        start_time: ISO-formatted start timestamp string.
        num_records: Number of timestamps to generate.
        freq: Frequency string (e.g., '1min').

    Returns:
        pd.DatetimeIndex with monotonic 1-minute steps.
    """
    return pd.date_range(start=start_time, periods=num_records, freq=freq)


def generate_normal_metrics(
    timestamps: pd.DatetimeIndex,
    instance_id: str = "i-0f8b3c4a2d1e98765",
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic baseline infrastructure metrics with natural fluctuations.

    Models inter-metric dependencies:
    - Diurnal cyclical pattern (peak daytime activity vs. nighttime lull).
    - Request count drives CPU utilization and network throughput.
    - CPU utilization and request volume correlate with response time.
    - Memory exhibits autoregressive stability with subtle cache variation.
    - Disk utilization exhibits slow steady accumulation over time.

    Args:
        timestamps: Continuous DatetimeIndex for the records.
        instance_id: Simulated cloud compute instance identifier.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame containing normal baseline metrics.
    """
    rng = np.random.default_rng(seed)
    n = len(timestamps)

    # 1. Cyclical Diurnal Workload Pattern (24-hour cycle)
    # Peak activity around 14:00 (afternoon), trough around 03:00 (early morning)
    hours = timestamps.hour + timestamps.minute / 60.0
    day_cycle = 0.5 * (1.0 + np.sin((hours - 8.0) * np.pi / 12.0))

    # Weekend dampening effect (Saturday=5, Sunday=6)
    day_of_week = timestamps.dayofweek
    weekend_mask = day_of_week >= 5
    workload_multiplier = np.where(weekend_mask, 0.75, 1.0) * day_cycle

    # 2. Request Count (requests per minute, correlated with workload)
    base_requests = 160.0 + 260.0 * workload_multiplier
    request_noise = rng.normal(0.0, 18.0, size=n)
    request_count = np.clip(
        np.round(base_requests + request_noise), 40.0, 650.0
    ).astype(np.int64)

    # 3. Network In (Mbps, incoming requests payload)
    net_in_base = 12.0 + 0.075 * request_count
    net_in_noise = rng.normal(0.0, 2.5, size=n)
    network_in = np.clip(np.round(net_in_base + net_in_noise, 2), 4.0, 85.0)

    # 4. Network Out (Mbps, outgoing response payload, typically larger)
    net_out_base = 22.0 + 0.17 * request_count + 0.35 * network_in
    net_out_noise = rng.normal(0.0, 4.0, size=n)
    network_out = np.clip(np.round(net_out_base + net_out_noise, 2), 12.0, 175.0)

    # 5. CPU Usage (percentage, directly driven by request processing)
    # Base idle CPU 18% + load factor + random fluctuation
    cpu_base = 18.0 + 0.055 * request_count
    cpu_noise = rng.normal(0.0, 2.8, size=n)
    cpu_usage = np.clip(np.round(cpu_base + cpu_noise, 2), 15.0, 65.0)

    # 6. Memory Usage (percentage, stable autoregressive process)
    # Simulates continuous memory occupancy with slow drift and periodic GC
    mem_shocks = rng.normal(0.0, 0.35, size=n)
    mem_series = np.zeros(n, dtype=np.float64)
    mem_series[0] = 46.0
    for i in range(1, n):
        # AR(1) process with mean reversion to 48.0%
        mem_series[i] = 0.995 * mem_series[i - 1] + 0.005 * 48.0 + mem_shocks[i]
    memory_usage = np.clip(np.round(mem_series, 2), 32.0, 68.0)

    # 7. Disk Usage (percentage, slowly increasing log and data accumulation)
    # Increases by ~6-7% over the 10,000 minutes with minor micro-jitter
    disk_drift = np.linspace(41.5, 48.8, n, dtype=np.float64)
    disk_jitter = rng.normal(0.0, 0.08, size=n)
    disk_usage = np.clip(np.round(disk_drift + disk_jitter, 2), 35.0, 75.0)

    # 8. Response Time (milliseconds, correlates with CPU and request volume)
    resp_base = 24.0 + 0.32 * cpu_usage + 0.025 * request_count
    resp_noise = rng.exponential(scale=3.5, size=n)
    response_time = np.clip(np.round(resp_base + resp_noise, 2), 18.0, 95.0)

    df = pd.DataFrame(
        {
            "timestamp": timestamps.strftime("%Y-%m-%d %H:%M:%S"),
            "instance_id": instance_id,
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "disk_usage": disk_usage,
            "network_in": network_in,
            "network_out": network_out,
            "request_count": request_count,
            "response_time": response_time,
            "anomaly_label": np.zeros(n, dtype=np.int64),
            "anomaly_type": "normal",
        }
    )

    return df


def _apply_anomaly_label(
    df: pd.DataFrame,
    start_idx: int,
    end_idx: int,
    anomaly_type: str,
) -> None:
    """Apply anomaly label and type respecting the precedence hierarchy."""
    for idx in range(start_idx, end_idx):
        current_type = df.at[idx, "anomaly_type"]
        current_prec = ANOMALY_PRECEDENCE.get(current_type, 0)
        new_prec = ANOMALY_PRECEDENCE.get(anomaly_type, 0)

        df.at[idx, "anomaly_label"] = 1
        if new_prec >= current_prec:
            df.at[idx, "anomaly_type"] = anomaly_type


def inject_cpu_anomalies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    windows: list[tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Inject sudden high CPU utilization spikes (90-100%).

    Simulates runaway compute jobs, tight processing loops, or sudden lock
    contention. Elevated CPU also creates moderate response time inflation.

    Args:
        df: Input DataFrame.
        rng: NumPy random generator.
        windows: Optional list of (start_index, end_index) slices.

    Returns:
        DataFrame with CPU spikes injected.
    """
    if windows is None:
        windows = [(1200, 1235), (7600, 7645)]  # 35 + 45 = 80 records

    for start_idx, end_idx in windows:
        length = end_idx - start_idx
        # CPU pegged at 91.0 - 99.8%
        cpu_vals = rng.uniform(91.0, 99.8, size=length)
        df.loc[start_idx : end_idx - 1, "cpu_usage"] = np.round(cpu_vals, 2)

        # Response time jumps due to thread starvation (190 - 360 ms)
        rt_vals = rng.uniform(190.0, 360.0, size=length)
        current_rt = df.loc[start_idx : end_idx - 1, "response_time"].to_numpy()
        df.loc[start_idx : end_idx - 1, "response_time"] = np.round(
            np.maximum(current_rt, rt_vals), 2
        )

        _apply_anomaly_label(df, start_idx, end_idx, "cpu_spike")

    return df


def inject_memory_anomalies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    windows: list[tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Inject memory saturation spikes (90-99%).

    Simulates runaway memory buffers, sudden large dataset deserialization,
    or rapid memory leaks leading to near-OOM conditions.

    Args:
        df: Input DataFrame.
        rng: NumPy random generator.
        windows: Optional list of (start_index, end_index) slices.

    Returns:
        DataFrame with memory spikes injected.
    """
    if windows is None:
        windows = [(2400, 2440), (8200, 8240)]  # 40 + 40 = 80 records

    for start_idx, end_idx in windows:
        length = end_idx - start_idx
        # Memory consumption reaches 91.5 - 99.2%
        mem_vals = rng.uniform(91.5, 99.2, size=length)
        df.loc[start_idx : end_idx - 1, "memory_usage"] = np.round(mem_vals, 2)

        # Swapping and GC latency impact response time (130 - 270 ms)
        rt_vals = rng.uniform(130.0, 270.0, size=length)
        current_rt = df.loc[start_idx : end_idx - 1, "response_time"].to_numpy()
        df.loc[start_idx : end_idx - 1, "response_time"] = np.round(
            np.maximum(current_rt, rt_vals), 2
        )

        _apply_anomaly_label(df, start_idx, end_idx, "memory_spike")

    return df


def inject_disk_anomalies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    windows: list[tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Inject disk utilization saturation and surge anomalies (90-100%).

    Simulates unrotated runaway log dumps, core dumps, or storage filling.

    Args:
        df: Input DataFrame.
        rng: NumPy random generator.
        windows: Optional list of (start_index, end_index) slices.

    Returns:
        DataFrame with disk anomalies injected.
    """
    if windows is None:
        windows = [(3600, 3640), (8700, 8740)]  # 40 + 40 = 80 records

    for start_idx, end_idx in windows:
        length = end_idx - start_idx
        # Disk usage reaches 92.0 - 99.5%
        disk_vals = rng.uniform(92.0, 99.5, size=length)
        df.loc[start_idx : end_idx - 1, "disk_usage"] = np.round(disk_vals, 2)

        # I/O wait overhead mildly affects response times (110 - 210 ms)
        rt_vals = rng.uniform(110.0, 210.0, size=length)
        current_rt = df.loc[start_idx : end_idx - 1, "response_time"].to_numpy()
        df.loc[start_idx : end_idx - 1, "response_time"] = np.round(
            np.maximum(current_rt, rt_vals), 2
        )

        _apply_anomaly_label(df, start_idx, end_idx, "disk_anomaly")

    return df


def inject_network_anomalies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    windows: list[tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Inject extreme network traffic spikes (inbound/outbound surges).

    Simulates flood attacks, heavy data replication, or massive client surges.

    Args:
        df: Input DataFrame.
        rng: NumPy random generator.
        windows: Optional list of (start_index, end_index) slices.

    Returns:
        DataFrame with network spikes injected.
    """
    if windows is None:
        windows = [(4800, 4835), (9100, 9140)]  # 35 + 40 = 75 records

    for start_idx, end_idx in windows:
        length = end_idx - start_idx
        # Network traffic surges 6x to 12x normal volumes
        net_in_vals = rng.uniform(420.0, 880.0, size=length)
        net_out_vals = rng.uniform(650.0, 1380.0, size=length)
        req_vals = rng.integers(1400, 2900, size=length, dtype=np.int64)

        df.loc[start_idx : end_idx - 1, "network_in"] = np.round(net_in_vals, 2)
        df.loc[start_idx : end_idx - 1, "network_out"] = np.round(net_out_vals, 2)
        df.loc[start_idx : end_idx - 1, "request_count"] = req_vals

        # Packet processing elevates CPU (72 - 88%)
        cpu_vals = rng.uniform(72.0, 88.0, size=length)
        current_cpu = df.loc[start_idx : end_idx - 1, "cpu_usage"].to_numpy()
        df.loc[start_idx : end_idx - 1, "cpu_usage"] = np.round(
            np.maximum(current_cpu, cpu_vals), 2
        )

        # Network congestion raises response time (180 - 420 ms)
        rt_vals = rng.uniform(180.0, 420.0, size=length)
        current_rt = df.loc[start_idx : end_idx - 1, "response_time"].to_numpy()
        df.loc[start_idx : end_idx - 1, "response_time"] = np.round(
            np.maximum(current_rt, rt_vals), 2
        )

        _apply_anomaly_label(df, start_idx, end_idx, "network_spike")

    return df


def inject_combined_anomalies(
    df: pd.DataFrame,
    rng: np.random.Generator,
    windows: list[tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Inject simultaneous catastrophic multi-metric infrastructure anomalies.

    Simulates cascading service failures where CPU, memory, network, and
    application latency collapse simultaneously.

    Args:
        df: Input DataFrame.
        rng: NumPy random generator.
        windows: Optional list of (start_index, end_index) slices.

    Returns:
        DataFrame with combined anomalies injected.
    """
    if windows is None:
        windows = [(6000, 6040), (9500, 9545)]  # 40 + 45 = 85 records

    for start_idx, end_idx in windows:
        length = end_idx - start_idx

        # Severe multi-metric saturation
        cpu_vals = rng.uniform(94.0, 99.8, size=length)
        mem_vals = rng.uniform(92.0, 98.9, size=length)
        net_in_vals = rng.uniform(350.0, 720.0, size=length)
        net_out_vals = rng.uniform(500.0, 980.0, size=length)
        req_vals = rng.integers(1200, 2400, size=length, dtype=np.int64)
        # Severe response time degradation (850 - 2400 ms)
        rt_vals = rng.uniform(850.0, 2400.0, size=length)

        df.loc[start_idx : end_idx - 1, "cpu_usage"] = np.round(cpu_vals, 2)
        df.loc[start_idx : end_idx - 1, "memory_usage"] = np.round(mem_vals, 2)
        df.loc[start_idx : end_idx - 1, "network_in"] = np.round(net_in_vals, 2)
        df.loc[start_idx : end_idx - 1, "network_out"] = np.round(net_out_vals, 2)
        df.loc[start_idx : end_idx - 1, "request_count"] = req_vals
        df.loc[start_idx : end_idx - 1, "response_time"] = np.round(rt_vals, 2)

        _apply_anomaly_label(df, start_idx, end_idx, "combined_anomaly")

    return df


def inject_gradual_degradation(
    df: pd.DataFrame,
    rng: np.random.Generator,
    windows: list[tuple[int, int]] | None = None,
) -> pd.DataFrame:
    """Inject slow, insidious system degradation over a continuous window.

    Simulates a memory leak with progressive heap fragmentation, increasing
    GC pauses, rising CPU, and steadily deteriorating response times.

    Args:
        df: Input DataFrame.
        rng: NumPy random generator.
        windows: Optional list of (start_index, end_index) slices.

    Returns:
        DataFrame with gradual degradation injected.
    """
    if windows is None:
        windows = [(6800, 6900)]  # 100 records

    for start_idx, end_idx in windows:
        length = end_idx - start_idx
        ramp = np.linspace(0.0, 1.0, length)

        # Memory smoothly climbing from baseline to 96%
        base_mem = df.loc[start_idx : end_idx - 1, "memory_usage"].to_numpy()
        target_mem = 96.0 + rng.normal(0.0, 0.5, size=length)
        mem_degraded = base_mem + ramp * (target_mem - base_mem)

        # CPU rising as garbage collection struggles to reclaim space
        base_cpu = df.loc[start_idx : end_idx - 1, "cpu_usage"].to_numpy()
        target_cpu = 86.0 + rng.normal(0.0, 1.5, size=length)
        cpu_degraded = base_cpu + (ramp**1.5) * (target_cpu - base_cpu)

        # Response time escalates exponentially
        base_rt = df.loc[start_idx : end_idx - 1, "response_time"].to_numpy()
        target_rt = 620.0 + rng.uniform(-30.0, 50.0, size=length)
        rt_degraded = base_rt + (ramp**2.0) * (target_rt - base_rt)

        df.loc[start_idx : end_idx - 1, "memory_usage"] = np.round(
            np.clip(mem_degraded, 0.0, 99.0), 2
        )
        df.loc[start_idx : end_idx - 1, "cpu_usage"] = np.round(
            np.clip(cpu_degraded, 0.0, 98.0), 2
        )
        df.loc[start_idx : end_idx - 1, "response_time"] = np.round(
            np.clip(rt_degraded, 15.0, 800.0), 2
        )

        _apply_anomaly_label(df, start_idx, end_idx, "gradual_degradation")

    return df


def generate_infrastructure_dataset(
    num_records: int = 10000,
    random_seed: int = 42,
    start_time: str = "2026-03-01 00:00:00",
    instance_id: str = "i-0f8b3c4a2d1e98765",
    anomaly_config: dict[str, list[tuple[int, int]]] | None = None,
) -> pd.DataFrame:
    """Generate the full synthetic cloud infrastructure anomaly dataset.

    Combines baseline normal generation with modular anomaly injection.
    Ensures approximately 5% anomalous observations distributed across 6
    distinct infrastructure failure categories.

    Args:
        num_records: Total observation count (default 10,000).
        random_seed: Reproducible seed.
        start_time: Starting timestamp.
        instance_id: Simulated AWS EC2 instance identifier.
        anomaly_config: Custom window intervals per anomaly type.

    Returns:
        Fully generated and labeled Pandas DataFrame.
    """
    rng = np.random.default_rng(random_seed)

    # 1. Generate Timestamps & Baseline Normal Metrics
    timestamps = generate_timestamps(
        start_time=start_time, num_records=num_records, freq="1min"
    )
    df = generate_normal_metrics(
        timestamps=timestamps, instance_id=instance_id, seed=random_seed
    )

    # 2. Extract or Default Anomaly Windows
    # If custom windows provided, scale/use them; otherwise use calibrated defaults
    cfg = anomaly_config or {}

    cpu_win = cfg.get("cpu_spike")
    mem_win = cfg.get("memory_spike")
    disk_win = cfg.get("disk_anomaly")
    net_win = cfg.get("network_spike")
    comb_win = cfg.get("combined_anomaly")
    degrad_win = cfg.get("gradual_degradation")

    # If non-default num_records and no custom windows, scale windows proportionally
    if anomaly_config is None and num_records != 10000:
        scale = num_records / 10000.0

        def _scale_wins(wins: list[tuple[int, int]]) -> list[tuple[int, int]]:
            return [
                (max(0, int(w[0] * scale)), min(num_records, int(w[1] * scale)))
                for w in wins
            ]

        cpu_win = _scale_wins([(1200, 1235), (7600, 7645)])
        mem_win = _scale_wins([(2400, 2440), (8200, 8240)])
        disk_win = _scale_wins([(3600, 3640), (8700, 8740)])
        net_win = _scale_wins([(4800, 4835), (9100, 9140)])
        comb_win = _scale_wins([(6000, 6040), (9500, 9545)])
        degrad_win = _scale_wins([(6800, 6900)])

    # 3. Inject Anomalies Modally
    df = inject_cpu_anomalies(df, rng=rng, windows=cpu_win)
    df = inject_memory_anomalies(df, rng=rng, windows=mem_win)
    df = inject_disk_anomalies(df, rng=rng, windows=disk_win)
    df = inject_network_anomalies(df, rng=rng, windows=net_win)
    df = inject_combined_anomalies(df, rng=rng, windows=comb_win)
    df = inject_gradual_degradation(df, rng=rng, windows=degrad_win)

    # 4. Strict Column Ordering and Monotonic Timestamp Sorting
    df["timestamp_dt"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values(by="timestamp_dt").drop(columns=["timestamp_dt"])
    df = df.reset_index(drop=True)
    df = df[REQUIRED_COLUMNS]

    return df


def save_dataset(
    df: pd.DataFrame,
    file_path: Path | str,
    sample_path: Path | str | None = None,
    summary_path: Path | str | None = None,
    sample_size: int = 100,
) -> tuple[Path, Path | None, Path | None]:
    """Save the generated DataFrame, sample CSV, and summary text.

    Args:
        df: Dataset DataFrame.
        file_path: Destination path for full CSV.
        sample_path: Optional destination path for sample CSV.
        summary_path: Optional destination path for summary text.
        sample_size: Number of records to include in sample file.

    Returns:
        Tuple of (full_path, sample_path, summary_path).
    """
    main_p = Path(file_path)
    main_p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(main_p, index=False)

    samp_p = None
    if sample_path:
        samp_p = Path(sample_path)
        samp_p.parent.mkdir(parents=True, exist_ok=True)
        # Select first sample_size records
        sample_df = df.head(sample_size)
        sample_df.to_csv(samp_p, index=False)

    sum_p = None
    if summary_path:
        sum_p = Path(summary_path)
        sum_p.parent.mkdir(parents=True, exist_ok=True)
        summary_text = generate_dataset_summary_text(df)
        sum_p.write_text(summary_text, encoding="utf-8")

    return main_p, samp_p, sum_p


def generate_dataset_summary_text(df: pd.DataFrame) -> str:
    """Produce a structured textual summary of the dataset."""
    total_records = len(df)
    normal_count = int((df["anomaly_label"] == 0).sum())
    anom_count = int((df["anomaly_label"] == 1).sum())
    anom_pct = (anom_count / total_records * 100) if total_records > 0 else 0.0

    type_counts = df["anomaly_type"].value_counts().to_dict()
    missing_counts = df.isna().sum().to_dict()

    start_ts = df["timestamp"].iloc[0] if total_records > 0 else "N/A"
    end_ts = df["timestamp"].iloc[-1] if total_records > 0 else "N/A"
    unique_instances = df["instance_id"].nunique()

    lines = [
        "=" * 70,
        "AIOps Cloud Infrastructure Anomaly Detection - Dataset Summary",
        "=" * 70,
        f"Total Records           : {total_records:,}",
        f"Normal Records          : {normal_count:,}",
        f"Anomalous Records       : {anom_count:,}",
        f"Anomaly Percentage      : {anom_pct:.2f}%",
        f"Start Timestamp         : {start_ts}",
        f"End Timestamp           : {end_ts}",
        f"Unique Instances        : {unique_instances}",
        "-" * 70,
        "Anomaly Type Breakdown:",
    ]

    for atype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = (count / total_records * 100) if total_records > 0 else 0.0
        lines.append(f"  - {atype:<22}: {count:>5} records ({pct:5.2f}%)")

    lines.extend(
        [
            "-" * 70,
            "Dataset Columns:",
        ]
    )
    for col in df.columns:
        lines.append(f"  - {col:<18} (dtype: {df[col].dtype})")

    lines.extend(
        [
            "-" * 70,
            "Missing Value Counts:",
        ]
    )
    for col, mcount in missing_counts.items():
        lines.append(f"  - {col:<18}: {mcount}")

    lines.append("=" * 70)
    return "\n".join(lines) + "\n"
