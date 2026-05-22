import logging
import os
from datetime import datetime
from typing import Any

from rich.console import Console

from prospere.ai.assistant import AIAssistant
from prospere.cli.i18n import _t
from prospere.cli.utils import (
    Spinner,
    cli_header,
    format_currency,
    hierarchical_checklist,
    interactive_checklist,
    prompt,
    prompt_float,
    prompt_int,
    tui_choice,
)
from prospere.core.constants import (
    AccountType,
    ExchangeRates,
    FinancialRole,
    NecessityLevel,
    PathConfig,
    SimulationDefaults,
)
from prospere.core.models import Identity
from prospere.core.workspace import WorkspaceManager
from prospere.simulation.scenario_builder import ScenarioBuilder

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════════════
# TUI helpers
# ═══════════════════════════════════════════════════════════════════════


def _tui_bool(console: Console, question: str, default: bool = True) -> bool | None:
    """Yes/No via tui_choice. Returns None on q/back."""
    console.print(f"  {question}\n")
    yes_label = _t("yes")
    no_label = _t("no")
    if default:
        items = [yes_label, no_label]
    else:
        items = [no_label, yes_label]
    idx = tui_choice(console, None, items, back_label=_t("back"))
    if idx is None:
        return None
    return items[idx] == yes_label


_tui_auto = False


def set_tui_auto(value: bool) -> None:
    global _tui_auto
    _tui_auto = value


def _tui_continue(console: Console) -> str:
    """Continue / Go Back via tui_choice. Returns 'next' or 'back'."""
    if _tui_auto:
        return "next"
    items = [_t("continue_label"), _t("go_back")]
    idx = tui_choice(console, None, items, back_label=_t("back"))
    if idx is None or idx == 1:
        return "back"
    return "next"


def _tui_choice_str(
    console: Console, label: str, choices: list[str], default: str
) -> str | None:
    """Single-choice via tui_choice. Default is positioned first."""
    ordered = list(choices)
    if default in ordered:
        ordered.remove(default)
        ordered.insert(0, default)
    console.print(f"  {label}:\n")
    idx = tui_choice(console, None, ordered, back_label=_t("back"))
    if idx is None:
        return None
    return ordered[idx]


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 1/7 — Scope Selection
# ═══════════════════════════════════════════════════════════════════════


def _scope_choose_depth(console: Console, excluded_accounts: list[str]) -> str | None:
    if excluded_accounts:
        msg = _t("scope_excluded_accounts", len(excluded_accounts))
        console.print("  " + msg + "\n")
    return _tui_choice_str(
        console,
        _t("scope_filter_depth"),
        [
            _t("scope_primary_only"),
            _t("scope_detailed_subs"),
            _t("scope_skip_filter"),
        ],
        _t("scope_primary_only"),
    )


def _scope_exclude_subs(
    console: Console,
    builder: ScenarioBuilder,
    excluded_accounts: list[str],
    depth_selection: str,
) -> list[tuple[str, str]] | None:
    summary = "  " + _t("scope_filter_enabled")
    if excluded_accounts:
        summary += f"  ·  {len(excluded_accounts)} {_t('ui_accounts_excluded')}"
    summary += f"\n  {_t('ui_depth')}: {depth_selection}\n"
    console.print(summary)
    flat_subs = []
    sub_lookup = {}
    for cat in builder.detected_categories:
        for sub in builder.sub_categories_map.get(cat, []):
            label = f"{cat} {SimulationDefaults.SUBCATEGORY_DELIMITER} {sub}"
            flat_subs.append(label)
            sub_lookup[label] = (cat, sub)
    subs_result = interactive_checklist(
        console,
        _t("scope_deselect_subs"),
        sorted(flat_subs),
        back_key="q",
    )
    if subs_result is None:
        return None
    return [sub_lookup[label] for label in subs_result]


def _scope_handle_exclude_accounts(
    console: Console, builder: ScenarioBuilder
) -> list[str] | None:
    console.print("  " + _t("scope_filter_enabled") + "\n")
    return interactive_checklist(
        console, _t("scope_deselect_accounts"), builder.detected_accounts, back_key="q"
    )


def _scope_handle_exclude_categories(
    console: Console, builder: ScenarioBuilder, depth_sel: str
) -> list[str] | None:
    console.print(f"  {_t('scope_filter_enabled')}\n  {_t('ui_depth')}: {depth_sel}\n")
    return interactive_checklist(
        console,
        _t("scope_deselect_categories"),
        builder.detected_categories,
        back_key="q",
    )


def _scope_step_ask_filter(console: Console) -> tuple[str, str | None]:
    res = _tui_bool(console, _t("scope_filter_prompt"), False)
    if res is None:
        return "back", "back"
    if not res:
        console.print("  " + _t("scope_proceeding") + "\n")
        return "finish", _tui_continue(console)
    return "exclude_accounts", None


def _scope_step_choose_depth(
    console: Console, ex_acc: list[str]
) -> tuple[str, str | None, str]:
    depth = _scope_choose_depth(console, ex_acc)
    if depth is None:
        return "exclude_accounts", None, _t("scope_primary_only")
    next_s = (
        "exclude_categories"
        if depth == _t("scope_primary_only")
        else ("exclude_subs" if depth == _t("scope_detailed_subs") else "apply")
    )
    return next_s, None, depth


def _scope_step_exclude_accounts(
    console: Console,
    builder: ScenarioBuilder,
    ex_acc: list[str],
    depth_sel: str,
    ex_cat: list[str],
    ex_sub: list[tuple[str, str]],
) -> tuple[str, str | None, list[str], str, list[str], list[tuple[str, str]]]:
    res = _scope_handle_exclude_accounts(console, builder)
    if res is not None:
        return "choose_depth", None, res, depth_sel, ex_cat, ex_sub
    return "ask_filter", None, ex_acc, depth_sel, ex_cat, ex_sub


def _scope_step_exclude_categories(
    console: Console,
    builder: ScenarioBuilder,
    ex_acc: list[str],
    depth_sel: str,
    ex_cat: list[str],
    ex_sub: list[tuple[str, str]],
) -> tuple[str, str | None, list[str], str, list[str], list[tuple[str, str]]]:
    res = _scope_handle_exclude_categories(console, builder, depth_sel)
    if res is not None:
        return "apply", None, ex_acc, depth_sel, res, ex_sub
    return "choose_depth", None, ex_acc, depth_sel, ex_cat, ex_sub


