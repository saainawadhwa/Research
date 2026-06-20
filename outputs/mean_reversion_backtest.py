#!/usr/bin/env python3
"""
Backtest a simple long-only mean reversion strategy on SPY.

SPY is used as a tradable proxy for the S&P 500 so transaction fees can be
modeled directly. Data comes from Yahoo Finance's chart endpoint.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import statistics
import urllib.parse
import urllib.request


SYMBOL = "SPY"
YEARS = 5
INITIAL_CAPITAL = 10_000.0
FEE_RATE = 0.001  # 0.10% per buy/sell, used as a commission + spread/slippage proxy.
LOOKBACK_DAYS = 20
ENTRY_Z = -1.0
EXIT_Z = 0.0

ROOT = os.path.dirname(os.path.abspath(__file__))
EQUITY_CSV = os.path.join(ROOT, "equity_curve.csv")
SUMMARY_CSV = os.path.join(ROOT, "backtest_summary.csv")
REPORT_MD = os.path.join(ROOT, "report.md")
CHART_SVG = os.path.join(ROOT, "equity_curve.svg")


def fetch_yahoo_chart(symbol: str, years: int) -> list[dict[str, float | str]]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?range={years}y&interval=1d&includePrePost=false&events=div%2Csplits"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    error = payload.get("chart", {}).get("error")
    if error:
        raise RuntimeError(f"Yahoo Finance returned an error: {error}")

    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    closes = quote["close"]
    opens = quote["open"]
    adjcloses = result["indicators"].get("adjclose", [{}])[0].get("adjclose", closes)

    rows: list[dict[str, float | str]] = []
    for timestamp, open_price, close_price, adjclose in zip(timestamps, opens, closes, adjcloses):
        if open_price is None or close_price is None or adjclose is None:
            continue
        adjustment = adjclose / close_price if close_price else 1.0
        rows.append(
            {
                "date": dt.datetime.fromtimestamp(timestamp).date().isoformat(),
                "adj_open": float(open_price) * adjustment,
                "adj_close": float(adjclose),
            }
        )
    if len(rows) <= LOOKBACK_DAYS + 2:
        raise RuntimeError("Not enough daily rows returned for the configured lookback.")
    return rows


def zscores(rows: list[dict[str, float | str]]) -> list[float | None]:
    values = [float(row["adj_close"]) for row in rows]
    z: list[float | None] = [None] * len(values)
    for i in range(LOOKBACK_DAYS - 1, len(values)):
        window = values[i - LOOKBACK_DAYS + 1 : i + 1]
        mean = statistics.fmean(window)
        std = statistics.pstdev(window)
        z[i] = 0.0 if std == 0 else (values[i] - mean) / std
    return z


def desired_positions(z: list[float | None]) -> list[int]:
    desired: list[int] = [0] * len(z)
    position = 0
    for i, score in enumerate(z):
        if score is None:
            desired[i] = position
            continue
        if position == 0 and score <= ENTRY_Z:
            position = 1
        elif position == 1 and score >= EXIT_Z:
            position = 0
        desired[i] = position
    return desired


def run_mean_reversion(rows: list[dict[str, float | str]], desired: list[int]) -> dict:
    start_index = LOOKBACK_DAYS
    cash = INITIAL_CAPITAL
    shares = 0.0
    fees = 0.0
    trades = 0
    buys = 0
    sells = 0
    curve = []

    for i in range(start_index, len(rows)):
        row = rows[i]
        open_price = float(row["adj_open"])
        close_price = float(row["adj_close"])
        target = desired[i - 1]

        if target == 1 and shares == 0.0:
            notional = cash / (1.0 + FEE_RATE)
            fee = notional * FEE_RATE
            shares = notional / open_price
            cash -= notional + fee
            fees += fee
            trades += 1
            buys += 1
        elif target == 0 and shares > 0.0:
            notional = shares * open_price
            fee = notional * FEE_RATE
            cash += notional - fee
            shares = 0.0
            fees += fee
            trades += 1
            sells += 1

        value = cash + shares * close_price
        curve.append(
            {
                "date": row["date"],
                "price": close_price,
                "value": value,
                "position": 1 if shares > 0.0 else 0,
            }
        )

    if shares > 0.0:
        last_price = float(rows[-1]["adj_close"])
        notional = shares * last_price
        fee = notional * FEE_RATE
        cash += notional - fee
        shares = 0.0
        fees += fee
        trades += 1
        sells += 1
        curve[-1]["value"] = cash
        curve[-1]["position"] = 0

    return {
        "curve": curve,
        "fees": fees,
        "trades": trades,
        "buys": buys,
        "sells": sells,
        "final_value": curve[-1]["value"],
    }


def run_buy_hold(rows: list[dict[str, float | str]]) -> dict:
    start_index = LOOKBACK_DAYS
    entry_open = float(rows[start_index]["adj_open"])
    notional = INITIAL_CAPITAL / (1.0 + FEE_RATE)
    entry_fee = notional * FEE_RATE
    shares = notional / entry_open
    curve = []

    for i in range(start_index, len(rows)):
        close_price = float(rows[i]["adj_close"])
        curve.append(
            {
                "date": rows[i]["date"],
                "price": close_price,
                "value": shares * close_price,
                "position": 1,
            }
        )

    exit_notional = shares * float(rows[-1]["adj_close"])
    exit_fee = exit_notional * FEE_RATE
    final_value = exit_notional - exit_fee
    curve[-1]["value"] = final_value
    curve[-1]["position"] = 0

    return {
        "curve": curve,
        "fees": entry_fee + exit_fee,
        "trades": 2,
        "buys": 1,
        "sells": 1,
        "final_value": final_value,
    }


def daily_returns(values: list[float]) -> list[float]:
    returns = []
    for previous, current in zip(values, values[1:]):
        returns.append(current / previous - 1.0 if previous else 0.0)
    return returns


def max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = value / peak - 1.0
        worst = min(worst, drawdown)
    return worst


def metrics(curve: list[dict], final_value: float) -> dict[str, float]:
    values = [float(row["value"]) for row in curve]
    returns = daily_returns(values)
    start = dt.date.fromisoformat(curve[0]["date"])
    end = dt.date.fromisoformat(curve[-1]["date"])
    years = max((end - start).days / 365.25, 1 / 365.25)
    total_return = final_value / INITIAL_CAPITAL - 1.0
    cagr = (final_value / INITIAL_CAPITAL) ** (1.0 / years) - 1.0
    volatility = statistics.pstdev(returns) * math.sqrt(252) if len(returns) > 1 else 0.0
    mean_daily = statistics.fmean(returns) if returns else 0.0
    std_daily = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = (mean_daily / std_daily) * math.sqrt(252) if std_daily else 0.0
    exposure = statistics.fmean(float(row["position"]) for row in curve)
    return {
        "final_value": final_value,
        "total_return": total_return,
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(values),
        "exposure": exposure,
    }


def fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def fmt_pct(value: float) -> str:
    return f"{value * 100:,.2f}%"


def write_outputs(rows: list[dict[str, float | str]], mean_rev: dict, buy_hold: dict) -> None:
    mr_curve = mean_rev["curve"]
    bh_curve = buy_hold["curve"]
    mr_metrics = metrics(mr_curve, float(mean_rev["final_value"]))
    bh_metrics = metrics(bh_curve, float(buy_hold["final_value"]))

    with open(EQUITY_CSV, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "spy_adjusted_close", "mean_reversion_value", "buy_hold_value", "mean_reversion_position"])
        for mr, bh in zip(mr_curve, bh_curve):
            writer.writerow(
                [
                    mr["date"],
                    f"{mr['price']:.4f}",
                    f"{mr['value']:.2f}",
                    f"{bh['value']:.2f}",
                    mr["position"],
                ]
            )

    summary_rows = [
        ("Mean reversion", mean_rev, mr_metrics),
        ("Buy and hold", buy_hold, bh_metrics),
    ]
    with open(SUMMARY_CSV, "w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "strategy",
                "final_value",
                "total_return",
                "cagr",
                "volatility",
                "sharpe",
                "max_drawdown",
                "exposure",
                "trades",
                "fees_paid",
            ]
        )
        for name, result, metric in summary_rows:
            writer.writerow(
                [
                    name,
                    f"{metric['final_value']:.2f}",
                    f"{metric['total_return']:.6f}",
                    f"{metric['cagr']:.6f}",
                    f"{metric['volatility']:.6f}",
                    f"{metric['sharpe']:.6f}",
                    f"{metric['max_drawdown']:.6f}",
                    f"{metric['exposure']:.6f}",
                    result["trades"],
                    f"{result['fees']:.2f}",
                ]
            )

    write_svg(mr_curve, bh_curve)

    start_date = mr_curve[0]["date"]
    end_date = mr_curve[-1]["date"]
    source_start = rows[0]["date"]
    source_end = rows[-1]["date"]
    report = f"""# SPY Mean Reversion Backtest

