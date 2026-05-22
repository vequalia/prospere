import json
import locale
from datetime import datetime
from typing import Any

import numpy as np

from prospere.cli.i18n import _set_language, _t
from prospere.core.constants import AccountType, HealthThresholds, SimulationDefaults
from prospere.simulation.metrics import compute_metrics
from prospere.simulation.models import (
    ScenarioMetadata,
    SimulationParams,
    SimulationResult,
)


def _status_badge_css(
    val: float, strong: float, moderate: float, inverse: bool = False
) -> str:
    """Return CSS class for color-coded badge based on threshold."""
    if inverse:
        if val <= strong:
            return "badge-green"
        if val <= moderate:
            return "badge-yellow"
        return "badge-red"
    if val >= strong:
        return "badge-green"
    if val >= moderate:
        return "badge-yellow"
    return "badge-red"


class HTMLExporter:
    """Generates a high-end HTML report with 100% parity with CLI output."""

    def __init__(self, template_lang: str = "en"):
        self.lang = template_lang
        _set_language(template_lang)

    def _format_currency(
        self, val: float, currency: str = "€", show_symbol: bool = True
    ) -> str:
        """Format currency for HTML output."""
        if not show_symbol:
            return f"{val:,.0f}"
        return f"{currency}{val:,.0f}"

    def _generate_portfolio_table_html(self, result: SimulationResult) -> str:
        """Compatibility method for tests. Matches CLI portfolio shift table."""
        mix = result.portfolio_mix_50
        if not mix:
            msg = _t("sim_no_portfolio_data")
            return f"<div class='card'><p class='text-muted'>{msg}</p></div>"

        total_start = sum(h[0] for h in mix.values())
        total_end = sum(h[-1] for h in mix.values())
        rows = []
        for a_type, history in sorted(mix.items()):
            s_pct = (history[0] / total_start * 100) if total_start > 0 else 0
            e_pct = (history[-1] / total_end * 100) if total_end > 0 else 0
            diff = e_pct - s_pct
            is_debt = a_type.lower() in [
                AccountType.DEBT.value,
                AccountType.CREDIT.value,
            ]

            if is_debt:
                icon = "↘" if diff < -0.5 else ("↗" if diff > 0.5 else "→")
                cls = (
                    "trend-up" if diff < -0.5 else ("trend-down" if diff > 0.5 else "")
                )
            else:
                icon = "↗" if diff > 0.5 else ("↘" if diff < -0.5 else "→")
                cls = (
                    "trend-up" if diff > 0.5 else ("trend-down" if diff < -0.5 else "")
                )

            rows.append(
                f"<tr><td>{a_type.capitalize()}</td><td>{s_pct:.1f}%</td>"
                f"<td>{e_pct:.1f}%</td><td class='{cls}'>{icon} {diff:+.1f}%"
                f"</td></tr>"
            )
        header = (
            f"<thead><tr><th>{_t('sim_asset_class')}</th>"
            f"<th>{_t('sim_start_pct')}</th><th>{_t('sim_end_pct')}</th>"
            f"<th>{_t('sim_shift')}</th></tr></thead>"
        )
        return f"<table>{header}<tbody>{''.join(rows)}</tbody></table>"

    def _build_trajectory_rows(
        self, result: SimulationResult, years: int, currency: str
    ) -> str:
        """Build rows for the trajectory table with CLI logic."""
        rows = []
        months_py = SimulationDefaults.MONTHS_PER_YEAR
        years_to_show = list(range(years + 1))
        if years > 12:
            years_to_show = sorted(list(set([0, years // 2, years])))

        for y in years_to_show:
            idx = min(y * months_py, len(result.percentile_50) - 1)
            nom = result.percentile_50[idx]
            real = result.present_value_50[idx]
            prev_idx = max(0, idx - months_py)
            growth = (nom - result.percentile_50[prev_idx]) if y > 0 else 0
            growth_s = (
                f"+{self._format_currency(growth, currency, False)}"
                if growth > 0
                else "-"
            )
            v_nom = self._format_currency(nom, currency, False)
            v_real = self._format_currency(real, currency, False)
            rows.append(
                f"<tr><td>Y{y}</td><td>{v_nom}</td>"
                f"<td>{v_real}</td>"
                f"<td>{growth_s}</td></tr>"
            )
        return "".join(rows)

    def _build_holdings_rows(self, result: SimulationResult, currency: str) -> str:
        """Build top holdings rows for the report."""
        rows = []
        acc_histories = result.account_histories_50
        roi_map = result.account_roi_contribution
        if not acc_histories:
            return ""
        holdings = []
        for name, h in acc_histories.items():
            if h[-1] <= 0 and h[0] <= 0:
                continue
            holdings.append((name, h[0], h[-1], roi_map.get(name, 0.0)))
        holdings.sort(key=lambda x: x[2], reverse=True)
        for name, start, end, roi in holdings[:8]:
            rows.append(
                f"<tr><td>{name[:25]}</td>"
                f"<td>{self._format_currency(start, currency, False)}</td>"
                f"<td>{self._format_currency(end, currency, False)}</td>"
                f"<td>{roi * 100:.1f}%</td></tr>"
            )
        return "".join(rows)

    def _format_shock_str(self, result: SimulationResult) -> str:
        """Format shock exposure string for the report."""
        parts = []
        if result.shock_crash_iter_pct > 0:
            val = result.shock_crash_iter_pct
            parts.append(f"{_t('sim_shock_crash')} {val:.0f}%")
        if result.shock_income_loss_iter_pct > 0:
            val = result.shock_income_loss_iter_pct
            parts.append(f"{_t('sim_shock_income')} {val:.0f}%")
        if result.shock_expense_spike_iter_pct > 0:
            val = result.shock_expense_spike_iter_pct
            parts.append(f"{_t('sim_shock_spike')} {val:.0f}%")
        return " | ".join(parts) if parts else "-"

    def generate(
        self,
        result: SimulationResult,
        metadata: ScenarioMetadata,
        params: SimulationParams,
        output_path: str,
        user_name: str = "User",
    ) -> str:
        """Generates the premium HTML report with perfect CLI parity."""
        m = compute_metrics(result, params)
        currency = params.profile.currency
        years = params.years

        s_b = _status_badge_css(
            result.success_rate * 100,
            HealthThresholds.SUCCESS_STRONG * 100,
            HealthThresholds.SUCCESS_MODERATE * 100,
        )
        c_b = _status_badge_css(
            m.coverage,
            HealthThresholds.COVERAGE_STRONG,
            HealthThresholds.COVERAGE_MODERATE,
        )
        if c_b == "badge-red":
            c_b = "badge-neutral"

        t_rows = self._build_trajectory_rows(result, years, currency)
        h_rows = self._build_holdings_rows(result, currency)

        sat_html = self._get_saturation_html(result)
        recs_html = self._get_recs_html(result, params)

        def _get_ann(data: np.ndarray) -> list[float]:
            return [float(data[min(i * 12, len(data) - 1)]) for i in range(years + 1)]

        p50 = _get_ann(result.percentile_50)
        pv50 = _get_ann(result.present_value_50)
        p10 = _get_ann(result.percentile_10)
        p90 = _get_ann(result.percentile_90)

        f_dist = result.final_wealth_distribution
        counts, edges = np.histogram(f_dist, bins=12)
        h_labels = [f"{e / 1e3:.0f}K" for e in edges[:-1]]
        h_data = counts.tolist()

        html_content = self._assemble_html(
            metadata,
            result,
            params,
            m,
            s_b,
            c_b,
            t_rows,
            h_rows,
            sat_html,
            recs_html,
            p50,
            pv50,
            p10,
            p90,
            h_labels,
            h_data,
            user_name,
        )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return output_path

    def _assemble_html(
        self,
        metadata: ScenarioMetadata,
        result: SimulationResult,
        params: SimulationParams,
        m: Any,
        s_b: str,
        c_b: str,
        t_r: str,
        h_r: str,
        s_h: str,
        r_h: str,
        p50: list[float],
        pv50: list[float],
        p10: list[float],
        p90: list[float],
        h_l: list[str],
        h_d: list[int],
        user_name: str,
    ) -> str:
        """Assembles the final HTML string from modular parts."""
        currency = params.profile.currency
        inc_m = params.profile.monthly_income_mean
        exp_m = params.profile.monthly_expense_mean
        net_m = inc_m - exp_m
        margin_m = (net_m / inc_m * 100) if inc_m > 0 else 0
        initial_cap = sum(a.initial_balance for a in params.profile.accounts)

        style = self._get_css()
        header = self._get_header_html(metadata, user_name)
        baseline = self._get_baseline_html(
            inc_m, exp_m, net_m, margin_m, initial_cap, currency, metadata
        )
        snapshot = self._get_snapshot_html(result, m, s_b, c_b, currency)
        trajectory = self._get_trajectory_html(t_r)
        analysis = self._get_analysis_html(result, m, currency, s_h)
        portfolio = self._get_portfolio_html(result, h_r)
        outcomes = self._get_outcomes_html()
        footer = self._get_footer_html()
        scripts = self._get_scripts(p50, pv50, p10, p90, h_l, h_d, currency)

        return f"""<!DOCTYPE html>
<html lang="{self.lang}">
<head>
    <meta charset="UTF-8"><meta name="viewport"
          content="width=device-width, initial-scale=1.0">
    <title>{_t("sim_title")} - {metadata.name}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,700;1,400&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap"
          rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>{style}</style>
</head>
<body>
    <div class="container">
        {header} {baseline} {snapshot} {trajectory}
        {analysis} {portfolio} {outcomes}
        {r_h} {footer}
    </div>
    {scripts}
</body></html>"""

    def _get_css(self) -> str:
        """Returns the Investment Bank light-mode CSS."""
        return """
        :root {
            --bg: #f8fafc; --surface: #ffffff; --fg: #1e293b; --muted: #64748b;
            --border: #f1f5f9; --navy: #002a5c; --navy-light: #0f172a;
            --accent: #92400e; --green: #15803d; --yellow: #b45309; --red: #b91c1c;
            --font-serif: 'Lora', serif; --font-sans: 'Inter', sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }
        body {
            background: var(--bg); color: var(--fg); font-family: var(--font-sans);
            margin: 0; padding: 0; -webkit-font-smoothing: antialiased;
            line-height: 1.5;
        }
        .container { max-width: 1000px; margin: 0 auto; padding: 4rem 2rem; }
        header {
            margin-bottom: 4rem; padding-bottom: 2rem;
            border-bottom: 3px solid var(--navy);
        }
        .report-label {
            font-family: var(--font-mono); font-size: 0.7rem; font-weight: 700;
            color: var(--navy); letter-spacing: 0.15em; text-transform: uppercase;
            margin-bottom: 1rem;
        }
        h1 {
            font-family: var(--font-serif); font-size: 2.8rem; font-weight: 700;
            margin: 0; color: var(--navy); letter-spacing: -0.01em;
        }
        .meta-header {
            display: flex; gap: 2rem; font-size: 0.85rem; color: var(--muted);
            margin-top: 1.25rem; font-family: var(--font-mono);
            flex-wrap: wrap;
        }
        section { margin-bottom: 5rem; }
        .section-header {
            border-bottom: 1px solid var(--border); margin-bottom: 2.5rem;
            padding-bottom: 0.75rem;
        }
        .section-header h2 {
            font-family: var(--font-serif); font-size: 1.4rem; font-weight: 700;
            color: var(--navy); margin: 0; text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .grid-4 {
            display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .snap-card {
            background: var(--surface); border: 1px solid var(--border);
            padding: 1.5rem 1.25rem; border-left: 4px solid var(--border);
            border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.02);
            display: flex; flex-direction: column; min-height: 120px;
        }
        .snap-card.badge-green { border-left-color: var(--green); }
        .snap-card.badge-yellow { border-left-color: var(--yellow); }
        .snap-card.badge-red { border-left-color: var(--red); }
        .snap-card.badge-neutral { border-left-color: var(--navy); }
        .snap-label {
            font-size: 0.65rem; font-weight: 700; color: var(--muted);
            text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: auto;
            display: block;
        }
        .snap-value {
            font-family: var(--font-serif); font-size: 1.5rem; font-weight: 700;
            color: var(--navy-light); line-height: 1.1; margin: 0.5rem 0;
        }
        .snap-sub-value {
            font-size: 0.85rem; font-weight: 400; color: var(--muted);
            display: block; margin-top: 0.1rem; font-family: var(--font-sans);
            letter-spacing: 0; text-transform: none;
        }
        .snap-explain {
            font-size: 0.72rem; color: var(--muted); font-style: italic;
            margin-top: auto; display: block; line-height: 1.3;
            padding-top: 0.5rem;
        }
        .progress-bar-bg {
            background: #f1f5f9; height: 5px; border-radius: 2px;
            margin-top: 0.5rem; overflow: hidden;
        }
        .progress-bar-fill {
            background: var(--navy); height: 100%; border-radius: 2px;
        }
        .analysis-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; }
        .insight-card h3 {
            font-family: var(--font-serif); font-size: 1.1rem; font-weight: 700;
            color: var(--navy); margin-bottom: 1.25rem;
            border-bottom: 2px solid var(--navy);
            padding-bottom: 0.5rem; margin-top: 0;
        }
        .insight-row {
            display: grid; grid-template-columns: 1fr auto; gap: 1rem;
            align-items: baseline; margin-bottom: 0.75rem; padding-bottom: 0.75rem;
            border-bottom: 1px solid #f1f5f9;
        }
        .insight-row:last-of-type { border-bottom: none; }
        .insight-row .label { font-size: 0.85rem; font-weight: 600; color: var(--fg); }
        .insight-row .value {
            font-family: var(--font-mono); font-weight: 700; color: var(--navy);
            font-size: 0.9rem;
        }
        .sub-explain {
            grid-column: 1 / -1; font-size: 0.75rem; color: var(--muted);
            font-style: italic; margin-top: -0.25rem;
        }
        .table-wrapper {
            border: 1px solid var(--border); background: #fff;
            margin-bottom: 2rem; overflow-x: auto;
        }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th {
            text-align: left; padding: 0.75rem 1.25rem; color: var(--navy);
            border-bottom: 2px solid var(--navy); background: #f8fafc;
            font-weight: 700; text-transform: uppercase; font-size: 0.7rem;
        }
        td { padding: 0.85rem 1.25rem; border-bottom: 1px solid var(--border); }
        tr:nth-child(even) { background: #fafafa; }
        .trend-up { color: var(--green); font-weight: 700; }
        .trend-down { color: var(--red); font-weight: 700; }
        .recs-grid {
            display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.25rem;
        }
        .rec-card {
            background: #f8fafc; border: 1px solid var(--border);
            padding: 1.5rem; border-radius: 4px;
        }
        .rec-msg {
            font-weight: 700; color: var(--navy);
            margin-bottom: 0.5rem; display: block;
        }
        .rec-why {
            font-size: 0.8rem; color: var(--muted);
            padding-left: 1rem; border-left: 2px solid var(--border);
        }
        .chart-wrapper {
            background: var(--surface); border: 1px solid var(--border);
            padding: 1.5rem; height: 400px;
        }
        .footer {
            margin-top: 6rem; padding-top: 2rem; border-top: 1px solid var(--navy);
            font-size: 0.7rem; color: var(--muted);
            text-align: center; font-weight: 600;
        }
        .val-red { color: var(--red); }
        .highlight-warning { border-color: var(--yellow); }
        .span-2 { grid-column: span 2; }
        """

    def _get_header_html(self, metadata: ScenarioMetadata, user_name: str) -> str:
        """Modular header generator."""
        # Use locale-friendly date if possible
        try:
            locale.setlocale(locale.LC_TIME, "")
        except Exception as e:  # nosec B110
            import logging

            logging.debug(f"Failed to set locale: {e}")
        d_s = datetime.now().strftime("%d %B %Y")
        label, scenario_l = _t("sim_analyst_report"), metadata.name
        user_label = f"{user_name.upper()} &bull; {scenario_l.upper()}"

        h_l, m_l, d_l = (
            _t("sim_horizon_label"),
            _t("sim_mc_label"),
            _t("sim_date_label"),
        )
        cur_l, yr_u = _t("sim_report_currency"), _t("sim_year_unit")

        return f"""<header>
            <div class="report-label">{label}</div>
            <h1>{_t("sim_title")}</h1>
            <div class="meta-header">
                <div><span>{h_l}:</span> <b>{metadata.years} {yr_u}</b></div>
                <div><span>{m_l}:</span> <b>{metadata.iterations:,}</b></div>
                <div><span>{cur_l}:</span> <b>{metadata.currency}</b></div>
                <div><span>{d_l}:</span> <b>{d_s}</b></div>
                <div style="margin-left:auto; color:var(--navy); font-weight:700;">
                    {user_label}
                </div>
            </div>
        </header>"""

    def _get_baseline_html(
        self,
        i: float,
        e: float,
        n: float,
        m: float,
        cap: float,
        cur: str,
        meta: ScenarioMetadata,
    ) -> str:
        """Modular baseline section generator with explicit labels."""
        fm, b_l = self._format_currency, _t("sim_baseline")

        assumptions_html = ""
        if meta.growth_policy:
            inf = meta.growth_policy.inflation_rate * 100
            inc = meta.growth_policy.default_income_growth * 100
            exp = meta.growth_policy.default_expense_growth * 100

            if meta.growth_policy.dynamic_income_growth:
                i_i = meta.growth_policy.dynamic_income_growth.initial_rate * 100
                i_t = meta.growth_policy.dynamic_income_growth.terminal_rate * 100
                inc_s = f"""{i_i:.1f}% <span class="snap-sub-value">
                            {_t("sim_holdings_start")} {i_i:.1f}% &rarr;
                            {_t("sim_holdings_end")} {i_t:.1f}%</span>"""
            else:
                inc_s = f"{inc:.1f}%"

            if meta.growth_policy.dynamic_expense_growth:
                e_i = meta.growth_policy.dynamic_expense_growth.initial_rate * 100
                e_t = meta.growth_policy.dynamic_expense_growth.terminal_rate * 100
                exp_s = f"""{e_i:.1f}% <span class="snap-sub-value">
                            {_t("sim_holdings_start")} {e_i:.1f}% &rarr;
                            {_t("sim_holdings_end")} {e_t:.1f}%</span>"""
            else:
                exp_s = f"{exp:.1f}%"

            assumptions_html = f"""
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_inflation")}</span>
                    <div class="snap-value">{inf:.1f}%</div>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_salary_growth")}</span>
                    <div class="snap-value">{inc_s}</div>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_expense_growth_label")}</span>
                    <div class="snap-value">{exp_s}</div>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_horizon_label")}</span>
                    <div class="snap-value">{meta.years} {_t("sim_year_unit")}</div>
                </div>
            """

        return f"""<section>
            <div class="section-header"><h2>{b_l}</h2></div>
            <div class="grid-4">
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_income_label")}</span>
                    <div class="snap-value">{fm(i, cur, False)}</div>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_expense_label")}</span>
                    <div class="snap-value">{fm(e, cur, False)}</div>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_monthly_savings_label")}</span>
                    <div class="snap-value">{fm(n, cur, False)} ({m:.1f}%)</div>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_initial_capital")}</span>
                    <div class="snap-value">{fm(cap, cur, False)}</div>
                </div>
                {assumptions_html}
            </div>
        </section>"""

    def _get_snapshot_html(
        self, r: SimulationResult, m: Any, s_b: str, c_b: str, cur: str
    ) -> str:
        """Modular snapshot section generator with cardified metrics."""
        fm = self._format_currency
        v50 = fm(r.percentile_50[-1], cur, False)
        v10, v90 = (
            fm(r.percentile_10[-1], cur, False),
            fm(r.percentile_90[-1], cur, False),
        )
        tax, t_p = fm(r.cumulative_tax_paid_50, cur, False), r.effective_tax_rate * 100
        total_inc = r.total_income_median
        total_exp = r.total_expenses_median
        total_savings = total_inc - total_exp

        ann_g, taxes_l, eff_l = (
            _t("sim_plain_annual_growth"),
            _t("sim_taxes"),
            _t("sim_eff_rate"),
        )
        fi_l, sr_l, med_l = (
            _t("sim_plain_financial_independence"),
            _t("sim_success_rate"),
            _t("sim_plain_final_wealth_median"),
        )
        rng_l, exp_c, exp_s, exp_f, exp_v, exp_m = (
            _t("sim_plain_outcome_range"),
            _t("sim_plain_explain_cagr"),
            _t("sim_plain_explain_success"),
            _t("sim_plain_explain_fire"),
            _t("sim_plain_explain_volatility"),
            _t("sim_plain_explain_final"),
        )
        return f"""<section>
            <div class="section-header"><h2>{_t("sim_plain_your_results")}</h2></div>
            <div class="grid-4">
                <div class="snap-card">
                    <span class="snap-label">{med_l}</span>
                    <div class="snap-value">{v50}</div>
                    <span class="snap-explain">{exp_m}</span>
                </div>
                <div class="snap-card {s_b}">
                    <span class="snap-label">{sr_l}</span>
                    <div class="snap-value">{r.success_rate * 100:.1f}%</div>
                    <span class="snap-explain">{exp_s}</span>
                </div>
                <div class="snap-card {c_b}">
                    <span class="snap-label">{fi_l}</span>
                    <div class="snap-value">{m.coverage:.1f}%</div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill"
                            style="width: {min(100.0, m.coverage):.1f}%"></div>
                    </div>
                    <span class="snap-explain">{exp_f}</span>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{rng_l}</span>
                    <div class="snap-value" style="font-size: 1.1rem;">
                        {v10} - {v90}</div>
                    <span class="snap-explain">{exp_v}</span>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{ann_g}</span>
                    <div class="snap-value">{m.cagr:.1f}%</div>
                    <span class="snap-explain">{exp_c}</span>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{_t("sim_plain_total_savings")}</span>
                    <div class="snap-value">{fm(total_savings, cur, False)}</div>
                    <span class="snap-explain">
                        {_t("sim_plain_explain_conversion")}
                    </span>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{taxes_l}</span>
                    <div class="snap-value">{tax}</div>
                    <span class="snap-explain">{_t("sim_plain_explain_tax")}</span>
                </div>
                <div class="snap-card">
                    <span class="snap-label">{eff_l}</span>
                    <div class="snap-value">{t_p:.1f}%</div>
                </div>
            </div>
        </section>"""

    def _get_trajectory_html(self, rows: str) -> str:
        """Modular trajectory section generator."""
        y_l, nom_l, real_l, gro_l = (
            _t("sim_year"),
            _t("sim_plain_total_wealth"),
            _t("sim_plain_spending_power"),
            _t("sim_plain_growth_this_year"),
        )
        return f"""<section>
            <div class="section-header"><h2>{_t("sim_trajectory")}</h2></div>
            <div class="chart-wrapper"><canvas id="wealthChart"></canvas></div>
            <br>
            <div class="table-wrapper">
                <table><thead><tr><th>{y_l}</th>
                <th>{nom_l}</th><th>{real_l}</th><th>{gro_l}</th></tr></thead>
                <tbody>{rows}</tbody></table>
            </div>
        </section>"""

    def _get_analysis_html(
        self, r: SimulationResult, m: Any, cur: str, sat: str
    ) -> str:
        """Modular analysis section generator."""
        fm = self._format_currency
        inc_e, exp_e = fm(m.inc_end, cur, False), fm(m.exp_end, cur, False)
        g_s, g_e = fm(m.gain_start, cur, False), fm(m.gain_end, cur, False)
        e_m, shocks = fm(m.erosion, cur, False), self._format_shock_str(r)
        engines = ", ".join([f"{n} ({v * 100:.1f}%)" for n, v in m.top_engines])
        grow_l, cf_l, goal_l, risk_l, eff_l = (
            _t("sim_plain_how_wealth_grows"),
            _t("sim_plain_cashflow_card"),
            _t("sim_plain_goal_progress"),
            _t("sim_plain_what_could_go_wrong"),
            _t("sim_plain_efficiency_card"),
        )
        title = _t("sim_plain_detailed_analysis")
        fire_l, fire_e = (
            _t("sim_plain_financial_independence"),
            _t("sim_plain_explain_fire"),
        )
        cagr_l, cagr_e = (_t("sim_plain_annual_growth"), _t("sim_plain_explain_cagr"))
        pass_l, pass_e = _t("sim_cashflow_passive"), _t("sim_plain_explain_passive")
        run_l, run_e = _t("sim_runway"), _t("sim_plain_explain_runway")
        inf_l, inf_e = _t("sim_inflation_drag"), _t("sim_plain_explain_inflation")
        vol_l, vol_e = _t("sim_volatility"), _t("sim_plain_explain_volatility")
        shk_l, shk_e = _t("sim_shock_exposure"), _t("sim_plain_explain_shock")
        eng_l, eng_e = _t("sim_top_engines"), _t("sim_plain_explain_engines")
        rig_l, rig_e = (_t("sim_plain_fixed_vs_flex"), _t("sim_plain_explain_rigidity"))
        eff_l_sub, eff_e = _t("sim_efficiency"), _t("sim_plain_explain_conversion")
        str_l, str_e = _t("sim_liquidity_stress"), _t("sim_plain_explain_stress")
        grow_e = _t("sim_plain_explain_growth_source")
        cf_e = _t("sim_plain_explain_cashflow")
        coast_e = _t("sim_plain_explain_coast")

        stress_v = f"{r.liquidity_stress_months} {_t('sim_months')} "
        stress_v += f"({m.stress_pct:.1f}%)"

        # Logic to balance the grid
        sat_class = "span-2" if not sat else ""

        return f"""<section>
            <div class="section-header"><h2>{title}</h2></div>
            <div class="analysis-grid">
                <div class="insight-card">
                    <h3>{grow_l}</h3>
                    <div class="insight-row">
                        <span class="label">{cagr_l}</span>
                        <span class="value">{m.cagr:.1f}% (x{m.multiplier:.2f})</span>
                        <span class="sub-explain">{cagr_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{_t("sim_growth_source")}</span>
                        <span class="value">{m.passive_ratio:.1f}% {_t("sim_passive")} |
                            {100 - m.passive_ratio:.1f}% {_t("sim_active")}</span>
                        <span class="sub-explain">{grow_e}</span>
                    </div>
                </div>
                <div class="insight-card">
                    <h3>{cf_l}</h3>
                    <div class="insight-row">
                        <span class="label">{_t("sim_income_label")}</span>
                        <span class="value">{inc_e}/mo</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{_t("sim_expense_label")}</span>
                        <span class="value">{exp_e}/mo</span>
                        <span class="sub-explain">{cf_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{pass_l}</span>
                        <span class="value">{g_s} &rarr; {g_e}/mo</span>
                        <span class="sub-explain">{pass_e}</span>
                    </div>
                </div>
                <div class="insight-card">
                    <h3>{goal_l}</h3>
                    <div class="insight-row">
                        <span class="label">{fire_l}</span>
                        <span class="value">{m.coverage:.1f}%</span>
                        <span class="sub-explain">{fire_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{_t("sim_coast_fire")}</span>
                        <span class="value">{m.coast_years:.1f} {_t("sim_year")}</span>
                        <span class="sub-explain">{coast_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{run_l}</span>
                        <span class="value">{m.runway_years:.1f} {_t("sim_year")}</span>
                        <span class="sub-explain">{run_e}</span>
                    </div>
                </div>
                <div class="insight-card">
                    <h3>{risk_l}</h3>
                    <div class="insight-row">
                        <span class="label">{inf_l}</span>
                        <span class="value val-red">-{e_m} ({m.erosion_pct:.1f}%)</span>
                        <span class="sub-explain">{inf_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{vol_l}</span>
                        <span class="value">{m.dispersion:.1f}%</span>
                        <span class="sub-explain">{vol_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{shk_l}</span>
                        <span class="value" style="font-size:0.8rem;">{shocks}</span>
                        <span class="sub-explain">{shk_e}</span>
                    </div>
                </div>
                <div class="insight-card {sat_class}">
                    <h3>{eff_l}</h3>
                    <div class="insight-row">
                        <span class="label">{eng_l}</span>
                        <span class="value" style="font-size:0.75rem;">{engines}</span>
                        <span class="sub-explain">{eng_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{rig_l}</span>
                        <span class="value">{m.rigidity:.1f}% fixed</span>
                        <span class="sub-explain">{rig_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{eff_l_sub}</span>
                        <span class="value">{m.conversion_eff:.2f}</span>
                        <span class="sub-explain">{eff_e}</span>
                    </div>
                    <div class="insight-row">
                        <span class="label">{str_l}</span>
                        <span class="value">{stress_v}</span>
                        <span class="sub-explain">{str_e}</span>
                    </div>
                </div>
                {sat}
            </div>
        </section>"""

    def _get_portfolio_html(self, result: SimulationResult, holdings: str) -> str:
        """Modular portfolio section generator."""
        acc_l, start_l, end_l, roi_l = (
            _t("sim_holdings_account"),
            _t("sim_holdings_start"),
            _t("sim_holdings_end"),
            _t("sim_holdings_roi"),
        )
        title = _t("sim_plain_where_money_lives")
        return f"""<section>
            <div class="section-header"><h2>{title}</h2></div>
            <div class="table-wrapper">
                {self._generate_portfolio_table_html(result)}
            </div>
            <div style="margin-top: 3rem; margin-bottom: 1.5rem;">
                <h3>{_t("sim_top_holdings")}</h3></div>
            <div class="table-wrapper">
                <table><thead><tr><th>{acc_l}</th>
                <th>{start_l}</th><th>{end_l}</th>
                <th>{roi_l}</th></tr></thead>
                <tbody>{holdings}</tbody></table>
            </div>
        </section>"""

    def _get_outcomes_html(self) -> str:
        """Modular outcomes/risk distribution section generator."""
        exp = _t("sim_plain_explain_distribution")
        title = _t("sim_plain_range_of_outcomes")
        return f"""<section>
            <div class="section-header"><h2>{title}</h2></div>
            <p class="text-muted" style="margin-bottom:2rem;">{exp}</p>
            <div class="chart-wrapper" style="height: 300px;">
                <canvas id="distChart"></canvas>
            </div>
        </section>"""

    def _get_saturation_html(self, result: SimulationResult) -> str:
        """Build saturation alerts HTML."""
        if not result.account_saturation_months:
            return ""
        sat_list = []
        for name, months in result.account_saturation_months.items():
            sat_list.append(
                f"<div class='insight-row'><span class='label'>{name}</span>"
                f"<span class='value'>{_t('sim_saturated_at', months)}</span>"
                f"</div>"
            )
        return f"""
            <div class="insight-card highlight-warning">
                <h3>{_t("sim_saturation_alerts")}</h3>
                {"".join(sat_list)}
                <p class="sub-explain">{_t("sim_plain_explain_saturation")}</p>
            </div>"""

    def _get_recs_html(self, result: SimulationResult, params: SimulationParams) -> str:
        """Build recommendations HTML with individualized cards."""
        from prospere.simulation.recommendations import generate_recommendations

        recs = generate_recommendations(result, params)
        if not recs:
            return ""
        rec_cards = []
        for rec in recs[:4]:
            msg = _t(rec["message_key"], **rec.get("message_args", {}))
            w_k = rec.get("why_key")
            why_t = _t(w_k, **rec.get("why_args", {})) if w_k else ""
            why = (
                f"<div class='rec-why'>{_t('sim_why_prefix')} {why_t}</div>"
                if why_t
                else ""
            )
            rec_cards.append(
                f"<div class='rec-card'><span class='rec-msg'>→ {msg}</span>{why}</div>"
            )
        return f"""
        <section>
            <div class="section-header"><h2>{_t("sim_rec_title")}</h2></div>
            <p class="text-muted" style="margin-bottom:2rem;">
                {_t("sim_rec_intro")}
            </p>
            <div class="recs-grid">
                {"".join(rec_cards)}
            </div>
        </section>"""

    def _get_footer_html(self) -> str:
        """Modular footer generator."""
        adv_l = _t("sim_advisory_label")
        line1 = "PROSPERE &bull; STRATEGIC FINANCIAL ANALYTICS"
        return f"""<div class="footer"><div>{line1}</div>
            <div style="margin-top:0.5rem; color:var(--muted);">{adv_l}</div></div>"""

    def _get_scripts(
        self, p50: Any, pv50: Any, p10: Any, p90: Any, h_l: Any, h_d: Any, cur: str
    ) -> str:
        """Returns the Chart.js script block."""
        l_j = json.dumps([f"Y{i}" for i in range(len(p50))])
        p50_j, pv50_j, p10_j, p90_j = map(json.dumps, [p50, pv50, p10, p90])
        h_l_j, h_d_j = map(json.dumps, [h_l, h_d])
        med_l, pp_l, ci_l = (
            _t("sim_median_label"),
            _t("sim_purchasing_power_label"),
            _t("sim_confidence_label"),
        )

        return f"""<script>
        window.onload = function() {{
            Chart.defaults.font.family = "'Inter', sans-serif";
            Chart.defaults.color = '#64748b';

            const ctxW = document.getElementById('wealthChart');
            if (ctxW) {{
                new Chart(ctxW.getContext('2d'), {{
                    type: 'line',
                    data: {{
                        labels: {l_j},
                        datasets: [
                            {{
                                label: '{med_l}', data: {p50_j},
                                borderColor: '#002a5c', borderWidth: 3,
                                fill: false, pointRadius: 0, tension: 0.1
                            }},
                            {{
                                label: '{pp_l}', data: {pv50_j},
                                borderColor: '#94a3b8', borderWidth: 1.5,
                                borderDash: [5, 5], fill: false, pointRadius: 0
                            }},
                            {{
                                label: '{ci_l}', data: {p90_j},
                                borderColor: 'rgba(0, 42, 92, 0.05)',
                                backgroundColor: 'rgba(0, 42, 92, 0.03)',
                                fill: '+1', pointRadius: 0
                            }},
                            {{
                                label: '_p10', data: {p10_j},
                                borderColor: 'transparent', fill: false,
                                pointRadius: 0
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true, maintainAspectRatio: false,
                        plugins: {{
                            legend: {{
                                position: 'bottom',
                                labels: {{
                                    filter: item => !item.text.startsWith('_')
                                }}
                            }}
                        }},
                        scales: {{
                            y: {{
                                grid: {{ color: '#f1f5f9' }},
                                ticks: {{
                                    callback: v => {{
                                        if (v >= 1e6) return (v/1e6).toFixed(1) + 'M';
                                        if (v >= 1e3) return (v/1e3).toFixed(0) + 'K';
                                        return v;
                                    }}
                                }}
                            }},
                            x: {{ grid: {{ display: false }} }}
                        }}
                    }}
                }});
            }}

            const ctxD = document.getElementById('distChart');
            if (ctxD) {{
                new Chart(ctxD.getContext('2d'), {{
                    type: 'bar',
                    data: {{
                        labels: {h_l_j},
                        datasets: [{{
                            label: 'Iterations', data: {h_d_j},
                            backgroundColor: '#002a5c', borderRadius: 2
                        }}]
                    }},
                    options: {{
                        responsive: true, maintainAspectRatio: false,
                        plugins: {{ legend: {{ display: false }} }},
                        scales: {{
                            y: {{ grid: {{ color: '#f1f5f9' }} }},
                            x: {{ grid: {{ display: false }} }}
                        }}
                    }}
                }});
            }}
        }};
        </script>"""


class JSONExporter:
    """Exports simulation results and profile metadata for optimization."""

    @staticmethod
    def export_optimization_context(
        result: SimulationResult,
        params: SimulationParams,
        output_path: str,
    ) -> str:
        """Exports a JSON containing everything needed for the optimization engine."""

        # Extract relevant category metadata
        categories_data = []
        for cat in params.profile.categories:
            categories_data.append(
                {
                    "name": cat.name,
                    "mean": float(cat.mean),
                    "std": float(cat.std),
                    "is_income": cat.is_income,
                    "flexibility_score": cat.flexibility_score,
                    "necessity_level": cat.necessity_level.value,
                    "annual_growth_rate": cat.annual_growth_rate,
                }
            )

        # Extract account metadata
        accounts_data = []
        for acc in params.profile.accounts:
            accounts_data.append(
                {
                    "name": acc.name,
                    "account_type": (
                        acc.account_type.value
                        if hasattr(acc.account_type, "value")
                        else acc.account_type
                    ),
                    "annual_return": float(acc.annual_return),
                    "annual_return_std": float(acc.annual_return_std),
                    "allocation_ratio": float(acc.allocation_ratio),
                    "initial_balance": float(acc.initial_balance),
                    "currency": acc.currency,
                }
            )

        context = {
            "metadata": {
                "scenario_name": params.scenario_metadata.name,
                "years": params.years,
                "iterations": params.iterations,
                "base_currency": params.profile.currency,
                "timestamp": datetime.now().isoformat(),
            },
            "baseline_results": {
                "success_rate": float(result.success_rate),
                "final_wealth_p50": float(result.percentile_50[-1]),
                "final_wealth_pv_p50": float(result.present_value_50[-1]),
                "total_income_median": float(result.total_income_median),
                "total_expenses_median": float(result.total_expenses_median),
                "effective_tax_rate": float(result.effective_tax_rate),
            },
            "financial_profile": {
                "monthly_income_mean": float(params.profile.monthly_income_mean),
                "monthly_expense_mean": float(params.profile.monthly_expense_mean),
                "categories": categories_data,
                "accounts": accounts_data,
            },
            "growth_policy": {
                "default_expense_growth": float(
                    params.growth_policy.default_expense_growth
                ),
                "default_income_growth": float(
                    params.growth_policy.default_income_growth
                ),
                "inflation_rate": float(params.growth_policy.inflation_rate),
            },
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(context, f, indent=4)

        return output_path