def _scope_step_exclude_subs(
    console: Console,
    builder: ScenarioBuilder,
    ex_acc: list[str],
    depth_sel: str,
    ex_cat: list[str],
    ex_sub: list[tuple[str, str]],
) -> tuple[str, str | None, list[str], str, list[str], list[tuple[str, str]]]:
    res = _scope_exclude_subs(console, builder, ex_acc, depth_sel)
    if res is not None:
        return "apply", None, ex_acc, depth_sel, ex_cat, res
    return "choose_depth", None, ex_acc, depth_sel, ex_cat, ex_sub


def _page_scope_step(
    console: Console,
    builder: ScenarioBuilder,
    state: str,
    user: str,
    ex_acc: list[str],
    depth_sel: str,
    ex_cat: list[str],
    ex_sub: list[tuple[str, str]],
) -> tuple[str, str | None, list[str], str, list[str], list[tuple[str, str]]]:
    """Processes a single step of the scope selection page."""
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_scope"))

    if state == "ask_filter":
        ns, fr = _scope_step_ask_filter(console)
        return ns, fr, ex_acc, depth_sel, ex_cat, ex_sub

    if state == "exclude_accounts":
        return _scope_step_exclude_accounts(
            console, builder, ex_acc, depth_sel, ex_cat, ex_sub
        )

    if state == "choose_depth":
        ns, fr, d = _scope_step_choose_depth(console, ex_acc)
        return ns, fr, ex_acc, d, ex_cat, ex_sub

    if state == "exclude_categories":
        return _scope_step_exclude_categories(
            console, builder, ex_acc, depth_sel, ex_cat, ex_sub
        )

    if state == "exclude_subs":
        return _scope_step_exclude_subs(
            console, builder, ex_acc, depth_sel, ex_cat, ex_sub
        )

    if state == "apply":
        if ex_acc or ex_cat or ex_sub:
            builder.apply_scope_filter(ex_acc, ex_cat, ex_sub)
            counts = (len(builder.detected_accounts), len(builder.detected_categories))
            console.print(f"\n  {_t('scope_remaining', *counts)}\n")
        return "finish", _tui_continue(console), ex_acc, depth_sel, ex_cat, ex_sub

    return "finish", "next", ex_acc, depth_sel, ex_cat, ex_sub


def _page_scope(
    console: Console, builder: ScenarioBuilder, is_auto: bool, user: str
) -> str:
    if is_auto:
        console.clear()
        cli_header(console, user, _t("bootstrap"), _t("step_scope"))
        console.print("  " + _t("scope_using_all") + "\n")
        return "next"

    state = "ask_filter"
    ex_acc: list[str] = []
    depth_sel = _t("scope_primary_only")
    ex_cat: list[str] = []
    ex_sub: list[tuple[str, str]] = []

    while state != "finish":
        state, res, ex_acc, depth_sel, ex_cat, ex_sub = _page_scope_step(
            console, builder, state, user, ex_acc, depth_sel, ex_cat, ex_sub
        )
        if res:
            return res
    return "next"

    return "next"


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 2/7 — Baseline Audit
# ═══════════════════════════════════════════════════════════════════════


def _audit_compute_trends(
    console: Console,
    builder: ScenarioBuilder,
    start_date: str,
    end_date: str,
    min_date: str,
    max_date: str,
) -> None:
    """Computes and displays historical growth trends."""
    full_trends = builder.calculate_historical_growth_metrics()
    if full_trends["income_growth"] is not None:
        console.print(
            "\n  " + _t("audit_full_history_header", full_trends["data_years"])
        )
        inc_steps = ", ".join(
            f"{s:+.1f}%" for s in full_trends["yearly_details"]["income_steps"]
        )
        exp_steps = ", ".join(
            f"{s:+.1f}%" for s in full_trends["yearly_details"]["expense_steps"]
        )
        console.print(f"    {_t('audit_income_steps')}  {inc_steps}")
        console.print(f"    {_t('audit_expense_steps')} {exp_steps}")
        console.print(
            f"    {_t('audit_overall_avg')}   {_t('ui_inc')} "
            f"{full_trends['income_growth'] * 100:+.1f}%, "
            f"{_t('ui_exp')} {full_trends['expense_growth'] * 100:+.1f}%"
        )

    if start_date != min_date or end_date != max_date:
        window_trends = builder.calculate_historical_growth_metrics(
            start_date, end_date
        )
        if window_trends["income_growth"] is not None:
            console.print("\n  " + _t("audit_selected_window", start_date, end_date))
            console.print(
                f"    {_t('audit_proposed_inc')}  "
                f"{window_trends['income_growth'] * 100:+.1f}%"
            )
            console.print(
                f"    {_t('audit_proposed_exp')} "
                f"{window_trends['expense_growth'] * 100:+.1f}%"
            )
            builder.set_scenario_field(
                "_historical_inc_growth", window_trends["income_growth"]
            )
            builder.set_scenario_field(
                "_historical_exp_growth", window_trends["expense_growth"]
            )
    else:
        builder.set_scenario_field(
            "_historical_inc_growth", full_trends["income_growth"]
        )
        builder.set_scenario_field(
            "_historical_exp_growth", full_trends["expense_growth"]
        )


def _audit_handle_compute(
    console: Console,
    builder: ScenarioBuilder,
    start_date: str,
    end_date: str,
    min_date: str,
    max_date: str,
) -> dict[str, Any]:
    audit = builder.calculate_baseline_audit(start_date, end_date)
    currency = builder.scenario["currency"]
    console.print("  " + _t("audit_results_header", audit["month_count"]))
    console.print(f"    {_t('audit_income')}  {audit['avg_income']:,.2f} {currency}")
    console.print(f"    {_t('audit_expense')} {audit['avg_expense']:,.2f} {currency}")
    surplus = audit["avg_income"] - audit["avg_expense"]
    console.print(f"    {_t('audit_surplus')} {surplus:,.2f} {currency}")

    _audit_compute_trends(console, builder, start_date, end_date, min_date, max_date)
    builder.set_scenario_field("start_date", start_date)
    builder.set_scenario_field("end_date", end_date)
    return audit


def _audit_display_results(
    console: Console, builder: ScenarioBuilder, audit: dict
) -> None:
    currency = builder.scenario["currency"]
    console.print("  " + _t("audit_results_header", audit["month_count"]))
    console.print(f"    {_t('audit_income')}  {audit['avg_income']:,.2f} {currency}")
    console.print(f"    {_t('audit_expense')} {audit['avg_expense']:,.2f} {currency}")


def _audit_step_ask_filter(
    console: Console, min_date: str, max_date: str
) -> tuple[str, str | None, str, str]:
    console.print(f"  {_t('audit_historical')} {min_date} to {max_date}")
    res = _tui_bool(console, _t("audit_filter_period"), False)
    if res is None:
        return "back", "back", min_date, max_date
    if res:
        return (
            "compute",
            None,
            prompt("    " + _t("audit_start_date"), min_date),
            prompt("    " + _t("audit_end_date"), max_date),
        )
    return "compute", None, min_date, max_date


