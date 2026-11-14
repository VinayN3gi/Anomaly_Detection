"""Visualizations Module for Infrastructure Telemetry and Anomalies.

Generates publication-quality charts examining time-series behavior,
metric distributions, correlation dynamics, and anomaly characterizations.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

# Set non-interactive writable cache directory for Matplotlib
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = tempfile.gettempdir()

import matplotlib

matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def set_plotting_theme() -> None:
    """Configure modern aesthetics and typography for matplotlib and seaborn."""
    sns.set_theme(style="whitegrid", palette="deep")
    plt.rcParams.update(
        {
            "figure.autolayout": True,
            "figure.dpi": 150,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.labelsize": 12,
            "axes.labelweight": "medium",
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        }
    )


def plot_metric_timeseries(
    df: pd.DataFrame,
    metric_col: str,
    y_label: str,
    title: str,
    output_path: Path | str,
    downsample_factor: int = 1,
) -> Path:
    """Generate a clean time-series plot with highlighted anomaly occurrences.

    Args:
        df: Metric DataFrame containing timestamp and anomaly flags.
        metric_col: Metric column name to plot.
        y_label: Formatted label for y-axis with unit.
        title: Descriptive plot title.
        output_path: Target PNG file path.
        downsample_factor: Step factor for large datasets.

    Returns:
        Path to saved visualization.
    """
    set_plotting_theme()
    fig, ax = plt.subplots(figsize=(14, 5))

    plot_df = df.iloc[::downsample_factor].copy()
    plot_df["timestamp_dt"] = pd.to_datetime(plot_df["timestamp"])

    # Plot baseline series
    ax.plot(
        plot_df["timestamp_dt"],
        plot_df[metric_col],
        color="#2b5c8f",
        linewidth=1.2,
        alpha=0.85,
        label=f"Normal Telemetry ({metric_col})",
    )

    # Highlight anomalous points
    anom_points = plot_df[plot_df["anomaly_label"] == 1]
    if not anom_points.empty:
        ax.scatter(
            anom_points["timestamp_dt"],
            anom_points[metric_col],
            color="#d9383a",
            s=22,
            zorder=5,
            edgecolors="#8b0000",
            linewidth=0.5,
            label=f"Anomalous Events ({len(anom_points)} pts)",
        )

    ax.set_title(title, pad=12)
    ax.set_xlabel("Observation Timestamp")
    ax.set_ylabel(y_label)
    ax.legend(loc="upper right", frameon=True)
    ax.grid(True, linestyle="--", alpha=0.6)

    fig.autofmt_xdate(rotation=25)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return out_p


def plot_anomaly_distribution(
    df: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Plot binary class distribution (normal vs anomalous observations)."""
    set_plotting_theme()
    fig, (ax_bar, ax_pie) = plt.subplots(1, 2, figsize=(13, 5))

    counts = df["anomaly_label"].value_counts().rename({0: "Normal", 1: "Anomalous"})
    colors = ["#2b5c8f", "#d9383a"]

    # Bar plot
    bars = ax_bar.bar(counts.index, counts.values, color=colors, width=0.5)
    ax_bar.set_title("Normal vs. Anomalous Observation Count")
    ax_bar.set_ylabel("Record Count")
    ax_bar.grid(axis="y", linestyle="--", alpha=0.6)

    for bar in bars:
        height = bar.get_height()
        pct = (height / len(df)) * 100
        ax_bar.annotate(
            f"{int(height):,}\n({pct:.1f}%)",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontweight="bold",
        )

    # Pie chart
    ax_pie.pie(
        counts.values,
        labels=counts.index,
        autopct="%1.1f%%",
        startangle=140,
        colors=colors,
        explode=(0, 0.1),
        shadow=True,
    )
    ax_pie.set_title("Infrastructure Telemetry Composition")

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return out_p