Data source: Yahoo Finance chart endpoint for `{SYMBOL}`. SPY is used as a tradable S&P 500 proxy.

Data downloaded: {source_start} to {source_end}. Backtest trading window: {start_date} to {end_date}.

## Assumptions

- Initial capital: {fmt_money(INITIAL_CAPITAL)}
- Transaction fee: {fmt_pct(FEE_RATE)} on each buy and sell, including final liquidation
- Mean reversion rule: buy at next session open when the prior close has a {LOOKBACK_DAYS}-day z-score <= {ENTRY_Z}; exit at next session open when z-score >= {EXIT_Z}
- Prices: adjusted open and adjusted close, so dividends and splits are reflected
- Long-only, no leverage, fractional shares allowed, idle cash earns 0%

## Results

| Strategy | Final value | Total return | CAGR | Volatility | Sharpe | Max drawdown | Market exposure | Trades | Fees paid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Mean reversion | {fmt_money(mr_metrics['final_value'])} | {fmt_pct(mr_metrics['total_return'])} | {fmt_pct(mr_metrics['cagr'])} | {fmt_pct(mr_metrics['volatility'])} | {mr_metrics['sharpe']:.2f} | {fmt_pct(mr_metrics['max_drawdown'])} | {fmt_pct(mr_metrics['exposure'])} | {mean_rev['trades']} | {fmt_money(mean_rev['fees'])} |
| Buy and hold | {fmt_money(bh_metrics['final_value'])} | {fmt_pct(bh_metrics['total_return'])} | {fmt_pct(bh_metrics['cagr'])} | {fmt_pct(bh_metrics['volatility'])} | {bh_metrics['sharpe']:.2f} | {fmt_pct(bh_metrics['max_drawdown'])} | {fmt_pct(bh_metrics['exposure'])} | {buy_hold['trades']} | {fmt_money(buy_hold['fees'])} |