def _audit_step_ask_override(
    console: Console, builder: ScenarioBuilder, audit: dict
) -> str:
    _audit_display_results(console, builder, audit)
    res = _tui_bool(console, _t("audit_override_prompt"), False)
    if res is None:
        return "back"
    return "prompt_override" if res else "finish"


def _page_audit_step(
    console: Console,
    builder: ScenarioBuilder,
    state: str,
    user: str,
    is_auto: bool,
    start_date: str,
    end_date: str,
    min_date: str,
    max_date: str,
    audit: dict[str, Any],
) -> tuple[str, str | None, str, str, dict[str, Any], bool]:
    """Processes a single step of the audit page."""
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_audit"))

    if state == "ask_filter":
        ns, fr, sd, ed = _audit_step_ask_filter(console, min_date, max_date)
        return ns, fr, sd, ed, audit, False

    if state == "compute":
        audit = _audit_handle_compute(
            console, builder, start_date, end_date, min_date, max_date
        )
        return (
            "finish" if is_auto else "ask_override",
            None,
            start_date,
            end_date,
            audit,
            False,
        )

    if state == "ask_override":
        fr = _audit_step_ask_override(console, builder, audit)
        return (
            ("back", "back", start_date, end_date, audit, False)
            if fr == "back"
            else (fr, None, start_date, end_date, audit, False)
        )

    if state == "prompt_override":
        over_inc = prompt_float(
            "    " + _t("audit_new_income"), audit["avg_income"], 0, 1e9
        )
        over_exp = prompt_float(
            "    " + _t("audit_new_expense"), audit["avg_expense"], 0, 1e9
        )
        builder.set_scenario_field(
            "audit_override", {"income": float(over_inc), "expense": float(over_exp)}
        )
        return "finish", None, start_date, end_date, audit, True

    if state == "finish":
        _audit_display_results(console, builder, audit)
        return "finish", _tui_continue(console), start_date, end_date, audit, False

    return "finish", "next", start_date, end_date, audit, False


def _page_audit(
    console: Console, builder: ScenarioBuilder, is_auto: bool, user: str
) -> str:
    min_date = str(builder.transactions["transaction_date"].min().date())
    max_date = str(builder.transactions["transaction_date"].max().date())
    sd, ed = min_date, max_date
    audit: dict[str, Any] = {}
    over_app = False
    state = "compute" if is_auto else "ask_filter"

    while state != "finish":
        state, res, sd, ed, audit, oa = _page_audit_step(
            console, builder, state, user, is_auto, sd, ed, min_date, max_date, audit
        )
        if oa:
            over_app = oa
        if res:
            if res == _tui_continue(console) and over_app:
                console.print("    " + _t("audit_overridden"))
            return res
    return "next"


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 3/7 — Basic Parameters
# ═══════════════════════════════════════════════════════════════════════


def _page_params(
    console: Console, builder: ScenarioBuilder, is_auto: bool, user: str
) -> str:
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_params"))

    if is_auto:
        auto_name = f"scenario_{datetime.now():%Y%m%d_%H%M%S}"
        builder.set_scenario_field("name", auto_name)
        builder.set_scenario_field("iterations", SimulationDefaults.ITERATIONS)
        builder.set_scenario_field(
            "currency",
            builder.scenario.get("currency", ExchangeRates.BASE_CURRENCY),
        )
        if "years" not in builder.scenario or not builder.scenario["years"]:
            builder.set_scenario_field("years", SimulationDefaults.YEARS)
    else:
        name = prompt(
            _t("param_scenario_name"),
            SimulationDefaults.DEFAULT_SCENARIO_NAME,
        )
        builder.set_scenario_field("name", name)
        builder.set_scenario_field(
            "years", prompt_int(_t("param_years"), SimulationDefaults.YEARS, 1, 100)
        )
        builder.set_scenario_field(
            "iterations",
            prompt_int(
                _t("param_iterations"),
                SimulationDefaults.ITERATIONS,
                100,
                500_000,
            ),
        )
        curr = prompt(_t("param_currency"), builder.scenario["currency"]).upper()
        builder.set_scenario_field("currency", curr)
    builder.update_initial_capital()
    return _tui_continue(console)


# ═══════════════════════════════════════════════════════════════════════
# Page: AI Classification
# ═══════════════════════════════════════════════════════════════════════


def _page_ai_classify(
    console: Console, builder: ScenarioBuilder, ai: AIAssistant, user: str
) -> str:
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_ai_classify"))

    meta = [
        {
            "name": n,
            "balance": builder.balances.get(n, 0.0),
            "currency": builder.currencies.get(n, ExchangeRates.BASE_CURRENCY),
        }
        for n in builder.detected_accounts
    ]
    console.print("    " + _t("ai_classify_hint"))
    with Spinner(_t("ai_classify_spinner")):
        preds = ai.classify_entities(meta, builder.get_category_metadata())

    console.print("    " + _t("ai_classify_complete"))
    if preds:
        acc_count = len(preds.accounts) if preds.accounts else 0
        cat_count = len(preds.categories) if preds.categories else 0
        console.print(f"    {_t('ai_classify_accounts', acc_count)}")
        console.print(f"    {_t('ai_classify_categories', cat_count)}")

    builder._ai_acc_map = {p.name: p for p in (preds.accounts if preds else [])}  # type: ignore[attr-defined]
    builder._ai_cat_map = {p.name: p for p in (preds.categories if preds else [])}  # type: ignore[attr-defined]
    return _tui_continue(console)


# ═══════════════════════════════════════════════════════════════════════
# AI Life Stage helpers
# ═══════════════════════════════════════════════════════════════════════


def _collect_optional_profile(identity: Identity | None = None) -> dict[str, str]:
    profile = {}
    print("\n    " + _t("profile_prompt"))
    fields = [
        ("age", _t("profile_current_age")),
        ("industry", _t("profile_industry_career")),
        ("location", _t("profile_location_field")),
        ("family_status", _t("profile_family_status")),
        ("financial_goal", _t("profile_primary_goal")),
    ]
    for key, label in fields:
        val = prompt(f"      {label}", getattr(identity, key) if identity else "")
        if val:
            profile[key] = val
    return profile


