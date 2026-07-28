"""
tearsheet.py
------------
Generates the auto-published performance report: PNG charts + a single
self-contained HTML page. This is what the GitHub Actions workflow commits
back to the repo / publishes to GitHub Pages on every scheduled run, so the
report on the repo's front page is never more than one cron cycle stale.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

plt.style.use("seaborn-v0_8-darkgrid")


def _save(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_equity_curves(real_df: pd.DataFrame, ideal_df: pd.DataFrame, out_path: Path):
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(real_df.index, real_df["equity"], label="Realistic (simulated costs)", linewidth=1.8)
    ax.plot(ideal_df.index, ideal_df["equity"], label="Idealized (frictionless)", linewidth=1.4, linestyle="--")
    ax.set_title("Equity Curve: Realistic vs. Idealized Execution")
    ax.set_ylabel("Portfolio Value ($)")
    ax.legend()
    _save(fig, out_path)


def plot_drawdown(real_df: pd.DataFrame, out_path: Path):
    running_max = real_df["equity"].cummax()
    dd = real_df["equity"] / running_max - 1.0
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.fill_between(real_df.index, dd * 100, 0, color="firebrick", alpha=0.5)
    ax.set_title("Drawdown (%)")
    ax.set_ylabel("Drawdown %")
    _save(fig, out_path)


def plot_fill_quality(fills_df: pd.DataFrame, out_path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    if not fills_df.empty:
        axes[0].hist(fills_df["latency_ms"], bins=30, color="steelblue")
        axes[0].set_title("Fill Latency Distribution (ms)")
        axes[0].set_xlabel("ms")

        axes[1].hist(fills_df["slippage"], bins=30, color="darkorange")
        axes[1].set_title("Per-Fill Slippage ($)")
        axes[1].set_xlabel("$")
    _save(fig, out_path)


def plot_slippage_attribution(summary: dict, out_path: Path):
    fig, ax = plt.subplots(figsize=(6, 5))
    labels = ["Slippage", "Commission"]
    values = [summary["total_slippage_dollars"], summary["total_commission_dollars"]]
    ax.bar(labels, values, color=["darkorange", "gray"])
    ax.set_title("Execution Cost Attribution ($)")
    ax.set_ylabel("$")
    _save(fig, out_path)


def generate_tearsheet(portfolio, summary: dict, out_dir: str = "reports"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    real_df = portfolio.equity_dataframe()
    ideal_df = portfolio.ideal_equity_dataframe()
    fills_df = portfolio.fills_dataframe()

    plot_equity_curves(real_df, ideal_df, out_dir / "equity_curve.png")
    plot_drawdown(real_df, out_dir / "drawdown.png")
    plot_fill_quality(fills_df, out_dir / "fill_quality.png")
    plot_slippage_attribution(summary, out_dir / "slippage_attribution.png")

    with open(out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    _write_html(summary, out_dir)
    return out_dir


def _write_html(summary: dict, out_dir: Path):
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = "".join(
        f"<tr><td>{k.replace('_', ' ').title()}</td><td>{_fmt(v)}</td></tr>"
        for k, v in summary.items()
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Backtest Tearsheet</title>
<style>
body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 40px; background:#0d1117; color:#c9d1d9; }}
h1 {{ color:#58a6ff; }}
table {{ border-collapse: collapse; width: 100%; max-width: 700px; margin-bottom: 30px; }}
td {{ padding: 6px 12px; border-bottom: 1px solid #30363d; }}
img {{ max-width: 100%; margin-bottom: 24px; border: 1px solid #30363d; border-radius: 6px; }}
.timestamp {{ color: #8b949e; font-size: 0.9em; }}
</style></head>
<body>
<h1>Event-Driven Backtest Tearsheet</h1>
<p class="timestamp">Auto-generated {generated_at} — this page regenerates every scheduled run, no manual step involved.</p>
<h2>Summary</h2>
<table>{rows}</table>
<h2>Equity Curve</h2>
<img src="equity_curve.png">
<h2>Drawdown</h2>
<img src="drawdown.png">
<h2>Fill Quality</h2>
<img src="fill_quality.png">
<h2>Execution Cost Attribution</h2>
<img src="slippage_attribution.png">
</body></html>"""
    (out_dir / "index.html").write_text(html)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.4f}"
    return v
