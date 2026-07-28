"""
performance.py
---------------
Standard performance metrics computed off the realized equity curve, plus
the realistic-vs-idealized comparison that is the whole point of this
project: how much of the idealized (frictionless) P&L got eaten by
slippage, spread, impact, and latency.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / TRADING_DAYS
    if excess.std() == 0:
        return 0.0
    return float(np.sqrt(TRADING_DAYS) * excess.mean() / excess.std())


def sortino_ratio(returns: pd.Series, risk_free: float = 0.0) -> float:
    excess = returns - risk_free / TRADING_DAYS
    downside = excess[excess < 0]
    if downside.std() == 0 or len(downside) == 0:
        return 0.0
    return float(np.sqrt(TRADING_DAYS) * excess.mean() / downside.std())


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def annualized_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = len(equity) / TRADING_DAYS
    if years <= 0:
        return 0.0
    return float((1 + total_return) ** (1 / years) - 1)


def turnover(fills: pd.DataFrame, avg_equity: float) -> float:
    if fills.empty or avg_equity <= 0:
        return 0.0
    dollar_volume = (fills["quantity"].abs() * fills["fill_price"]).sum()
    return float(dollar_volume / avg_equity)


def summarize(portfolio) -> dict:
    real_df = portfolio.equity_dataframe()
    ideal_df = portfolio.ideal_equity_dataframe()
    fills_df = portfolio.fills_dataframe()

    real_equity = real_df["equity"]
    ideal_equity = ideal_df["equity"]

    realistic_pnl = real_equity.iloc[-1] - portfolio.initial_capital
    idealized_pnl = ideal_equity.iloc[-1] - portfolio.initial_capital
    cost_drag = idealized_pnl - realistic_pnl

    total_slippage = fills_df["slippage"].sum() if not fills_df.empty else 0.0
    total_commission = fills_df["commission"].sum() if not fills_df.empty else 0.0

    return {
        "initial_capital": portfolio.initial_capital,
        "final_equity_realistic": float(real_equity.iloc[-1]),
        "final_equity_idealized": float(ideal_equity.iloc[-1]),
        "realistic_pnl": float(realistic_pnl),
        "idealized_pnl": float(idealized_pnl),
        "execution_cost_drag": float(cost_drag),
        "execution_cost_drag_pct_of_idealized": float(cost_drag / idealized_pnl) if idealized_pnl else None,
        "total_return_pct": float(real_equity.iloc[-1] / portfolio.initial_capital - 1),
        "annualized_return": annualized_return(real_equity),
        "sharpe_ratio": sharpe_ratio(real_df["returns"]),
        "sortino_ratio": sortino_ratio(real_df["returns"]),
        "max_drawdown": max_drawdown(real_equity),
        "turnover": turnover(fills_df, real_equity.mean()),
        "num_fills": int(len(fills_df)),
        "total_slippage_dollars": float(total_slippage),
        "total_commission_dollars": float(total_commission),
        "avg_latency_ms": float(fills_df["latency_ms"].mean()) if not fills_df.empty else 0.0,
        "num_partial_fills": int((fills_df["remaining_quantity"].abs() > 1e-6).sum()) if not fills_df.empty else 0,
    }