def _run_ai_life_stage_modeling(
    builder: ScenarioBuilder, ai: AIAssistant, context: dict
) -> tuple[dict | None, dict | None, Any]:
    meta = builder.get_category_metadata()

    def _sum_meta(lst: list[dict[str, Any]], key: str) -> dict[str, Any]:
        ovr: dict[str, Any] = builder.scenario.get("audit_override", {})
        val = ovr.get(key)
        avg = float(val) if val is not None else sum(abs(m["avg_monthly"]) for m in lst)
        return {
            "avg_monthly": avg,
            "stability": "Moderate" if len(lst) > 3 else "High",
        }

    with Spinner(_t("growth_life_stage_spinner")):
        modeling = ai.model_life_stage(
            _sum_meta([m for m in meta if m["net_flow"] > 0], "income"),
            _sum_meta([m for m in meta if m["net_flow"] <= 0], "expense"),
            profile_context=context,
        )

    if not modeling:
        return None, None, None

    d_inc = {
        "initial_rate": modeling.income_growth.initial_rate,
        "terminal_rate": modeling.income_growth.terminal_rate,
        "transition_years": float(modeling.income_growth.transition_years),
    }
    d_exp = {
        "initial_rate": modeling.expense_growth.initial_rate,
        "terminal_rate": modeling.expense_growth.terminal_rate,
        "transition_years": float(modeling.expense_growth.transition_years),
    }
    return d_inc, d_exp, modeling


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 4/7 — Growth & Inflation
# ═══════════════════════════════════════════════════════════════════════


def _growth_display_model_recap(console: Console, model: Any) -> None:
    """Displays AI life stage modeling analysis."""
    if not model:
        return
    console.print("  " + _t("growth_ai_analysis"))
    console.print("    " + _t("growth_profile") + " " + str(model.life_stage))
    console.print("    " + _t("growth_insight") + " " + str(model.reasoning))
    console.print("    " + _t("growth_model_title"))
    console.print(
        "      "
        + _t("recap_dyn_income_fmt").format(
            model.income_growth.initial_rate * 100,
            model.income_growth.terminal_rate * 100,
            model.income_growth.transition_years,
        )
    )
    console.print(
        "      "
        + _t("recap_dyn_expense_fmt").format(
            model.expense_growth.initial_rate * 100,
            model.expense_growth.terminal_rate * 100,
            model.expense_growth.transition_years,
        )
    )
    console.print()


def _growth_get_rates(
    builder: ScenarioBuilder,
    is_auto: bool,
    dynamic_inc: dict | None,
    dynamic_exp: dict | None,
) -> tuple[float, float]:
    if dynamic_inc and dynamic_exp:
        return dynamic_inc["terminal_rate"], dynamic_exp["terminal_rate"]

    def_inc = builder.scenario.get(
        "_historical_inc_growth", SimulationDefaults.DEFAULT_INCOME_GROWTH
    )
    def_exp = builder.scenario.get(
        "_historical_exp_growth", SimulationDefaults.DEFAULT_EXPENSE_GROWTH
    )

    if is_auto:
        return def_inc, def_exp

    inc_rate = prompt_float(_t("growth_annual_income"), def_inc, -0.5, 0.5)
    exp_rate = prompt_float(_t("growth_annual_expense"), def_exp, -0.5, 0.5)
    return inc_rate, exp_rate


def _growth_step_prompt_rates(
    console: Console,
    builder: ScenarioBuilder,
    is_auto: bool,
    dynamic_inc: dict | None,
    dynamic_exp: dict | None,
    model: Any,
) -> None:
    _growth_display_model_recap(console, model)
    inc_rate, exp_rate = _growth_get_rates(builder, is_auto, dynamic_inc, dynamic_exp)
    infl = (
        SimulationDefaults.DEFAULT_INFLATION_RATE
        if is_auto
        else prompt_float(
            _t("growth_inflation_rate"),
            SimulationDefaults.DEFAULT_INFLATION_RATE,
            -0.5,
            0.5,
        )
    )
    if dynamic_inc and dynamic_exp:
        p = {
            "inflation_rate": infl,
            "dynamic_income_growth": dynamic_inc,
            "dynamic_expense_growth": dynamic_exp,
        }
    else:
        p = {
            "default_income_growth": inc_rate,
            "default_expense_growth": exp_rate,
            "inflation_rate": infl,
        }
    builder.set_scenario_field("growth_policy", p)


def _page_growth_step(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    state: str,
    user: str,
    is_auto: bool,
    identity: Any,
    profile_context: dict,
    dynamic_inc: dict | None,
    dynamic_exp: dict | None,
    model: Any,
) -> tuple[str, str | None, dict, dict | None, dict | None, Any]:
    """Processes a single step of the growth page."""
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_growth"))

    if state == "ask_profile":
        res = _tui_bool(console, _t("growth_ai_prompt"), False)
        if res is None:
            return "back", "back", profile_context, dynamic_inc, dynamic_exp, model
        if res:
            pc = _collect_optional_profile(identity)
            return "run_model", None, pc, dynamic_inc, dynamic_exp, model
        return "prompt_rates", None, profile_context, dynamic_inc, dynamic_exp, model

    if state == "run_model":
        if ai:
            console.print("    " + _t("growth_life_stage_hint"))
            di, de, m = _run_ai_life_stage_modeling(builder, ai, profile_context)
            return "prompt_rates", None, profile_context, di, de, m
        return "prompt_rates", None, profile_context, dynamic_inc, dynamic_exp, model

    if state == "prompt_rates":
        _growth_step_prompt_rates(
            console, builder, is_auto, dynamic_inc, dynamic_exp, model
        )
        return "finish", None, profile_context, dynamic_inc, dynamic_exp, model

    if state == "finish":
        console.print("  " + _t("growth_configured") + "\n")
        return (
            "finish",
            _tui_continue(console),
            profile_context,
            dynamic_inc,
            dynamic_exp,
            model,
        )

    return "finish", "next", profile_context, dynamic_inc, dynamic_exp, model


def _page_growth(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    is_auto: bool,
    ws: WorkspaceManager | None,
    user: str,
) -> str:
    di, de, pc, model = None, None, {}, None
    identity = ws.load_identity() if ws else None
    _fields = ("age", "industry", "location", "family_status", "financial_goal")
    has_p = bool(identity and any(getattr(identity, f) for f in _fields))
    state = "prompt_rates"
    if ai and ai.is_available():
        state = "run_model" if (is_auto or (has_p and identity)) else "ask_profile"
        if identity:
            pc = identity.to_dict()

    while state != "finish":
        state, res, pc, di, de, model = _page_growth_step(
            console, builder, ai, state, user, is_auto, identity, pc, di, de, model
        )
        if res:
            if res == _tui_continue(console) and ws and pc:
                ws.save_identity(Identity(name=ws.context.user, **pc))
            return res
    return "next"


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 5/7 — Tax Configuration
# ═══════════════════════════════════════════════════════════════════════


