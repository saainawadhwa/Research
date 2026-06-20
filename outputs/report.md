# SPY Mean Reversion Backtest

Data source: Yahoo Finance chart endpoint for `SPY`. SPY is used as a tradable S&P 500 proxy.

Data downloaded: 2021-06-21 to 2026-06-18. Backtest trading window: 2021-07-20 to 2026-06-18.

## Assumptions

- Initial capital: $10,000.00
- Transaction fee: 0.10% on each buy and sell, including final liquidation
- Mean reversion rule: buy at next session open when the prior close has a 20-day z-score <= -1.0; exit at next session open when z-score >= 0.0
- Prices: adjusted open and adjusted close, so dividends and splits are reflected
- Long-only, no leverage, fractional shares allowed, idle cash earns 0%

## Results

| Strategy | Final value | Total return | CAGR | Volatility | Sharpe | Max drawdown | Market exposure | Trades | Fees paid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Mean reversion | $11,005.10 | 10.05% | 1.97% | 12.41% | 0.20 | -16.09% | 27.94% | 72 | $729.66 |
| Buy and hold | $18,683.58 | 86.84% | 13.57% | 17.22% | 0.81 | -24.50% | 99.92% | 2 | $28.69 |

## Takeaway

The mean reversion strategy finished with $11,005.10, versus $18,683.58 for buy and hold. In this five-year test, the difference was $-7,678.48.

Run `python3 outputs/mean_reversion_backtest.py` to regenerate the full daily equity curve CSV and SVG chart.