## Takeaway

The mean reversion strategy finished with {fmt_money(mr_metrics['final_value'])}, versus {fmt_money(bh_metrics['final_value'])} for buy and hold. In this five-year test, the difference was {fmt_money(mr_metrics['final_value'] - bh_metrics['final_value'])}.

See `equity_curve.csv` for daily values and `equity_curve.svg` for the chart.
"""
    with open(REPORT_MD, "w", newline="\n") as file:
        file.write(report)


def write_svg(mr_curve: list[dict], bh_curve: list[dict]) -> None:
    width = 1100
    height = 620
    margin_left = 72
    margin_right = 28
    margin_top = 34
    margin_bottom = 68
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    values = [float(row["value"]) for row in mr_curve] + [float(row["value"]) for row in bh_curve]
    min_v = min(values)
    max_v = max(values)
    pad = (max_v - min_v) * 0.08 or 1.0
    min_v -= pad
    max_v += pad

    def point(index: int, value: float) -> tuple[float, float]:
        x = margin_left + (index / (len(mr_curve) - 1)) * plot_w
        y = margin_top + (1 - (value - min_v) / (max_v - min_v)) * plot_h
        return x, y

    def path(curve: list[dict]) -> str:
        commands = []
        for i, row in enumerate(curve):
            x, y = point(i, float(row["value"]))
            commands.append(("M" if i == 0 else "L") + f"{x:.2f},{y:.2f}")
        return " ".join(commands)

    grid = []
    for tick in range(6):
        ratio = tick / 5
        y = margin_top + (1 - ratio) * plot_h
        value = min_v + ratio * (max_v - min_v)
        grid.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#e5e7eb"/>'
        )
        grid.append(
            f'<text x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end" font-size="12" fill="#4b5563">${value:,.0f}</text>'
        )

    first_date = mr_curve[0]["date"]
    last_date = mr_curve[-1]["date"]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#ffffff"/>
  <text x="{margin_left}" y="24" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#111827">SPY strategy comparison, net of transaction fees</text>
  <g font-family="Arial, sans-serif">
    {''.join(grid)}
    <line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#9ca3af"/>
    <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#9ca3af"/>
    <path d="{path(bh_curve)}" fill="none" stroke="#2563eb" stroke-width="2.6"/>
    <path d="{path(mr_curve)}" fill="none" stroke="#dc2626" stroke-width="2.6"/>
    <text x="{margin_left}" y="{height - 30}" font-size="12" fill="#4b5563">{first_date}</text>
    <text x="{width - margin_right}" y="{height - 30}" font-size="12" text-anchor="end" fill="#4b5563">{last_date}</text>
    <line x1="{width - 260}" y1="56" x2="{width - 220}" y2="56" stroke="#dc2626" stroke-width="3"/>
    <text x="{width - 212}" y="60" font-size="13" fill="#111827">Mean reversion</text>
    <line x1="{width - 260}" y1="78" x2="{width - 220}" y2="78" stroke="#2563eb" stroke-width="3"/>
    <text x="{width - 212}" y="82" font-size="13" fill="#111827">Buy and hold</text>
  </g>
</svg>
"""
    with open(CHART_SVG, "w", newline="\n") as file:
        file.write(svg)


def main() -> None:
    rows = fetch_yahoo_chart(SYMBOL, YEARS)
    scores = zscores(rows)
    desired = desired_positions(scores)
    mean_rev = run_mean_reversion(rows, desired)
    buy_hold = run_buy_hold(rows)
    write_outputs(rows, mean_rev, buy_hold)
    print(f"Wrote {REPORT_MD}")
    print(f"Wrote {SUMMARY_CSV}")
    print(f"Wrote {EQUITY_CSV}")
    print(f"Wrote {CHART_SVG}")


if __name__ == "__main__":
    main()
