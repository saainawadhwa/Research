# SPY Mean Reversion Backtest

This repository contains a self-contained Python backtest comparing a simple long-only mean reversion strategy on SPY against buy-and-hold over the past five years, including transaction fees.

## Run

```bash
python3 outputs/mean_reversion_backtest.py
```

The script downloads adjusted SPY prices from Yahoo Finance and writes:

- `outputs/report.md`
- `outputs/backtest_summary.csv`
- `outputs/equity_curve.csv`
- `outputs/equity_curve.svg`

## Current Published Results

Using the downloaded window from 2021-06-21 to 2026-06-18, with 0.10% transaction cost on each buy and sell:

| Strategy | Final value | Total return | CAGR | Max drawdown | Trades | Fees paid |
|---|---:|---:|---:|---:|---:|---:|
| Mean reversion | $11,005.10 | 10.05% | 1.97% | -16.09% | 72 | $729.66 |
| Buy and hold | $18,683.58 | 86.84% | 13.57% | -24.50% | 2 | $28.69 |
