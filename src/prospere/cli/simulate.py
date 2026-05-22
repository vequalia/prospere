import argparse
import io
from typing import Any

import numpy as np
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from prospere.cli.i18n import _set_language, _t
from prospere.cli.utils import format_currency
from prospere.core.constants import (
    CLIConfig,
    HealthThresholds,
    SimulationDefaults,
    UITheme,
)
from prospere.simulation.analyzer import HistoricalDataAnalyzer
from prospere.simulation.config import (
    AccountConfigurationManager,
    CategoryConfigurationManager,
)
from prospere.simulation.engine import MonteCarloSimulationEngine
from prospere.simulation.models import (
    AccountStats,
    FinancialProfile,
    GrowthPolicy,
    ScenarioMetadata,
    SimulationParams,
    SimulationResult,
)
from prospere.simulation.scenario import ScenarioRepository

# Rich console with shared theme
_sim_console = Console(theme=Theme(UITheme.THEME_DICT))


def _status_color(
    value: float, strong: float, moderate: float, inverse: bool = False
) -> str:
    """Return Rich style name based on threshold comparison."""
    if inverse:
        if value <= strong:
            return "success"
        elif value <= moderate:
            return "warning"
        return "error"
    else:
        if value >= strong:
            return "success"
        elif value >= moderate:
            return "warning"
        return "error"


def _status_icon(style: str) -> str:
    """Return a status icon for the given style."""
    return {"success": "●", "warning": "●", "error": "●"}.get(style, "●")


def _display_header(meta: ScenarioMetadata, user: str) -> None:
    width = CLIConfig.TABLE_WIDTH
    print()
    print("─" * width)
    print(f"  ✦ Prospere  ›  {user}  ›  {_t('sim_title')}  ›  {meta.name}")
    print("─" * width)

    date_range = f"{meta.start_date or 'N/A'} ➜ {meta.end_date or 'N/A'}"
    header_info = (
        f" {_t('sim_period')}: {meta.years} | "
        f"{_t('sim_ref')}: {date_range} | "
        f"{_t('sim_iterations')}: {meta.iterations:,}"
    )
    print(header_info)
    print("-" * width)


def _display_baseline(profile: FinancialProfile, meta: ScenarioMetadata) -> None:
    w = CLIConfig.TABLE_WIDTH
    print(f"\n[1] {_t('sim_baseline').upper()}")
    print("─" * w)
    income = profile.monthly_income_mean
    expense = profile.monthly_expense_mean
    net = income - expense
    margin = (net / income * 100) if income > 0 else 0
    cashflow_info = (
        f"  {_t('sim_monthly_cashflow')}: {format_currency(income)} - "
        f"{format_currency(expense)} = {format_currency(net)} ({margin:.1f}%)"
    )
    print(cashflow_info)
    initial_cap = sum(a.initial_balance for a in profile.accounts)
    print(f"  {_t('sim_initial_capital')} : {format_currency(initial_cap)}")

    if meta.growth_policy:
        inf = meta.growth_policy.inflation_rate * 100

        # Determine displayed growth rates (Dynamic vs Static)
        inc_rate = meta.growth_policy.default_income_growth * 100
        inc_label = _t("sim_salary_growth")
        if meta.growth_policy.dynamic_income_growth:
            dg = meta.growth_policy.dynamic_income_growth
            inc_label = _t("sim_dynamic_prefix") + inc_label
            inc_rate_str = (
                f"{dg.initial_rate * 100:.1f}% ➜ {dg.terminal_rate * 100:.1f}%"
            )
        else:
            inc_rate_str = f"{inc_rate:.1f}%"

        exp_rate = meta.growth_policy.default_expense_growth * 100
        exp_label = _t("sim_expense_growth_label")
        if meta.growth_policy.dynamic_expense_growth:
            dg = meta.growth_policy.dynamic_expense_growth
            exp_label = _t("sim_dynamic_prefix") + exp_label
            exp_rate_str = (
                f"{dg.initial_rate * 100:.1f}% ➜ {dg.terminal_rate * 100:.1f}%"
            )
        else:
            exp_rate_str = f"{exp_rate:.1f}%"

        assumption_info = (
            f"  {_t('sim_assumptions')}     : {_t('sim_inflation')} {inf:.1f}% | "
            f"{inc_label} {inc_rate_str}"
        )
        print(assumption_info)
        if meta.growth_policy.dynamic_expense_growth or exp_rate != 0:
            print(f"                     : {exp_label} {exp_rate_str}")


