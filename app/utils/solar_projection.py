"""
20-year utility cost projection for preliminary solar reports.

Numbers are indicative for design/preview; they can be tuned later.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YearProjection:
    year: int
    monthly: float
    annual: float
    cumulative: float


@dataclass(frozen=True)
class SolarProjection:
    monthly_bill: float
    years: list[YearProjection]
    total_20yr: float
    solar_payments_20yr: float
    savings_low: float
    savings_high: float
    chart_years: list[int]
    chart_annuals: list[float]


def _money(n: float) -> str:
    return f"${n:,.0f}"


def format_money(n: float) -> str:
    return _money(n)


def format_savings_range(low: float, high: float) -> str:
    """Display as ~$55K – $65K style."""

    def _k(v: float) -> str:
        k = round(v / 1000)
        return f"${k}K"

    return f"~{_k(low)} – {_k(high)}"


def build_projection(
    monthly_bill: float,
    *,
    annual_increase: float = 0.05,
    solar_monthly_factor: float = 158.4,
    years: int = 20,
) -> SolarProjection:
    """
    Escalate monthly bill by annual_increase each year.

    Solar 20-yr payments ≈ monthly_bill * solar_monthly_factor
    (calibrated to the sample: $250 → $39,600).
    """
    rows: list[YearProjection] = []
    monthly = float(monthly_bill)
    cumulative = 0.0
    for year in range(1, years + 1):
        annual = monthly * 12.0
        cumulative += annual
        rows.append(
            YearProjection(
                year=year,
                monthly=round(monthly),
                annual=round(annual),
                cumulative=round(cumulative),
            )
        )
        monthly *= 1.0 + annual_increase

    total = rows[-1].cumulative if rows else 0.0
    solar = round(float(monthly_bill) * solar_monthly_factor)
    savings = max(total - solar, 0.0)
    # Bracket savings for display (same style as sample ~$55K–$65K)
    savings_low = round(savings - 5000, -3)
    savings_high = round(savings + 5000, -3)

    chart_years = [1, 5, 10, 15, 20]
    chart_annuals = [
        next(r.annual for r in rows if r.year == y) for y in chart_years if any(r.year == y for r in rows)
    ]

    return SolarProjection(
        monthly_bill=float(monthly_bill),
        years=rows,
        total_20yr=total,
        solar_payments_20yr=solar,
        savings_low=max(savings_low, 0),
        savings_high=max(savings_high, savings_low),
        chart_years=chart_years,
        chart_annuals=chart_annuals,
    )
