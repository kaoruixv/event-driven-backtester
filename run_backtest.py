#!/usr/bin/env python3
"""
run_backtest.py
----------------
Single entrypoint that the GitHub Actions workflow (and any human) calls to
run the entire pipeline: fetch data -> run event-driven backtest ->
compute performance -> regenerate the tearsheet. Designed to be idempotent
and safe to run unattended on a schedule.

Usage:
    python run_backtest.py --config config/config.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import yaml

from src.data.data_handler import YFinanceDataHandler
from src.engine.backtest import Backtest
from src.execution.execution_handler import SimulatedExecutionHandler
from src.reporting.performance import summarize
from src.reporting.tearsheet import generate_tearsheet
from src.strategies.sma_crossover import SMACrossoverStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_backtest")


def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if cfg["data"].get("end") is None:
        cfg["data"]["end"] = date.today().isoformat()
    return cfg


def main(config_path: str) -> int:
    cfg = load_config(config_path)

    try:
        data_handler = YFinanceDataHandler(
            event_queue=None,  # attached inside Backtest
            symbols=cfg["data"]["symbols"],
            start=cfg["data"]["start"],
            end=cfg["data"]["end"],
        )
    except Exception:
        logger.exception("Data acquisition failed unrecoverably — aborting run.")
        return 1

    execution_handler = SimulatedExecutionHandler(**cfg["execution"])

    bt = Backtest(
        data_handler=data_handler,
        strategy_cls=SMACrossoverStrategy,
        strategy_kwargs={
            "short_window": cfg["strategy"]["short_window"],
            "long_window": cfg["strategy"]["long_window"],
        },
        symbols=cfg["data"]["symbols"],
        initial_capital=cfg["portfolio"]["initial_capital"],
        execution_handler=execution_handler,
        position_size_pct=cfg["portfolio"]["position_size_pct"],
    )

    try:
        portfolio = bt.run()
    except Exception:
        logger.exception("Backtest run failed — aborting before report generation.")
        return 1

    summary = summarize(portfolio)
    logger.info("Run summary: %s", summary)

    out_dir = generate_tearsheet(portfolio, summary, out_dir=cfg["reporting"]["out_dir"])
    logger.info("Tearsheet written to %s", out_dir)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    sys.exit(main(args.config))