def _handle_payroll_tax_estimation(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant,
    formatted_taxable: list[str],
    country: str,
    meta: list[dict],
) -> None:
    """Handles AI-driven effective payroll tax estimation."""
    taxable_parents = set()
    for t in formatted_taxable:
        delim = SimulationDefaults.SUBCATEGORY_DELIMITER
        taxable_parents.add(t.split(delim, 1)[0] if delim in t else t)

    monthly_income = sum(m["avg_monthly"] for m in meta if m["name"] in taxable_parents)

    use_ai = _tui_bool(
        console,
        _t("tax_no_payment_detected") + "\n  " + _t("tax_estimate_prompt", country),
        True,
    )
    if not use_ai:
        return

    console.print("    " + _t("tax_estimating_hint"))
    with Spinner(_t("tax_estimating", country)):
        estimate = ai.estimate_effective_payroll_tax(
            country=country, monthly_income=monthly_income
        )

    if estimate and estimate.estimated_rate > 0:
        console.print(f"\n  {_t('tax_estimate_title')}")
        console.print(
            f"  {_t('tax_effective_rate')} {estimate.estimated_rate * 100:.1f}%"
        )
        console.print(f"  {estimate.reasoning}\n")

        if _tui_bool(console, _t("tax_apply_estimate"), True):
            builder.set_estimated_effective_tax_rate(estimate.estimated_rate)
            console.print(
                f"    {_t('tax_estimate_saved', estimate.estimated_rate * 100)}"
            )
        else:
            console.print("    " + _t("tax_estimate_discarded"))
    else:
        console.print("    " + _t("tax_estimate_warning"))


def _handle_ai_tax_rules(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant,
    country: str,
    formatted_tax_cats: list[str],
) -> None:
    """Handles AI-driven detailed tax rule building."""
    if not _tui_bool(console, _t("tax_ai_rules_prompt", country), True):
        return

    console.print("    " + _t("tax_rules_hint"))
    with Spinner(_t("tax_analyzing_rules", country)):
        acc_meta = [
            {
                "name": n,
                "account_type": (
                    builder.account_overrides.get(n, {}).get(
                        "account_type", builder._infer_account_type(n)
                    )
                ),
            }
            for n in builder.detected_accounts
        ]
        config = ai.build_tax_rules(
            country=country,
            accounts=acc_meta,
            tax_expense_categories=formatted_tax_cats,
        )

    if config:
        console.print(f"\n  {_t('tax_ai_analysis_title')}")
        console.print(
            f"  {_t('ui_country')}: {config.country}  ·  {config.tax_regime_summary}\n"
        )
        console.print("  " + _t("tax_rules_label"))
        for rule in config.rules:
            console.print(f"  ▸ {rule.name}  — {rule.rate * 100:.0f}% on {rule.base}")
            exempt = set(rule.exempt_accounts) if rule.exempt_accounts else set()
            applied = sorted(set(builder.detected_accounts) - exempt)
            if applied:
                applied_str = ", ".join(applied[:6]) + (
                    " …" if len(applied) > 6 else ""
                )
                console.print(f"    {_t('ui_applied')}: {applied_str}")
        console.print()

        if _tui_bool(console, _t("tax_apply_rules"), True):
            builder.set_tax_rules(
                [
                    {
                        "name": r.name,
                        "base": r.base,
                        "rate": r.rate,
                        "exempt_accounts": r.exempt_accounts,
                        "deduct_from": r.deduct_from,
                        "apply_only_to_positive": r.apply_only_to_positive,
                        "timing": "monthly",
                    }
                    for r in config.rules
                ]
            )
            console.print("    " + _t("tax_rules_saved"))
        else:
            console.print("    " + _t("tax_rules_discarded"))
    else:
        console.print("    " + _t("tax_rules_warning"))


def _tax_handle_taxable(console: Console, groups: dict) -> list[str] | None:
    taxable = hierarchical_checklist(
        console, _t("tax_select_taxable"), groups, default_val=False, back_key="q"
    )
    if taxable is None:
        return None
    delim = SimulationDefaults.SUBCATEGORY_DELIMITER
    return [t.replace(" > ", delim) for t in taxable]


def _tax_handle_cats(console: Console, groups: dict) -> list[str] | None:
    tax_cats = hierarchical_checklist(
        console, _t("tax_select_payment"), groups, default_val=False, back_key="q"
    )
    if tax_cats is None:
        return None
    delim = SimulationDefaults.SUBCATEGORY_DELIMITER
    return [t.replace(" > ", delim) for t in tax_cats]


def _tax_step_est_payroll(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    ws: WorkspaceManager | None,
    fmt_taxable: list[str],
    meta: list[dict],
) -> None:
    id_info = ws.load_identity() if ws else None
    country = (
        id_info.location
        if id_info and id_info.location
        else prompt(_t("tax_country_prompt"), "")
    )
    if country and ai:
        _handle_payroll_tax_estimation(console, builder, ai, fmt_taxable, country, meta)


def _tax_step_ai_rules(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    ws: WorkspaceManager | None,
    fmt_tax_cats: list[str],
) -> None:
    id_info = ws.load_identity() if ws else None
    country = (
        id_info.location
        if id_info and id_info.location
        else prompt(_t("tax_country_rules_prompt"), "")
    )
    if country and ai:
        _handle_ai_tax_rules(console, builder, ai, country, fmt_tax_cats)


def _page_tax_step(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    ws: WorkspaceManager | None,
    state: str,
    user: str,
    fmt_taxable: list[str],
    fmt_tax_cats: list[str],
    inc_groups: dict,
    exp_groups: dict,
    meta: list[dict],
) -> tuple[str, str | None, list[str], list[str]]:
    """Processes a single step of the tax page."""
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_tax"))

    if state == "taxable":
        res = _tax_handle_taxable(console, inc_groups)
        if res is None:
            return "back", "back", fmt_taxable, fmt_tax_cats
        builder.set_taxable_income(res)
        return "tax_cats", None, res, fmt_tax_cats

    if state == "tax_cats":
        res = _tax_handle_cats(console, exp_groups)
        if res is None:
            return "taxable", None, fmt_taxable, fmt_tax_cats
        builder.set_tax_categories(res)
        next_s = (
            "est_payroll_tax"
            if (not res and fmt_taxable and ai and ai.is_available())
            else ("ai_tax" if (ai and ai.is_available()) else "finish")
        )
        return next_s, None, fmt_taxable, res

    if state == "est_payroll_tax":
        _tax_step_est_payroll(console, builder, ai, ws, fmt_taxable, meta)
        return (
            ("ai_tax" if (ai and ai.is_available()) else "finish"),
            None,
            fmt_taxable,
            fmt_tax_cats,
        )

    if state == "ai_tax":
        _tax_step_ai_rules(console, builder, ai, ws, fmt_tax_cats)
        return "finish", None, fmt_taxable, fmt_tax_cats

    if state == "finish":
        return "finish", _tui_continue(console), fmt_taxable, fmt_tax_cats

    return "finish", "next", fmt_taxable, fmt_tax_cats


