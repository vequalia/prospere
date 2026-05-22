"""Shared derived metrics computed from simulation results."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prospere.simulation.models import SimulationParams, SimulationResult


@dataclass
class ComputedMetrics:
    """All derived metrics computed once from a SimulationResult + params."""

    final: float
    p10: float
    p50: float
    p90: float
    cagr: float
    multiplier: float
    coverage: float
    passive_ratio: float
    erosion: float
    erosion_pct: float
    dispersion: float
    annual_expenses_end: float
    fire_target: float
    coast_years: float
    runway_years: float
    conversion_eff: float
    stress_pct: float
    rigidity: float
    success: float
    top_engines: list[tuple[str, float]]
    savings_start: float
    savings_end: float
    inc_start: float
    inc_end: float
    exp_start: float
    exp_end: float
    gain_start: float
    gain_end: float
    has_cashflow: bool
    neg_months: int


def compute_metrics(
    result: SimulationResult, params: SimulationParams
) -> ComputedMetrics:
    """Compute all derived metrics from a simulation result."""
    years = params.years
    initial = result.percentile_50[0]
    final = result.percentile_50[-1]

    multiplier = final / initial if initial > 0 else 0
    cagr = (
        (multiplier ** (1 / years) - 1) * 100 if years > 0 and multiplier > 0 else 0.0
    )

    passive_ratio = max(0, min(100, result.passive_income_coverage_50.mean() * 100))
    coverage = result.passive_income_coverage_50[-1] * 100

    real_final = result.present_value_50[-1]
    erosion = final - real_final
    erosion_pct = (erosion / final * 100) if final > 0 else 0

    p10, p50, p90 = (
        result.percentile_10[-1],
        result.percentile_50[-1],
        result.percentile_90[-1],
    )
    dispersion = (p90 - p10) / p50 * 100 if p50 > 0 else 0

    annual_expenses_end = (
        params.profile.monthly_expense_mean
        * 12
        * ((1 + params.growth_policy.default_expense_growth) ** years)
    )
    fire_target = annual_expenses_end * 25
    avg_annual_roi = cagr / 100
    coast_years = (
        np.log(fire_target / final) / np.log(1 + avg_annual_roi)
        if avg_annual_roi > 0 and final < fire_target
        else 0
    )
    runway_years = final / annual_expenses_end if annual_expenses_end > 0 else 0

    total_wealth_gain = final - initial
    conversion_eff = (
        total_wealth_gain / result.total_income_median
        if result.total_income_median > 0
        else 0
    )
    stress_pct = (
        (result.liquidity_stress_months / (years * 12)) * 100 if years > 0 else 0
    )
    rigidity = result.essential_expense_ratio * 100
    success = result.success_rate * 100

    top_engines = sorted(
        result.account_roi_contribution.items(), key=lambda x: x[1], reverse=True
    )[:3]

    # Cash flow data
    inc_hist = result.monthly_income_history_50
    exp_hist = result.monthly_expenses_history_50
    has_cashflow = inc_hist.size > 0 and exp_hist.size > 0
    if has_cashflow:
        inc_start, inc_end = inc_hist[0], inc_hist[-1]
        exp_start, exp_end = exp_hist[0], exp_hist[-1]
        gain_start = result.monthly_gains_history_50[0]
        gain_end = result.monthly_gains_history_50[-1]
        s_start = (inc_start - exp_start) / inc_start * 100 if inc_start > 0 else 0
        s_end = (inc_end - exp_end) / inc_end * 100 if inc_end > 0 else 0
        neg_months = int(np.sum(result.net_cash_flow_50 < 0))
    else:
        inc_start = inc_end = exp_start = exp_end = 0.0
        gain_start = gain_end = 0.0
        s_start = s_end = 0.0
        neg_months = 0

    return ComputedMetrics(
        final=final,
        p10=p10,
        p50=p50,
        p90=p90,
        cagr=cagr,
        multiplier=multiplier,
        coverage=coverage,
        passive_ratio=passive_ratio,
        erosion=erosion,
        erosion_pct=erosion_pct,
        dispersion=dispersion,
        annual_expenses_end=annual_expenses_end,
        fire_target=fire_target,
        coast_years=coast_years,
        runway_years=runway_years,
        conversion_eff=conversion_eff,
        stress_pct=stress_pct,
        rigidity=rigidity,
        success=success,
        top_engines=top_engines,
        savings_start=s_start,
        savings_end=s_end,
        inc_start=inc_start,
        inc_end=inc_end,
        exp_start=exp_start,
        exp_end=exp_end,
        gain_start=gain_start,
        gain_end=gain_end,
        has_cashflow=has_cashflow,
        neg_months=neg_months,
    )
