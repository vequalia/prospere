"""Recommendation engine: generates actionable suggestions from simulation results."""

from __future__ import annotations

from typing import Any

from prospere.simulation.models import SimulationParams, SimulationResult


def _add_p1_recs(
    recs: list[dict], m: Any, res: SimulationResult, p: SimulationParams
) -> None:
    if res.success_rate < 0.70:
        recs.append(
            {
                "type": "warning",
                "message_key": "sim_rec_boost_savings",
                "message_args": {},
                "why_key": "sim_rec_why_success_low",
                "why_args": {"iterations": p.iterations},
                "priority": 1,
            }
        )
    if m.final >= m.fire_target > 0:
        recs.append(
            {
                "type": "positive",
                "message_key": "sim_rec_fire_achieved",
                "message_args": {},
                "why_key": "sim_rec_why_fire_achieved",
                "why_args": {"wealth": f"{p.profile.currency}{m.final:,.0f}"},
                "priority": 1,
            }
        )
    if m.stress_pct > 25:
        recs.append(
            {
                "type": "warning",
                "message_key": "sim_rec_build_emergency_fund",
                "message_args": {},
                "why_key": "sim_rec_why_stress_high",
                "why_args": {"pct": m.stress_pct},
                "priority": 1,
            }
        )


def _add_p2_recs(recs: list[dict], m: Any, res: SimulationResult) -> None:
    if res.success_rate < 0.90 and m.savings_end < 20:
        recs.append(
            {
                "type": "action",
                "message_key": "sim_rec_boost_savings",
                "message_args": {},
                "why_key": "sim_rec_why_savings_low",
                "why_args": {"pct": m.savings_end},
                "priority": 2,
            }
        )
    if m.coverage < 50:
        recs.append(
            {
                "type": "action",
                "message_key": "sim_rec_increase_passive",
                "message_args": {},
                "why_key": "sim_rec_why_coverage_low",
                "why_args": {"pct": m.coverage},
                "priority": 2,
            }
        )
    if 0 < m.conversion_eff < 0.30:
        recs.append(
            {
                "type": "action",
                "message_key": "sim_rec_reduce_spending",
                "message_args": {},
                "why_key": "sim_rec_why_conversion_low",
                "why_args": {"pct": m.conversion_eff * 100},
                "priority": 2,
            }
        )
    if m.dispersion > 60:
        recs.append(
            {
                "type": "warning",
                "message_key": "sim_rec_diversify",
                "message_args": {},
                "why_key": "sim_rec_why_dispersion_high",
                "why_args": {"pct": m.dispersion},
                "priority": 2,
            }
        )


def _add_p3_recs(recs: list[dict], m: Any, res: SimulationResult) -> None:
    if m.erosion_pct > 30:
        recs.append(
            {
                "type": "action",
                "message_key": "sim_rec_inflation_protection",
                "message_args": {},
                "why_key": "sim_rec_why_inflation_high",
                "why_args": {"pct": m.erosion_pct},
                "priority": 3,
            }
        )
    if m.rigidity > 70:
        recs.append(
            {
                "type": "warning",
                "message_key": "sim_rec_build_emergency_fund",
                "message_args": {},
                "why_key": "sim_rec_why_rigidity_high",
                "why_args": {"pct": m.rigidity},
                "priority": 3,
            }
        )
    engs = res.account_roi_contribution
    if engs and max(engs.values()) > 0.80:
        name = max(engs.items(), key=lambda x: x[1])[0]
        recs.append(
            {
                "type": "warning",
                "message_key": "sim_rec_diversify",
                "message_args": {},
                "why_key": "sim_rec_why_concentrated",
                "why_args": {"pct": max(engs.values()) * 100, "name": name},
                "priority": 3,
            }
        )
    if res.shock_income_loss_iter_pct > 0.10:
        recs.append(
            {
                "type": "warning",
                "message_key": "sim_rec_income_protection",
                "message_args": {},
                "why_key": "sim_rec_why_income_shock",
                "why_args": {"pct": res.shock_income_loss_iter_pct},
                "priority": 3,
            }
        )


def _add_p4_recs(recs: list[dict], m: Any) -> None:
    if 0 < m.coast_years <= 5:
        recs.append(
            {
                "type": "positive",
                "message_key": "sim_rec_on_track",
                "message_args": {},
                "why_key": "sim_rec_why_savings_great",
                "why_args": {"pct": m.savings_end},
                "priority": 4,
            }
        )
    if m.savings_end > 30:
        recs.append(
            {
                "type": "positive",
                "message_key": "sim_rec_great_savings",
                "message_args": {},
                "why_key": "sim_rec_why_savings_great",
                "why_args": {"pct": m.savings_end},
                "priority": 4,
            }
        )


def generate_recommendations(
    result: SimulationResult,
    params: SimulationParams,
) -> list[dict]:
    """Generate a ranked list of recommendations based on simulation results."""
    from prospere.simulation.metrics import compute_metrics

    m = compute_metrics(result, params)
    recs: list[dict] = []

    _add_p1_recs(recs, m, result, params)
    _add_p2_recs(recs, m, result)
    _add_p3_recs(recs, m, result)
    _add_p4_recs(recs, m)

    if not recs:
        recs.append(
            {
                "type": "positive",
                "message_key": "sim_rec_on_track",
                "message_args": {},
                "why_key": "sim_rec_why_savings_great",
                "why_args": {"pct": m.savings_end},
                "priority": 5,
            }
        )

    recs.sort(key=lambda r: r["priority"])
    return recs