def _page_tax(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    ws: WorkspaceManager | None,
    user: str,
    is_auto: bool = False,
) -> str:
    state = "finish" if is_auto else "taxable"
    fmt_t: list[str] = []
    fmt_c: list[str] = []
    meta = builder.get_category_metadata()
    ig = {
        m["name"]: builder.sub_categories_map.get(m["name"], [])
        for m in meta
        if m["net_flow"] > 0
    }
    en = [c for c in builder.detected_categories if c not in ig]
    eg = {
        c: builder.sub_categories_map.get(c, [])
        for c in sorted(en, key=lambda x: ("tax" not in x.lower(), x))
    }

    while state != "finish":
        state, res, fmt_t, fmt_c = _page_tax_step(
            console, builder, ai, ws, state, user, fmt_t, fmt_c, ig, eg, meta
        )
        if res:
            if res == _tui_continue(console) and not is_auto:
                console.print("  " + _t("tax_config_saved") + "\n")
            return res
    return "next"


# ═══════════════════════════════════════════════════════════════════════
# Page: Market Assumptions
# ═══════════════════════════════════════════════════════════════════════


def _market_map_assets(console: Console, builder: ScenarioBuilder) -> None:
    """Infers asset classes for detected accounts and displays mappings."""
    console.print("    " + _t("market_assets_title") + "\n")
    for name in builder.detected_accounts:
        existing = builder.account_overrides.get(name, {})
        inferred = builder.infer_asset_class(
            name, existing.get("account_type", AccountType.CASH.value)
        )
        existing["asset_class"] = inferred
        builder.configure_account(name, asset_class=inferred)
        if inferred:
            console.print("    " + _t("market_asset_mapped", name, inferred))


def _market_handle_save(
    builder: ScenarioBuilder, enable_mr: bool, mr_decay: float
) -> str:
    market_assumptions = {
        "mean_reversion_enabled": enable_mr,
        "mean_reversion_decay": mr_decay,
        "asset_correlations": (SimulationDefaults.DEFAULT_ASSET_CORRELATIONS),
        "long_term_returns": (SimulationDefaults.DEFAULT_LONG_TERM_RETURNS),
    }
    builder.set_market_assumptions(market_assumptions)
    return "    " + _t("market_saved")


def _market_step_ask_mr(console: Console) -> tuple[str, str | None, bool]:
    console.print("\n    " + _t("market_mr_title") + "\n")
    res = _tui_bool(console, _t("market_mr_prompt"), True)
    if res is None:
        return "show_assets", None, True
    return ("prompt_mr" if res else "ask_save"), None, bool(res)


def _page_market_step(
    console: Console,
    builder: ScenarioBuilder,
    state: str,
    user: str,
    enable_mr: bool,
    mr_decay: float,
    save_msg: str,
) -> tuple[str, str | None, bool, float, str]:
    """Processes a single step of the market page."""
    console.clear()
    cli_header(console, user, _t("bootstrap"), _t("step_market"))

    if state == "ask_configure":
        res = _tui_bool(console, _t("market_prompt"), True)
        if res is None:
            return "back", "back", enable_mr, mr_decay, save_msg
        if not res:
            return "finish", None, enable_mr, mr_decay, "    " + _t("market_skipped")
        return "show_assets", None, enable_mr, mr_decay, save_msg

    if state == "show_assets":
        _market_map_assets(console, builder)
        return "ask_mr", None, enable_mr, mr_decay, save_msg

    if state == "ask_mr":
        ns, fr, emr = _market_step_ask_mr(console)
        return ns, fr, emr, mr_decay, save_msg

    if state == "prompt_mr":
        mrd = prompt_float("    " + _t("market_mr_speed"), -3.0, -5.0, -0.1)
        return "ask_save", None, enable_mr, mrd, save_msg

    if state == "ask_save":
        res = _tui_bool(console, _t("market_save_prompt"), True)
        if res is None:
            return "ask_mr", None, enable_mr, mr_decay, save_msg
        sm = (
            _market_handle_save(builder, enable_mr, mr_decay)
            if res
            else "    " + _t("market_discarded")
        )
        return "finish", None, enable_mr, mr_decay, sm

    if state == "finish":
        return "finish", _tui_continue(console), enable_mr, mr_decay, save_msg

    return "finish", "next", enable_mr, mr_decay, save_msg


def _page_market(
    console: Console, builder: ScenarioBuilder, user: str, is_auto: bool = False
) -> str:
    state = "finish" if is_auto else "ask_configure"
    emr, mrd, sm = True, -3.0, ""

    while state != "finish":
        state, res, emr, mrd, sm = _page_market_step(
            console, builder, state, user, emr, mrd, sm
        )
        if res:
            if res == _tui_continue(console):
                console.print(f"{sm}\n")
            return res
    return "next"


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 6/7 — Account Setup
# ═══════════════════════════════════════════════════════════════════════


def _page_accounts(
    console: Console, builder: ScenarioBuilder, is_auto: bool, user: str
) -> str:
    acc_map = getattr(builder, "_ai_acc_map", {})
    curr = builder.scenario["currency"]
    names = builder.detected_accounts

    if not names:
        return _tui_continue(console)

    i = 0
    while i < len(names):
        console.clear()
        cli_header(console, user, _t("bootstrap"), _t("step_accounts"))

        name = names[i]
        bal = builder.balances.get(name, 0.0)
        p = acc_map.get(name)
        inf_type = p.account_type.value if p else builder._infer_account_type(name)
        inf_ret = (
            p.annual_return if p else builder._infer_account_return(name, inf_type)
        )

        console.print(
            f"  ▸ {name} ({format_currency(bal, builder.currencies.get(name, curr))})"
        )
        if is_auto:
            t, r = inf_type, inf_ret
            console.print(
                "    " + _t("ai_classify_auto", _t("account_type_" + t), r * 100)
            )
        else:
            type_map = {_t("account_type_" + e.value): e.value for e in AccountType}
            t_display = _tui_choice_str(
                console,
                _t("account_type_label"),
                list(type_map.keys()),
                _t("account_type_" + inf_type),
            )
            if t_display is None:
                if i > 0:
                    i -= 1
                continue
            t = type_map[t_display]
            r = prompt_float("    " + _t("ui_return"), inf_ret, -0.5, 0.5)
        builder.configure_account(name, account_type=t, annual_return=r)
        i += 1

    return _tui_continue(console)


# ═══════════════════════════════════════════════════════════════════════
# Page: Step 7/7 — Category Setup
# ═══════════════════════════════════════════════════════════════════════