def _display_projection_journey(
    result: SimulationResult, meta: ScenarioMetadata
) -> None:
    width = CLIConfig.TABLE_WIDTH
    print(f"\n[2] {_t('sim_trajectory').upper()}")
    print("─" * width)

    data = result.percentile_50
    chars = " ▂▃▄▅▆▇█"
    steps = min(len(data), width - 30)
    sampled = [data[int(i)] for i in np.linspace(0, len(data) - 1, steps)]
    rng = max(data) - min(data) or 1
    sparkline = "".join(chars[int((v - min(sampled)) / rng * 7)] for v in sampled)
    print(
        f"  {format_currency(min(data))} | {sparkline} | {format_currency(max(data))}"
    )

    print(
        f"\n  {_t('sim_year'):<5} | "
        f"{_t('sim_plain_total_wealth'):>15} | "
        f"{_t('sim_plain_spending_power'):>18} | "
        f"{_t('sim_plain_growth_this_year'):>15}"
    )
    print("  " + "-" * (width - 4))
    months_per_year = SimulationDefaults.MONTHS_PER_YEAR

    years_to_show: list[int] = list(range(meta.years + 1))
    if meta.years > 10:
        years_to_show = sorted(list(set([0, meta.years // 2, meta.years])))

    for year in years_to_show:
        idx = min(year * months_per_year, len(result.percentile_50) - 1)
        nominal = result.percentile_50[idx]
        real = result.present_value_50[idx]
        prev_idx = max(0, idx - months_per_year)
        growth = (nominal - result.percentile_50[prev_idx]) if year > 0 else 0
        growth_str = f"+{format_currency(growth)}" if growth > 0 else "-"
        print(f"  Y{year:<4} | {nominal:>18,.0f} | {real:>18,.0f} | {growth_str:>15}")


def _text_strategic_analysis(result: SimulationResult, params: SimulationParams) -> str:
    """Strategic Analysis: performance, cash flow, goals, risks, mechanics."""
    output = io.StringIO()
    width = CLIConfig.TABLE_WIDTH
    output.write(f"\n[3] {_t('sim_plain_detailed_analysis').upper()}\n")
    output.write("-" * width + "\n")

    years = params.years
    initial = result.percentile_50[0]
    final = result.percentile_50[-1]

    multiplier = final / initial if initial > 0 else 0
    cagr = (multiplier ** (1 / years) - 1) * 100 if years > 0 and multiplier > 0 else 0
    passive_ratio = max(0, min(100, result.passive_income_coverage_50.mean() * 100))

    real_final = result.present_value_50[-1]
    erosion = final - real_final
    erosion_pct = (erosion / final * 100) if final > 0 else 0

    output.write(f"  >> {_t('sim_plain_how_wealth_grows')}\n")
    output.write(
        f"  {_t('sim_plain_annual_growth'):<24}: {cagr:.1f}% (x{multiplier:.2f})"
        f"  -- {_t('sim_plain_explain_cagr')}\n"
    )
    output.write(
        f"  {_t('sim_growth_source'):<24}: "
        f"{passive_ratio:.1f}% {_t('sim_passive')} | "
        f"{100 - passive_ratio:.1f}% {_t('sim_active')}\n"
    )

    _text_strategic_cashflow(output, result)
    _text_strategic_goals(output, result, params, final, cagr)
    _text_strategic_risks(output, result, erosion, erosion_pct)
    _text_strategic_efficiency(output, result, years, initial, final)

    if result.account_saturation_months:
        output.write(f"\n  >> {_t('sim_saturation_alerts')}\n")
        for name, months in result.account_saturation_months.items():
            output.write(
                f"  ! {name:<18}: {_t('sim_saturated_at', months)}"
                f"  -- {_t('sim_plain_explain_saturation')}\n"
            )

    output.write("-" * width + "\n")
    return output.getvalue()


def _text_strategic_cashflow(output: io.StringIO, result: SimulationResult) -> None:
    if (
        result.monthly_income_history_50.size > 0
        and result.monthly_expenses_history_50.size > 0
    ):
        inc_start, inc_end = (
            result.monthly_income_history_50[0],
            result.monthly_income_history_50[-1],
        )
        exp_start, exp_end = (
            result.monthly_expenses_history_50[0],
            result.monthly_expenses_history_50[-1],
        )
        gain_start, gain_end = (
            result.monthly_gains_history_50[0],
            result.monthly_gains_history_50[-1],
        )
        s_rate_start = (inc_start - exp_start) / inc_start * 100 if inc_start > 0 else 0
        s_rate_end = (inc_end - exp_end) / inc_end * 100 if inc_end > 0 else 0

        output.write(f"\n  >> {_t('sim_plain_cashflow_card')}\n")
        output.write(
            f"  {_t('sim_cashflow_income'):<20}: "
            f"{format_currency(inc_start)} → {format_currency(inc_end)}/mo\n"
        )
        output.write(
            f"  {_t('sim_cashflow_expense'):<20}: "
            f"{format_currency(exp_start)} → {format_currency(exp_end)}/mo\n"
        )
        output.write(
            f"  {_t('sim_cashflow_savings_rate'):<20}: "
            f"{s_rate_start:.1f}% → {s_rate_end:.1f}%\n"
        )
        if gain_end > 0:
            output.write(
                f"  {_t('sim_cashflow_passive'):<24}: "
                f"{format_currency(gain_start)} → {format_currency(gain_end)}/mo"
                f"  -- {_t('sim_plain_explain_passive')}\n"
            )
        neg_months = int(np.sum(result.net_cash_flow_50 < 0))
        if neg_months > 0:
            output.write(
                f"  {_t('sim_cashflow_stress'):<24}: "
                f"{neg_months}/{len(result.net_cash_flow_50)} mo"
                f"  -- {_t('sim_plain_explain_stress')}\n"
            )


def _text_strategic_goals(
    output: io.StringIO,
    result: SimulationResult,
    params: SimulationParams,
    final: float,
    cagr: float,
) -> None:
    years = params.years
    ann_exp_end = (
        params.profile.monthly_expense_mean
        * 12
        * ((1 + params.growth_policy.default_expense_growth) ** years)
    )
    fire_target = ann_exp_end * 25
    roi = cagr / 100
    coast_y = (
        np.log(fire_target / final) / np.log(1 + roi)
        if roi > 0 and final < fire_target
        else 0
    )
    runway_y = final / (ann_exp_end) if ann_exp_end > 0 else 0

    output.write(f"\n  >> {_t('sim_plain_goal_progress')}\n")
    cov_pct = result.passive_income_coverage_50[-1] * 100
    output.write(
        f"  {_t('sim_plain_financial_independence'):<24}: {cov_pct:.1f}%"
        f"  -- {_t('sim_plain_explain_fire')}\n"
    )
    if coast_y > 0:
        output.write(
            f"  {_t('sim_coast_fire'):<24}: {coast_y:.1f} {_t('sim_year')}"
            f"  -- {_t('sim_plain_explain_fire')}\n"
        )
    output.write(
        f"  {_t('sim_runway'):<24}: {runway_y:.1f} {_t('sim_year')}"
        f"  -- {_t('sim_plain_explain_runway')}\n"
    )


def _text_strategic_risks(
    output: io.StringIO, result: SimulationResult, erosion: float, erosion_pct: float
) -> None:
    p10, p50, p90 = (
        result.percentile_10[-1],
        result.percentile_50[-1],
        result.percentile_90[-1],
    )
    dispersion = (p90 - p10) / p50 * 100 if p50 > 0 else 0

    output.write(f"\n  >> {_t('sim_plain_what_could_go_wrong')}\n")
    output.write(
        f"  {_t('sim_inflation_drag'):<24}: "
        f"-{format_currency(erosion)} ({erosion_pct:.1f}%)"
        f"  -- {_t('sim_plain_explain_inflation')}\n"
    )
    output.write(
        f"  {_t('sim_volatility'):<24}: {dispersion:.1f}%"
        f"  -- {_t('sim_plain_explain_volatility')}\n"
    )
    shock_parts = []
    if result.shock_crash_iter_pct > 0:
        c_pct = result.shock_crash_iter_pct
        s = f"{_t('sim_shock_crash')} {c_pct:.0f}%"
        if result.shock_crash_avg_duration > 0:
            avg_d = result.shock_crash_avg_duration
            s += f" ({_t('sim_shock_avg')} {avg_d:.0f}{_t('sim_shock_mo')})"
        shock_parts.append(s)
    if result.shock_income_loss_iter_pct > 0:
        i_pct = result.shock_income_loss_iter_pct
        s = f"{_t('sim_shock_income')} {i_pct:.0f}%"
        if result.shock_income_avg_duration > 0:
            avg_d = result.shock_income_avg_duration
            s += f" ({_t('sim_shock_avg')} {avg_d:.0f}{_t('sim_shock_mo')})"
        shock_parts.append(s)
    if result.shock_expense_spike_iter_pct > 0:
        s = f"{_t('sim_shock_spike')} {result.shock_expense_spike_iter_pct:.0f}%"
        shock_parts.append(s)
    if shock_parts:
        output.write(
            f"  {_t('sim_shock_exposure'):<24}: "
            + " | ".join(shock_parts)
            + f"  -- {_t('sim_plain_explain_shock')}\n"
        )
    if result.earliest_failure_year is not None:
        output.write(
            f"  {_t('sim_earliest_failure'):<24}: "
            f"{result.earliest_failure_year:.1f} yr\n"
        )


def _text_strategic_efficiency(
    output: io.StringIO,
    result: SimulationResult,
    years: int,
    initial: float,
    final: float,
) -> None:
    output.write(f"\n  >> {_t('sim_plain_efficiency_card')}\n")
    top_engines = sorted(
        result.account_roi_contribution.items(), key=lambda x: x[1], reverse=True
    )[:3]
    engine_str = ", ".join([f"{name} ({val * 100:.1f}%)" for name, val in top_engines])
    output.write(
        f"  {_t('sim_top_engines'):<24}: {engine_str}"
        f"  -- {_t('sim_plain_explain_engines')}\n"
    )
    output.write(
        f"  {_t('sim_plain_fixed_vs_flex'):<24}: "
        f"{result.essential_expense_ratio * 100:.1f}% fixed"
        f"  -- {_t('sim_plain_explain_rigidity')}\n"
    )

    conversion_eff = (
        ((final - initial) / result.total_income_median)
        if result.total_income_median > 0
        else 0
    )
    stress_pct = (
        (result.liquidity_stress_months / (years * 12)) * 100 if years > 0 else 0
    )

    output.write(
        f"  {_t('sim_efficiency'):<24}: {conversion_eff:.2f}"
        f"  -- {_t('sim_plain_explain_conversion')}\n"
    )
    output.write(
        f"  {_t('sim_liquidity_stress'):<24}: "
        f"{result.liquidity_stress_months} {_t('sim_months')} ({stress_pct:.1f}%)"
        f"  -- {_t('sim_plain_explain_stress')}\n"
    )


def _text_outcome_analysis(result: SimulationResult, meta: ScenarioMetadata) -> str:
    output = io.StringIO()
    w = CLIConfig.TABLE_WIDTH
    output.write(f"\n[1] {_t('sim_plain_your_results').upper()}\n")
    output.write("─" * w + "\n")
    final_wealth = result.percentile_50[-1]
    p10 = result.percentile_10[-1]
    p90 = result.percentile_90[-1]
    coverage = result.passive_income_coverage_50[-1] * 100
    success = result.success_rate * 100

    output.write(
        f"  {_t('sim_plain_final_wealth_median'):<24}: "
        f"{format_currency(final_wealth)}  "
        f"({_t('sim_success_rate')}: {success:.1f}%)\n"
    )
    output.write(
        f"  {_t('sim_plain_financial_independence'):<24}: {coverage:.1f}%  "
        f"({_t('sim_plain_explain_fire')})\n"
    )
    output.write(
        f"  {_t('sim_plain_outcome_range'):<24}: "
        f"{format_currency(p10)} - {format_currency(p90)}  "
        f"({_t('sim_plain_explain_volatility')})\n"
    )
    tax_info = (
        f"  {_t('sim_taxes'):<24}: {format_currency(result.cumulative_tax_paid_50)} "
        f"({_t('sim_eff_rate')}: {result.effective_tax_rate * 100:.1f}%)"
    )
    output.write(tax_info + "\n")
    return output.getvalue()


def _text_portfolio_shift(result: SimulationResult) -> str:
    output = io.StringIO()
    width = CLIConfig.TABLE_WIDTH
    output.write(f"\n[4] {_t('sim_plain_where_money_lives').upper()}\n")
    output.write("─" * width + "\n")
    mix = result.portfolio_mix_50
    if not mix:
        return ""

    mix_header = (
        f"  {_t('sim_asset_class'):<20} | "
        f"{_t('sim_start_pct'):>10} | "
        f"{_t('sim_end_pct'):>10} | "
        f"{_t('sim_shift')}"
    )
    output.write(mix_header + "\n")
    output.write("  " + "-" * (width - 4) + "\n")

    total_start = sum(h[0] for h in mix.values())
    total_end = sum(h[-1] for h in mix.values())

    for a_type, history in sorted(mix.items()):
        s_pct = (history[0] / total_start * 100) if total_start > 0 else 0
        e_pct = (history[-1] / total_end * 100) if total_end > 0 else 0
        diff = e_pct - s_pct
        trend = "↗" if diff > 0.5 else ("↘" if diff < -0.5 else "→")
        row_info = (
            f"  {a_type.capitalize():<20} | {s_pct:>9.1f}% | "
            f"{e_pct:>9.1f}% | {trend} ({diff:>+5.1f}%)"
        )
        output.write(row_info + "\n")
    return output.getvalue()


def _text_account_holdings(result: SimulationResult) -> str:
    output = io.StringIO()

    accounts = result.account_histories_50
    roi_map = result.account_roi_contribution
    if not accounts:
        return ""

    holdings = []
    for name, history in accounts.items():
        if history[-1] <= 0:
            continue
        holdings.append((name, history[0], history[-1], roi_map.get(name, 0.0)))
    holdings.sort(key=lambda x: x[2], reverse=True)

    if not holdings:
        return ""

    output.write(f"\n  >> {_t('sim_top_holdings')}\n")
    hdr = f"  {'Account':<20} | {'Start':>10} | {'End':>10} | {'ROI Share'}"
    output.write(hdr + "\n")
    w = CLIConfig.TABLE_WIDTH
    output.write("  " + "-" * (w - 4) + "\n")

    for name, start, end, roi in holdings[:8]:
        from prospere.cli.utils import format_currency

        start_s = format_currency(start).rjust(10)
        end_s = format_currency(end).rjust(10)
        roi_s = f"{roi * 100:.1f}%".rjust(9)
        name_s = name[:20].ljust(20)
        output.write(f"  {name_s} | {start_s} | {end_s} | {roi_s}\n")

    return output.getvalue()


def generate_insight_report_text(
    result: SimulationResult,
    params: SimulationParams,
    meta: ScenarioMetadata,
) -> str:
    """Combines all analyst insights into a single text report."""
    report = []
    report.append(_text_outcome_analysis(result, meta))
    report.append(_text_strategic_analysis(result, params))
    report.append(_text_portfolio_shift(result))
    report.append(_text_account_holdings(result))
    return "\n".join(report)


def _display_distribution_histogram(result: SimulationResult) -> None:
    width = CLIConfig.TABLE_WIDTH
    print(f"\n[6] {_t('sim_plain_range_of_outcomes').upper()}")
    print("─" * width)
    print(f"  {_t('sim_plain_explain_distribution')}")
    print()
    data = result.final_wealth_distribution
    p10, p90 = np.percentile(data, [10, 90])
    dist_range = [x for x in data if p10 <= x <= p90]
    counts, edges = np.histogram(dist_range, bins=10)
    max_count = max(counts) or 1
    for i in range(len(counts)):
        bar_len = int(counts[i] / max_count * (width - 25))
        bar = "█" * bar_len
        label = f"{edges[i] / 1e3:>4.0f}K"
        print(f"  {label} | {bar}")
    print("-" * width + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Rich-based user-friendly display functions (for terminal CLI)
# ═══════════════════════════════════════════════════════════════════════════════


def _display_header_rich(meta: ScenarioMetadata, user: str) -> None:
    """Styled header with Panel — clear brand, user, scenario hierarchy."""
    date_range = f"{meta.start_date or 'N/A'} ➜ {meta.end_date or 'N/A'}"
    info = (
        f"[dim]{_t('sim_period')}: {meta.years}y  │  "
        f"{_t('sim_ref')}: {date_range}  │  "
        f"{_t('sim_iterations')}: {meta.iterations:,}[/dim]"
    )
    _sim_console.print()
    _sim_console.print(
        Panel(
            Text(f"✦ Prospere  ·  {user}  ·  {meta.name}", style="bold"),
            subtitle=info,
            border_style="accent",
            padding=(1, 2),
        )
    )


def _display_baseline_rich(profile: FinancialProfile, meta: ScenarioMetadata) -> None:
    """Plain-language baseline with Rich table."""
    income = profile.monthly_income_mean
    expense = profile.monthly_expense_mean
    net = income - expense
    margin = (net / income * 100) if income > 0 else 0
    initial_cap = sum(a.initial_balance for a in profile.accounts)

    _sim_console.print()
    _sim_console.print(Rule(_t("sim_baseline"), style="accent"))
    _sim_console.print()

    table = Table(show_header=False, box=None, padding=(0, 4, 0, 0))
    table.add_column("label", style="dim")
    table.add_column("value")
    cashflow_msg = (
        f"{format_currency(income)} - {format_currency(expense)} = "
        f"[bold]{format_currency(net)}[/bold] ({margin:.1f}%)"
    )
    table.add_row(_t("sim_monthly_cashflow"), cashflow_msg)
    table.add_row(
        _t("sim_initial_capital"),
        f"[bold]{format_currency(initial_cap)}[/bold]",
    )
    _sim_console.print(table)

    if meta.growth_policy:
        inf = meta.growth_policy.inflation_rate * 100
        inc_rate = meta.growth_policy.default_income_growth * 100
        inc_label = _t("sim_salary_growth")
        if meta.growth_policy.dynamic_income_growth:
            dg = meta.growth_policy.dynamic_income_growth
            inc_label = _t("sim_dynamic_prefix") + inc_label
            inc_rate_str = (
                f"{dg.initial_rate * 100:.1f}% ➜ {dg.terminal_rate * 100:.1f}%"
            )
        else:
            inc_rate_str = f"{inc_rate:.1f}%"

        exp_rate = meta.growth_policy.default_expense_growth * 100
        exp_label = _t("sim_expense_growth_label")
        if meta.growth_policy.dynamic_expense_growth:
            dg = meta.growth_policy.dynamic_expense_growth
            exp_label = _t("sim_dynamic_prefix") + exp_label
            exp_rate_str = (
                f"{dg.initial_rate * 100:.1f}% ➜ {dg.terminal_rate * 100:.1f}%"
            )
        else:
            exp_rate_str = f"{exp_rate:.1f}%"

        _sim_console.print(
            f"  [dim]{_t('sim_assumptions')}: "
            f"{_t('sim_inflation')} {inf:.1f}%  |  "
            f"{inc_label} {inc_rate_str}"
        )
        if meta.growth_policy.dynamic_expense_growth or exp_rate != 0:
            _sim_console.print(f"                     {exp_label} {exp_rate_str}")


def _display_summary_rich(result: SimulationResult, meta: ScenarioMetadata) -> None:
    """[1] Your Results at a Glance — 2-column layout, auto-width."""
    final = result.percentile_50[-1]
    p10 = result.percentile_10[-1]
    p90 = result.percentile_90[-1]
    success = result.success_rate * 100
    coverage = result.passive_income_coverage_50[-1] * 100
    cagr_val = _calc_cagr(result.percentile_50, meta.years)
    currency = meta.currency

    success_style = _status_color(
        success,
        HealthThresholds.SUCCESS_STRONG * 100,
        HealthThresholds.SUCCESS_MODERATE * 100,
    )
    coverage_style = _status_color(
        coverage, HealthThresholds.COVERAGE_STRONG, HealthThresholds.COVERAGE_MODERATE
    )

    _sim_console.print()
    _sim_console.print(Rule(_t("sim_plain_your_results"), style="accent"))

    summary = Table(
        show_header=False, box=box.SIMPLE, border_style="dim", padding=(0, 3)
    )
    summary.add_column(style="dim", width=22)
    summary.add_column(style="bold")

    summary.add_row(_t("sim_plain_most_likely"), f"{currency}{final:,.0f}")
    summary.add_row("", Text(_t("sim_plain_explain_cagr"), style="dim italic"))
    summary.add_row(
        _t("sim_success_rate"), Text(f"{success:.1f}%", style=success_style)
    )
    summary.add_row("", Text(_t("sim_plain_explain_success"), style="dim italic"))
    summary.add_row(
        _t("sim_plain_financial_independence"),
        Text(f"{coverage:.1f}%", style=coverage_style),
    )
    summary.add_row("", Text(_t("sim_plain_explain_fire"), style="dim italic"))
    summary.add_row(
        _t("sim_plain_outcome_range"), f"{currency}{p10:,.0f}  →  {currency}{p90:,.0f}"
    )
    summary.add_row("", Text(_t("sim_plain_explain_volatility"), style="dim italic"))

    _sim_console.print(summary)
    tax_val = f"{currency}{result.cumulative_tax_paid_50:,.0f}"
    eff_rate_val = f"{result.effective_tax_rate * 100:.1f}%"
    tax_msg = f"[dim]{_t('sim_taxes')}[/dim] [bold]{tax_val}[/bold]"
    rate_msg = f"([dim]{_t('sim_eff_rate')}: {eff_rate_val}[/dim])"
    growth_label = _t("sim_plain_annual_growth")
    _sim_console.print(
        f"  [dim]{growth_label}[/dim]  [bold]{cagr_val:.1f}%[/bold]  │  "
        f"{tax_msg}  {rate_msg}"
    )


def _display_trajectory_rich(result: SimulationResult, meta: ScenarioMetadata) -> None:
    """[2] Wealth trajectory with sparkline and plain-language table."""
    _sim_console.print()
    _sim_console.print(Rule(_t("sim_trajectory"), style="accent"))
    _sim_console.print()

    data = result.percentile_50
    import shutil

    term_w = shutil.get_terminal_size().columns
    chars = " ▂▃▄▅▆▇█"
    steps = min(len(data), term_w - 30)
    sampled = [data[int(i)] for i in np.linspace(0, len(data) - 1, steps)]
    rng = max(data) - min(data) or 1
    sparkline = "".join(chars[int((v - min(sampled)) / rng * 7)] for v in sampled)
    _sim_console.print(
        f"  {format_currency(min(data))} | {sparkline} | {format_currency(max(data))}"
    )
    _sim_console.print()

    months_per_year = SimulationDefaults.MONTHS_PER_YEAR
    years_to_show: list[int] = list(range(meta.years + 1))
    if meta.years > 10:
        years_to_show = sorted(list(set([0, meta.years // 2, meta.years])))

    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column(_t("sim_year"), style="dim")
    table.add_column(_t("sim_plain_total_wealth"), justify="right")
    table.add_column(_t("sim_plain_spending_power"), justify="right")
    table.add_column(_t("sim_plain_growth_this_year"), justify="right")

    for year in years_to_show:
        idx = min(year * months_per_year, len(result.percentile_50) - 1)
        nominal = result.percentile_50[idx]
        real = result.present_value_50[idx]
        prev_idx = max(0, idx - months_per_year)
        growth = (nominal - result.percentile_50[prev_idx]) if year > 0 else 0
        growth_str = f"+{format_currency(growth)}" if growth > 0 else "-"
        table.add_row(f"Y{year}", f"{nominal:,.0f}", f"{real:,.0f}", growth_str)

    _sim_console.print(table)


def _display_analysis_rich(result: SimulationResult, params: SimulationParams) -> None:
    """[3] Detailed Analysis — table-based layout with clear typographic hierarchy."""
    from prospere.simulation.metrics import compute_metrics

    m = compute_metrics(result, params)
    currency = params.profile.currency

    _sim_console.print()
    _sim_console.print(Rule(_t("sim_plain_detailed_analysis"), style="accent"))

    _display_analysis_growth_rich(m)
    if m.has_cashflow:
        _display_analysis_cashflow_rich(m, result, currency)
    _display_analysis_goals_rich(m)
    _display_analysis_risks_rich(m, result, currency)
    _display_analysis_efficiency_rich(m, result, currency)

    if result.account_saturation_months:
        _sim_console.print()
        sat_table = Table(
            show_header=False, box=box.SIMPLE, border_style="warning", padding=(0, 3)
        )
        sat_table.add_column("account", style="bold warning")
        sat_table.add_column("detail")
        for name, months in result.account_saturation_months.items():
            exp_key = "sim_plain_explain_saturation"
            msg = f"{_t('sim_saturated_at', months)}  —  {_t(exp_key)}"
            sat_table.add_row(name, msg)
        _sim_console.print(sat_table)


def _print_group(title: str, rows: list[tuple[str, str, str]]) -> None:
    """Print a group title followed by a clean label-value table."""
    _sim_console.print()
    _sim_console.print(Text(title, style="bold"))
    t = Table(show_header=False, box=box.SIMPLE, border_style="dim", padding=(0, 2))
    t.add_column(style="dim", width=20)
    t.add_column(style="bold")
    for label, value, explain in rows:
        t.add_row(label, value)
        if explain:
            t.add_row("", Text(explain, style="dim italic"))
    _sim_console.print(t)


def _display_analysis_growth_rich(m: Any) -> None:
    _print_group(
        _t("sim_plain_how_wealth_grows"),
        [
            (
                _t("sim_plain_annual_growth"),
                f"{m.cagr:.1f}%  (x{m.multiplier:.2f})",
                _t("sim_plain_explain_cagr"),
            ),
            (
                _t("sim_growth_source"),
                f"{m.passive_ratio:.1f}% {_t('sim_passive')}  |  "
                f"{100 - m.passive_ratio:.1f}% {_t('sim_active')}",
                "",
            ),
        ],
    )


def _display_analysis_cashflow_rich(
    m: Any, result: SimulationResult, currency: str
) -> None:
    savings_style = _status_color(
        (1 - m.rigidity / 100) * 100 if m.rigidity < 100 else 0,
        HealthThresholds.SAVINGS_STRONG,
        HealthThresholds.SAVINGS_MODERATE,
    )
    stress_style = _status_color(
        m.stress_pct,
        HealthThresholds.STRESS_LOW,
        HealthThresholds.STRESS_HIGH,
        inverse=True,
    )
    rows = [
        (
            _t("sim_cashflow_income"),
            f"{currency}{m.inc_start:,.0f}  →  {currency}{m.inc_end:,.0f} /mo",
            "",
        ),
        (
            _t("sim_cashflow_expense"),
            f"{currency}{m.exp_start:,.0f}  →  {currency}{m.exp_end:,.0f} /mo",
            "",
        ),
        (
            _t("sim_cashflow_savings_rate"),
            f"[{savings_style}]{m.savings_start:.1f}%  →  "
            f"{m.savings_end:.1f}%[/{savings_style}]",
            "",
        ),
    ]
    if m.gain_end > 0:
        rows.append(
            (
                _t("sim_cashflow_passive"),
                f"{currency}{m.gain_start:,.0f}  →  {currency}{m.gain_end:,.0f} /mo",
                _t("sim_plain_explain_passive"),
            )
        )
    if m.neg_months > 0:
        rows.append(
            (
                _t("sim_cashflow_stress"),
                f"[{stress_style}]{m.neg_months}/{len(result.net_cash_flow_50)} "
                f"mo[/{stress_style}]",
                _t("sim_plain_explain_stress"),
            )
        )
    _print_group(_t("sim_plain_cashflow_card"), rows)


def _display_analysis_goals_rich(m: Any) -> None:
    coverage_style = _status_color(
        m.coverage, HealthThresholds.COVERAGE_STRONG, HealthThresholds.COVERAGE_MODERATE
    )
    g_rows = [
        (
            _t("sim_plain_financial_independence"),
            f"[{coverage_style}]{m.coverage:.1f}%[/{coverage_style}]",
            _t("sim_plain_explain_fire"),
        ),
    ]
    if m.coast_years > 0:
        g_rows.append(
            (
                _t("sim_coast_fire"),
                f"{m.coast_years:.1f} {_t('sim_year')}",
                _t("sim_plain_explain_fire"),
            )
        )
    g_rows.append(
        (
            _t("sim_runway"),
            f"{m.runway_years:.1f} {_t('sim_year')}",
            _t("sim_plain_explain_runway"),
        )
    )
    _print_group(_t("sim_plain_goal_progress"), g_rows)


def _display_analysis_risks_rich(
    m: Any, result: SimulationResult, currency: str
) -> None:
    dispersion_style = _status_color(
        m.dispersion,
        HealthThresholds.VOLATILITY_LOW,
        HealthThresholds.VOLATILITY_HIGH,
        inverse=True,
    )
    erosion_style = _status_color(
        m.erosion_pct,
        HealthThresholds.INFLATION_DRAG_HIGH / 2,
        HealthThresholds.INFLATION_DRAG_HIGH,
        inverse=True,
    )
    shock_parts = []
    if result.shock_crash_iter_pct > 0:
        c_pct = result.shock_crash_iter_pct
        s = f"{_t('sim_shock_crash')} {c_pct:.0f}%"
        if result.shock_crash_avg_duration > 0:
            avg_d = result.shock_crash_avg_duration
            s += f" ({_t('sim_shock_avg')} {avg_d:.0f}{_t('sim_shock_mo')})"
        shock_parts.append(s)
    if result.shock_income_loss_iter_pct > 0:
        i_pct = result.shock_income_loss_iter_pct
        s = f"{_t('sim_shock_income')} {i_pct:.0f}%"
        if result.shock_income_avg_duration > 0:
            avg_d = result.shock_income_avg_duration
            s += f" ({_t('sim_shock_avg')} {avg_d:.0f}{_t('sim_shock_mo')})"
        shock_parts.append(s)
    if result.shock_expense_spike_iter_pct > 0:
        s = f"{_t('sim_shock_spike')} {result.shock_expense_spike_iter_pct:.0f}%"
        shock_parts.append(s)
    shock_str = " | ".join(shock_parts) if shock_parts else "-"

    r_rows = [
        (
            _t("sim_inflation_drag"),
            f"[{erosion_style}]-{currency}{m.erosion:,.0f}  "
            f"({m.erosion_pct:.1f}%)[/{erosion_style}]",
            _t("sim_plain_explain_inflation"),
        ),
        (
            _t("sim_volatility"),
            f"[{dispersion_style}]{m.dispersion:.1f}%[/{dispersion_style}]",
            _t("sim_plain_explain_volatility"),
        ),
        (_t("sim_shock_exposure"), shock_str, _t("sim_plain_explain_shock")),
    ]
    if result.earliest_failure_year is not None:
        r_rows.append(
            (_t("sim_earliest_failure"), f"{result.earliest_failure_year:.1f} yr", "")
        )
    _print_group(_t("sim_plain_what_could_go_wrong"), r_rows)


def _display_analysis_efficiency_rich(
    m: Any, result: SimulationResult, currency: str
) -> None:
    rigidity_style = _status_color(
        m.rigidity,
        HealthThresholds.RIGIDITY_LOW,
        HealthThresholds.RIGIDITY_HIGH,
        inverse=True,
    )
    stress_style = _status_color(
        m.stress_pct,
        HealthThresholds.STRESS_LOW,
        HealthThresholds.STRESS_HIGH,
        inverse=True,
    )
    conversion_style = _status_color(
        m.conversion_eff,
        HealthThresholds.CONVERSION_STRONG,
        HealthThresholds.CONVERSION_MODERATE,
    )
    e_rows = []
    if m.top_engines:
        engine_str = ", ".join([f"{n} ({v * 100:.1f}%)" for n, v in m.top_engines])
        e_rows.append(
            (_t("sim_top_engines"), engine_str, _t("sim_plain_explain_engines"))
        )
    e_rows += [
        (
            _t("sim_plain_fixed_vs_flex"),
            f"[{rigidity_style}]{m.rigidity:.1f}% fixed[/{rigidity_style}]",
            _t("sim_plain_explain_rigidity"),
        ),
        (
            _t("sim_efficiency"),
            f"[{conversion_style}]{m.conversion_eff:.2f}[/{conversion_style}]",
            _t("sim_plain_explain_conversion"),
        ),
        (
            _t("sim_liquidity_stress"),
            f"[{stress_style}]{result.liquidity_stress_months} "
            f"{_t('sim_months')}  ({m.stress_pct:.1f}%)[/{stress_style}]",
            _t("sim_plain_explain_stress"),
        ),
    ]
    _print_group(_t("sim_plain_efficiency_card"), e_rows)


def _display_portfolio_rich(result: SimulationResult) -> None:
    """[4] Portfolio evolution with plain-language labels."""
    mix = result.portfolio_mix_50
    if not mix:
        return

    _sim_console.print()
    _sim_console.print(Rule(_t("sim_plain_where_money_lives"), style="accent"))
    _sim_console.print()

    total_start = sum(h[0] for h in mix.values())
    total_end = sum(h[-1] for h in mix.values())

    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column(_t("sim_asset_class"))
    table.add_column(_t("sim_start_pct"), justify="right")
    table.add_column(_t("sim_end_pct"), justify="right")
    table.add_column(_t("sim_shift"), justify="right")

    for a_type, history in sorted(mix.items()):
        s_pct = (history[0] / total_start * 100) if total_start > 0 else 0
        e_pct = (history[-1] / total_end * 100) if total_end > 0 else 0
        diff = e_pct - s_pct
        trend = "↗" if diff > 0.5 else ("↘" if diff < -0.5 else "→")
        style = "success" if diff > 0.5 else ("error" if diff < -0.5 else "")
        diff_str = (
            f"[{style}]{trend} {diff:+.1f}%[/{style}]"
            if style
            else f"{trend} {diff:+.1f}%"
        )
        table.add_row(a_type.capitalize(), f"{s_pct:.1f}%", f"{e_pct:.1f}%", diff_str)

    _sim_console.print(table)

    accounts = result.account_histories_50
    roi_map = result.account_roi_contribution
    if accounts:
        holdings = []
        for name, history in accounts.items():
            if history[-1] <= 0:
                continue
            holdings.append((name, history[0], history[-1], roi_map.get(name, 0.0)))
        holdings.sort(key=lambda x: x[2], reverse=True)

        if holdings:
            _sim_console.print(f"\n  [bold]{_t('sim_top_holdings')}[/bold]")
            h_table = Table(show_header=True, box=None, padding=(0, 2))
            h_table.add_column(_t("sim_holdings_account"))
            h_table.add_column(_t("sim_holdings_start"), justify="right")
            h_table.add_column(_t("sim_holdings_end"), justify="right")
            h_table.add_column(_t("sim_holdings_roi"), justify="right")
            for name, start, end, roi in holdings[:8]:
                h_table.add_row(
                    name[:20],
                    format_currency(start),
                    format_currency(end),
                    f"{roi * 100:.1f}%",
                )
            _sim_console.print(h_table)


def _display_distribution_rich(result: SimulationResult) -> None:
    """[6] Distribution histogram with plain-language title."""
    _sim_console.print()
    _sim_console.print(Rule(_t("sim_plain_range_of_outcomes"), style="accent"))
    _sim_console.print()
    _sim_console.print(
        f"  [dim italic]{_t('sim_plain_explain_distribution')}[/dim italic]"
    )
    _sim_console.print()

    import shutil

    term_w = shutil.get_terminal_size().columns
    data = result.final_wealth_distribution
    p10, p90 = np.percentile(data, [10, 90])
    dist_range = [x for x in data if p10 <= x <= p90]
    counts, edges = np.histogram(dist_range, bins=10)
    max_count = max(counts) or 1
    for i in range(len(counts)):
        bar_len = int(counts[i] / max_count * (term_w - 25))
        bar = "█" * bar_len
        label = f"{edges[i] / 1e3:>4.0f}K"
        _sim_console.print(f"  {label} | {bar}")
    _sim_console.print("─" * term_w)


def _display_recommendations_rich(
    result: SimulationResult, params: SimulationParams
) -> None:
    """[6] Auto-generated recommendations."""
    from prospere.simulation.recommendations import generate_recommendations

    recs = generate_recommendations(result, params)
    if not recs:
        return

    _sim_console.print()
    _sim_console.print(Rule(_t("sim_rec_title"), style="accent"))
    _sim_console.print(f"  [dim italic]{_t('sim_rec_intro')}[/dim italic]")
    _sim_console.print()

    icon_map = {
        "positive": "[success]✓[/success]",
        "warning": "[warning]⚠[/warning]",
        "action": "[accent]→[/accent]",
    }
    for rec in recs[:5]:
        icon = icon_map.get(rec["type"], "•")
        msg = _t(rec["message_key"], **rec.get("message_args", {}))
        _sim_console.print(f"  {icon}  {msg}")
        if rec.get("why_key"):
            why = _t(rec["why_key"], **rec.get("why_args", {}))
            _sim_console.print(f"     [dim]Why: {why}[/dim]")
    _sim_console.print()


def _calc_cagr(wealth_path: np.ndarray, years: int) -> float:
    """Calculate CAGR from a wealth trajectory."""
    initial = wealth_path[0]
    final = wealth_path[-1]
    multiplier = final / initial if initial > 0 else 0
    return (
        (multiplier ** (1 / years) - 1) * 100 if years > 0 and multiplier > 0 else 0.0
    )


def run_simulation_cli() -> None:
    parser = argparse.ArgumentParser(description="Prospere Financial Forecasting")
    parser.add_argument("--user", type=str, default="default_user")
    parser.add_argument("--scenario", type=str, default="adhoc")
    parser.add_argument("--years", type=int, default=SimulationDefaults.YEARS)
    parser.add_argument("--iterations", type=int, default=SimulationDefaults.ITERATIONS)
    parser.add_argument(
        "--html", action="store_true", help="Generate a minimalist HTML report"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="en",
        choices=["en", "zh", "zh-Hant", "zh-Hans"],
        help="Language for CLI output",
    )
    args = parser.parse_args()

    _set_language(args.lang)

    from prospere.core.models import WorkspaceContext
    from prospere.core.workspace import WorkspaceManager

    context = WorkspaceContext(user=args.user, scenario=args.scenario)
    ws_manager = WorkspaceManager(context)

    repo = ScenarioRepository(ws_manager=ws_manager)
    try:
        meta = repo.retrieve_scenario_metadata(args.scenario)
    except FileNotFoundError:
        if args.scenario == "adhoc":
            meta = ScenarioMetadata(
                name="adhoc",
                initial_capital=0.0,
                years=args.years,
                iterations=args.iterations,
            )
        else:
            raise

    context = WorkspaceContext(
        user=args.user, snapshot=meta.snapshot_name, scenario=args.scenario
    )
    ws_manager = WorkspaceManager(context)

    config_paths = repo.get_configuration_file_paths(meta.name)
    cat_mgr = CategoryConfigurationManager(config_paths["category_config"])
    acc_mgr = AccountConfigurationManager(config_paths["account_config"])
    cat_mgr.load_from_disk()
    acc_mgr.load_from_disk()

    data_path = ws_manager.get_dataset_path("processed_transactions.xlsx")
    analyzer = HistoricalDataAnalyzer(data_path)
    profile = analyzer.construct_financial_profile(
        currency=meta.currency,
        start_date=meta.start_date,
        end_date=meta.end_date,
        category_config=cat_mgr,
        account_config=acc_mgr,
    )

    initial_cap_sum = sum(a.initial_balance for a in profile.accounts)
    if abs(initial_cap_sum - meta.initial_capital) > 1.0 and meta.initial_capital > 0:
        factor = meta.initial_capital / initial_cap_sum
        profile = FinancialProfile(
            profile.monthly_income_mean,
            profile.monthly_income_std,
            profile.monthly_expense_mean,
            profile.monthly_expense_std,
            profile.currency,
            profile.categories,
            [
                AccountStats(
                    a.name,
                    a.account_type,
                    a.annual_return,
                    a.monthly_net_flow_mean,
                    a.monthly_net_flow_std,
                    a.allocation_ratio,
                    a.annual_return_std,
                    a.max_balance,
                    a.deposit_priority,
                    a.initial_balance * factor,
                    a.currency,
                    a.asset_class,
                )
                for a in profile.accounts
            ],
        )

    sim_params = SimulationParams(
        initial_capital=sum(a.initial_balance for a in profile.accounts),
        years=meta.years,
        iterations=meta.iterations,
        profile=profile,
        growth_policy=meta.growth_policy or GrowthPolicy(0.0, 0.0),
        scenario_metadata=meta,
    )

    _display_header_rich(meta, args.user)
    _display_baseline_rich(profile, meta)

    print(f"\n[{_t('sim_running', meta.iterations)}]")
    result = MonteCarloSimulationEngine().execute_projection(sim_params)

    _display_summary_rich(result, meta)
    _display_trajectory_rich(result, meta)
    _display_analysis_rich(result, sim_params)
    _display_portfolio_rich(result)
    _display_distribution_rich(result)
    _display_recommendations_rich(result, sim_params)

    export_path = repo.export_simulation_result(meta.name, result)
    print(f"{_t('sim_report_exported')}: {export_path}")

    opt_path = repo.export_optimization_context(meta.name, result, sim_params)
    print(f"{_t('sim_opt_context_exported')}: {opt_path}")

    if args.html:
        html_path = repo.export_html_report(
            meta.name, result, sim_params, template_lang=args.lang, user_name=args.user
        )
        print(_t("sim_html_report_exported", html_path))


if __name__ == "__main__":
    run_simulation_cli()