def plot_anomaly_type_distribution(
    df: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Plot distribution breakdown across specific anomaly categories."""
    set_plotting_theme()
    fig, ax = plt.subplots(figsize=(12, 6))

    # Exclude normal records to inspect anomaly category representation
    anom_only = df[df["anomaly_type"] != "normal"]["anomaly_type"].value_counts()

    palette = sns.color_palette("rocket", n_colors=len(anom_only))
    bars = ax.barh(
        anom_only.index,
        anom_only.values,
        color=palette,
        edgecolor="#333333",
        linewidth=0.6,
    )

    total_anom = anom_only.sum()
    for bar in bars:
        width = bar.get_width()
        pct = (width / total_anom) * 100
        ax.annotate(
            f" {int(width)} records ({pct:.1f}%)",
            xy=(width, bar.get_y() + bar.get_height() / 2),
            va="center",
            fontweight="bold",
        )

    ax.set_title(
        "Distribution of Infrastructure Anomaly Types (500 Total Anomalies)", pad=12
    )
    ax.set_xlabel("Number of Anomalous Records")
    ax.set_ylabel("Failure Scenario")
    ax.grid(axis="x", linestyle="--", alpha=0.6)
    ax.invert_yaxis()

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return out_p


def plot_correlation_heatmap(
    df: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Compute and render correlation matrix heatmap of numerical metrics."""
    set_plotting_theme()
    fig, ax = plt.subplots(figsize=(10, 8))

    numeric_cols = [
        "cpu_usage",
        "memory_usage",
        "disk_usage",
        "network_in",
        "network_out",
        "request_count",
        "response_time",
        "anomaly_label",
    ]
    corr = df[numeric_cols].corr()

    sns.heatmap(
        corr,
        annot=True,
        fmt=".2f",
        cmap="coolwarm",
        vmin=-1.0,
        vmax=1.0,
        center=0.0,
        square=True,
        linewidths=0.8,
        cbar_kws={"shrink": 0.8, "label": "Pearson Correlation Coefficient"},
        ax=ax,
    )

    ax.set_title("Correlation Heatmap of Infrastructure Telemetry Metrics", pad=15)
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_p, dpi=200, bbox_inches="tight")
    plt.close(fig)

    return out_p


def generate_all_visualizations(
    df: pd.DataFrame,
    visualizations_dir: Path | str,
) -> dict[str, Path]:
    """Generate all 10 required exploratory visualization charts.

    Charts generated:
    1. cpu_usage.png
    2. memory_usage.png
    3. disk_usage.png
    4. network_in.png
    5. network_out.png
    6. request_count.png
    7. response_time.png
    8. anomaly_distribution.png
    9. anomaly_type_distribution.png
    10. correlation_heatmap.png

    Args:
        df: Input metric DataFrame.
        visualizations_dir: Output folder path.

    Returns:
        Mapping of chart name to generated file path.
    """
    vdir = Path(visualizations_dir)
    vdir.mkdir(parents=True, exist_ok=True)

    generated: dict[str, Path] = {}

    # 1. CPU Usage
    generated["cpu_usage"] = plot_metric_timeseries(
        df=df,
        metric_col="cpu_usage",
        y_label="CPU Utilization (%)",
        title="Simulated EC2 CPU Utilization Over Time (Normal vs Spikes)",
        output_path=vdir / "cpu_usage.png",
    )

    # 2. Memory Usage
    generated["memory_usage"] = plot_metric_timeseries(
        df=df,
        metric_col="memory_usage",
        y_label="Memory Utilization (%)",
        title="Simulated EC2 Memory Utilization Over Time (Normal vs Spikes & Leaks)",
        output_path=vdir / "memory_usage.png",
    )

    # 3. Disk Usage
    generated["disk_usage"] = plot_metric_timeseries(
        df=df,
        metric_col="disk_usage",
        y_label="Disk Utilization (%)",
        title="Simulated EC2 Disk Utilization Over Time (Accumulation & Surges)",
        output_path=vdir / "disk_usage.png",
    )

    # 4. Network In
    generated["network_in"] = plot_metric_timeseries(
        df=df,
        metric_col="network_in",
        y_label="Inbound Traffic (Mbps)",
        title="Incoming Network Throughput Over Time (Baseline vs Traffic Floods)",
        output_path=vdir / "network_in.png",
    )

    # 5. Network Out
    generated["network_out"] = plot_metric_timeseries(
        df=df,
        metric_col="network_out",
        y_label="Outbound Traffic (Mbps)",
        title="Outgoing Network Throughput Over Time (Baseline vs Egress Surges)",
        output_path=vdir / "network_out.png",
    )

    # 6. Request Count
    generated["request_count"] = plot_metric_timeseries(
        df=df,
        metric_col="request_count",
        y_label="Incoming Requests (req/min)",
        title="Application Request Volume Over Time (Circadian & Spikes)",
        output_path=vdir / "request_count.png",
    )

    # 7. Response Time
    generated["response_time"] = plot_metric_timeseries(
        df=df,
        metric_col="response_time",
        y_label="Response Time (ms)",
        title="Application Response Latency Over Time (Normal vs Degraded)",
        output_path=vdir / "response_time.png",
    )

    # 8. Anomaly Distribution (Binary)
    generated["anomaly_distribution"] = plot_anomaly_distribution(
        df=df,
        output_path=vdir / "anomaly_distribution.png",
    )

    # 9. Anomaly Type Distribution
    generated["anomaly_type_distribution"] = plot_anomaly_type_distribution(
        df=df,
        output_path=vdir / "anomaly_type_distribution.png",
    )

    # 10. Correlation Heatmap
    generated["correlation_heatmap"] = plot_correlation_heatmap(
        df=df,
        output_path=vdir / "correlation_heatmap.png",
    )

    return generated