def _page_categories(
    console: Console, builder: ScenarioBuilder, is_auto: bool, user: str
) -> str:
    cat_map = getattr(builder, "_ai_cat_map", {})
    names = builder.detected_categories

    if not names:
        return _tui_continue(console)

    i = 0
    while i < len(names):
        console.clear()
        cli_header(console, user, _t("bootstrap"), _t("step_categories"))

        name = names[i]
        subs = builder.sub_categories_map.get(name, [])
        p = cat_map.get(name)

        cat_transactions = builder.transactions[
            builder.transactions["primary_category"] == name
        ]
        has_positive = any(t["amount"] > 0 for t in cat_transactions.to_dict("records"))
        inf_role = (
            p.role.value
            if p
            else (
                FinancialRole.INCOME.value
                if has_positive
                else FinancialRole.EXPENSE.value
            )
        )

        console.print(f"  ▸ {name} ({len(subs)} subs)")
        if is_auto:
            role = inf_role
        else:
            role_map = {_t("role_" + r.value): r.value for r in FinancialRole}
            role_display = _tui_choice_str(
                console,
                _t("category_role_label"),
                list(role_map.keys()),
                _t("role_" + inf_role),
            )
            if role_display is None:
                if i > 0:
                    i -= 1
                continue
            role = role_map[role_display]
            if role == FinancialRole.IGNORE.value:
                builder.configure_category(name, role=role)
                i += 1
                continue

        for s_name in subs:
            sp = next(
                (sp for sp in (p.sub_categories if p else []) if sp.name == s_name),
                None,
            )
            sub_transactions = builder.transactions[
                (builder.transactions["primary_category"] == name)
                & (builder.transactions["secondary_category"] == s_name)
            ]
            month_count = sub_transactions["month"].nunique()
            is_rec = (month_count / builder.total_months_count) > 0.4
            flex = sp.flexibility_score if sp else 3
            nes = sp.necessity_level.value if sp else NecessityLevel.DISCRETIONARY.value
            builder.configure_sub_category(
                name,
                s_name,
                is_recurring=is_rec,
                flexibility_score=flex,
                necessity_level=nes,
            )
        builder.configure_category(name, role=role)
        i += 1

    return _tui_continue(console)


# ═══════════════════════════════════════════════════════════════════════
# Page: Summary
# ═══════════════════════════════════════════════════════════════════════


def _recap_growth_policy(console: Console, policy: dict) -> None:
    inc_rate = policy.get("default_income_growth", 0)
    exp_rate = policy.get("default_expense_growth", 0)
    infl = policy.get("inflation_rate", 0)
    dyn_inc = policy.get("dynamic_income_growth")
    dyn_exp = policy.get("dynamic_expense_growth")

    console.print(f"\n  [bold]{_t('recap_growth_policy')}[/bold]")
    if dyn_inc and dyn_exp:
        console.print(f"    [bold]{_t('recap_dynamic_model')}[/bold]")
        console.print(
            "      "
            + _t("recap_dyn_income_fmt").format(
                dyn_inc["initial_rate"] * 100,
                dyn_inc["terminal_rate"] * 100,
                dyn_inc["transition_years"],
            )
        )
        console.print(
            "      "
            + _t("recap_dyn_expense_fmt").format(
                dyn_exp["initial_rate"] * 100,
                dyn_exp["terminal_rate"] * 100,
                dyn_exp["transition_years"],
            )
        )
    elif dyn_inc:
        console.print(f"    [bold]{_t('recap_dynamic_income_model')}[/bold]")
        console.print(
            "      "
            + _t("recap_dyn_income_fmt").format(
                dyn_inc["initial_rate"] * 100,
                dyn_inc["terminal_rate"] * 100,
                dyn_inc["transition_years"],
            )
        )
        console.print(f"    Expense:   {exp_rate * 100:+.1f}%")
    else:
        console.print(
            "    " + _t("recap_static_fmt").format(inc_rate * 100, exp_rate * 100)
        )
    console.print(f"    {_t('recap_inflation')} {infl * 100:.1f}%")


def _recap_tax_config(console: Console, s: dict) -> None:
    taxable = s.get("taxable_income_categories", [])
    tax_cats = s.get("tax_categories", [])
    eff_rate = s.get("estimated_effective_tax_rate")
    tax_rules = s.get("tax_rules", [])

    console.print(f"\n  [bold]{_t('recap_tax_config')}[/bold]")
    if taxable:
        shown = ", ".join(taxable[:8])
        console.print(f"    {_t('recap_taxable_income')} {shown}")
        if len(taxable) > 8:
            console.print("      " + _t("recap_more_items", len(taxable) - 8))
    else:
        console.print("    " + _t("recap_taxable_none"))
    if tax_cats:
        shown = ", ".join(tax_cats[:8])
        console.print(f"    {_t('recap_tax_categories')} {shown}")
        if len(tax_cats) > 8:
            console.print("      " + _t("recap_more_items", len(tax_cats) - 8))
    else:
        console.print("    " + _t("recap_tax_categories_none"))
    if eff_rate is not None:
        console.print(f"    {_t('recap_effective_tax_rate')} {eff_rate * 100:.1f}%")
    if tax_rules:
        msg = f"    {_t('recap_capital_gains_rules')} {len(tax_rules)} rule(s)"
        console.print(msg)
        for r in tax_rules[:3]:
            exempt = (
                f"  (exempt: {', '.join(r['exempt_accounts'])})"
                if r.get("exempt_accounts")
                else ""
            )
            name = r.get("name", "?")
            rate = r.get("rate", 0)
            base = r.get("base", "?")
            on_label = _t("recap_on")
            msg = f"      - {name}: {rate * 100:.0f}% {on_label} {base}{exempt}"
            console.print(msg)
        if len(tax_rules) > 3:
            console.print("      " + _t("recap_more_items", len(tax_rules) - 3))


def _recap_market_assumptions(console: Console, market: dict | None) -> None:
    console.print(f"\n  [bold]{_t('recap_market_title')}[/bold]")
    if market:
        mr = (
            _t("recap_mr_enabled")
            if market.get("mean_reversion_enabled")
            else _t("recap_mr_disabled")
        )
        mr_decay = market.get("mean_reversion_decay", 0)
        console.print(
            f"    {_t('recap_mean_reversion')} {mr} ({_t('recap_decay')} {mr_decay})"
        )
        lt_returns = market.get("long_term_returns", {})
        if lt_returns:
            parts = [f"{k}: {v * 100:.1f}%" for k, v in sorted(lt_returns.items())]
            console.print(f"    {_t('recap_long_term_returns')} {', '.join(parts)}")
    else:
        console.print("    " + _t("recap_not_configured"))


def _recap_accounts(console: Console, acc_cfg: dict, curr: str) -> None:
    label = _t("recap_accounts_title")
    msg = f"\n  [bold]{label}[/bold] {len(acc_cfg)} {_t('recap_total')}"
    console.print(msg)
    type_counts: dict[str, int] = {}
    for a in acc_cfg.values():
        t = a.get("account_type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
    type_parts = [
        f"{_t('account_type_' + t)}: {c}" for t, c in sorted(type_counts.items())
    ]
    console.print(f"    {_t('recap_types')} {', '.join(type_parts)}")

    top_accounts = sorted(
        acc_cfg.items(), key=lambda x: abs(x[1].get("initial_balance", 0)), reverse=True
    )[:8]
    for name, ac in top_accounts:
        bal, ac_curr, ret = (
            ac.get("initial_balance", 0),
            ac.get("currency", curr),
            ac.get("annual_return", 0),
        )
        asset = ac.get("asset_class", ac.get("account_type", "?"))
        name_s, bal_s = name[:28].ljust(29), format_currency(abs(bal), ac_curr)
        console.print(f"    {name_s} {asset:<10} {ret * 100:+.1f}%  {bal_s}")
    if len(acc_cfg) > 8:
        console.print("    " + _t("recap_more_accounts", len(acc_cfg) - 8))


def _recap_categories(console: Console, cat_cfg: dict) -> None:
    label = _t("recap_categories_title")
    msg = f"\n  [bold]{label}[/bold] {len(cat_cfg)} {_t('recap_total')}"
    console.print(msg)
    role_counts: dict[str, int] = {}
    role_examples: dict[str, list[str]] = {}
    for name, c in cat_cfg.items():
        role = c.get("role", "?")
        role_counts[role] = role_counts.get(role, 0) + 1
        role_examples.setdefault(role, []).append(name)
    for role in (
        FinancialRole.INCOME.value,
        FinancialRole.EXPENSE.value,
        FinancialRole.IGNORE.value,
    ):
        if role in role_counts:
            examples = role_examples[role][:5]
            detail = ", ".join(examples)
            extra = len(role_examples[role]) - 5
            if extra > 0:
                detail += f" (+{extra} {_t('recap_more')})"
            label = _t("role_" + role)
            console.print(
                "    "
                + _t("recap_categories_fmt").format(
                    role=label, count=role_counts[role], examples=detail
                )
            )


def _recap_display_overview(console: Console, s: dict, worth: float, curr: str) -> None:
    console.print(f"  [bold]{_t('recap_scenario')}[/bold] {s['name']}")
    console.print(
        f"  [bold]{_t('recap_snapshot')}[/bold] {s.get('snapshot_name', '?')}"
    )
    msg = _t("recap_sim_fmt").format(
        years=s.get("years", "?"), iterations=s.get("iterations", 0), currency=curr
    )
    console.print(f"  [bold]{_t('recap_simulation')}[/bold] {msg}")
    console.print(
        f"  [bold]{_t('recap_date_range')}[/bold] "
        f"{s.get('start_date', '?')} → {s.get('end_date', '?')}"
    )
    console.print(
        f"  [bold]{_t('recap_net_worth')}[/bold] {format_currency(worth, curr)}"
    )


def _auto_save(
    console: Console,
    builder: ScenarioBuilder,
    ws: WorkspaceManager | None,
    user: str,
) -> str:
    """Show recap and ask for confirmation before saving in Quick Setup mode."""
    while True:
        console.clear()
        cli_header(console, user, _t("bootstrap"), _t("recap_title"))

        s = builder.scenario
        worth = builder._compute_net_worth_eur()
        curr = s.get("currency", ExchangeRates.BASE_CURRENCY)

        _recap_display_overview(console, s, worth, curr)
        _recap_growth_policy(console, s.get("growth_policy", {}))
        _recap_tax_config(console, s)
        _recap_market_assumptions(console, s.get("market_assumptions"))
        _recap_accounts(console, builder._build_accounts_config(), curr)
        _recap_categories(console, builder._build_categories_config())

        console.print()
        items = [_t("recap_save_btn"), _t("recap_go_back"), _t("recap_discard_btn")]
        descs = [
            _t("recap_save_desc"),
            _t("recap_go_back_desc"),
            _t("recap_discard_desc"),
        ]
        idx = tui_choice(console, None, items, descs, back_label="back")
        if idx is None or idx == 2:
            if idx == 2:
                console.print("\n  " + _t("recap_discarded"))
            return "quit"
        if idx == 1:
            return "back"

        scenario_name = s["name"]
        out_dir = (
            ws.get_scenario_dir(scenario_name)
            if ws
            else os.path.join(PathConfig.SIM_SCENARIOS_DIR, scenario_name)
        )
        os.makedirs(out_dir, exist_ok=True)
        builder.write(out_dir)
        console.print(f"\n  [green]{_t('recap_saved', scenario_name)}[/green]")
        hint = _t(
            "recap_run_hint",
            ws.context.user if ws else "default_user",
            scenario_name,
        )
        console.print("  " + hint)
        input("\n  Press Enter to continue...")
        return "quit"


def _page_summary(
    console: Console,
    builder: ScenarioBuilder,
    ws: WorkspaceManager | None,
    user: str,
    is_auto: bool = False,
) -> str:
    if is_auto:
        return _auto_save(console, builder, ws, user)

    while True:
        console.clear()
        cli_header(console, user, _t("bootstrap"), _t("step_summary"))
        summary_worth = builder._compute_net_worth_eur()
        console.print(
            f"  {_t('summary_name')} {builder.scenario['name']}\n"
            f"  {_t('summary_net_worth')} {format_currency(summary_worth, 'EUR')}\n"
        )
        items = [_t("summary_write_save"), _t("summary_go_back"), _t("summary_quit")]
        descs = [
            _t("summary_write_desc"),
            _t("summary_go_back_desc"),
            _t("summary_quit_desc"),
        ]
        idx = tui_choice(console, None, items, descs, back_label="back")
        if idx is None or idx == 2:
            if idx == 2:
                console.print("\n  " + _t("recap_discarded"))
            return "quit"
        if idx == 1:
            return "back"

        scenario_name = builder.scenario["name"]
        out_dir = (
            ws.get_scenario_dir(scenario_name)
            if ws
            else os.path.join(PathConfig.SIM_SCENARIOS_DIR, scenario_name)
        )
        os.makedirs(out_dir, exist_ok=True)
        builder.write(out_dir)
        console.print(
            "\n  "
            + _t(
                "recap_run_hint",
                ws.context.user if ws else "default_user",
                scenario_name,
            )
        )
        input("\n  Press Enter to continue...")
        return "quit"
