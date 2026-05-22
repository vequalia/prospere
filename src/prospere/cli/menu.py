"""Unified CLI entry point with TUI navigation and scenario management."""

import os
import sys
from typing import Any

from rich.console import Console
from rich.theme import Theme

from prospere.cli.i18n import (
    MENU_I18N,
    _detect_lang,
    _set_language,
    _t,
    get_language,
)
from prospere.cli.utils import Spinner, cli_header, hierarchical_checklist, tui_choice
from prospere.core.constants import (
    AccountType,
    FinancialRole,
    NecessityLevel,
    UITheme,
    WorkspaceConfig,
)
from prospere.core.models import Identity, WorkspaceContext
from prospere.core.settings import settings_manager
from prospere.core.workspace import WorkspaceManager
from prospere.simulation.scenario import ScenarioRepository

# ── Theme ──────────────────────────────────────────────────────────────
MENU_THEME = Theme(UITheme.THEME_DICT)


def _launch_bootstrap(user: str) -> None:
    old_argv = sys.argv[:]
    sys.argv = ["prospere-bootstrap", "--user", user, "--lang", get_language()]
    try:
        from prospere.cli.bootstrap import run_bootstrap_cli

        run_bootstrap_cli()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv


def _launch_chat(user: str, scenario: str | None = None) -> None:
    old_argv = sys.argv[:]
    base = [
        "prospere-chat",
        "--user",
        user,
        "--lang",
        get_language(),
    ]
    if scenario:
        base += ["--scenario", scenario]
    sys.argv = base
    try:
        from prospere.cli.chat import run_chat_cli

        run_chat_cli()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv


def _has_datasets(user: str) -> bool:
    ws = WorkspaceManager(WorkspaceContext(user=user))
    root = ws.get_datasets_root()
    return os.path.exists(root) and bool(os.listdir(root))


def _prompt_snapshot(ws: WorkspaceManager) -> str | None:
    """Prompt for snapshot name, checking overwrite. Returns name or None."""
    snapshot = input(f"  {_t('enter_snapshot_name')} [default]: ").strip()
    if not snapshot:
        snapshot = "default"
    snap_dir = os.path.join(ws.get_datasets_root(), snapshot)
    if os.path.isdir(snap_dir) and os.listdir(snap_dir):
        prompt = f"  {_t('snapshot_exists', snapshot)} [y/N]: "
        if input(prompt).strip().lower() != "y":
            return None
    return snapshot


def _import_data_menu(console: Console, user: str) -> bool:
    """Interactive data import. Returns True if import succeeded."""
    from prospere.cli.process import import_preprocessed, ingest_moneywiz

    ws = WorkspaceManager(WorkspaceContext(user=user))

    console.clear()
    cli_header(console, user, _t("import_data"))
    idx = tui_choice(
        console,
        None,
        [_t("source_moneywiz"), _t("source_preprocessed")],
        back_label=_t("back"),
    )
    if idx is None:
        return False

    if idx == 0:
        default_csv = os.path.join(ws.get_raw_dir(), WorkspaceConfig.RAW_CSV_FILENAME)
        csv_path = input(f"  {_t('enter_csv_path')} [{default_csv}]: ").strip()
        if not csv_path:
            csv_path = default_csv

        snapshot = _prompt_snapshot(ws)
        if snapshot is None:
            return False

        with Spinner(_t("importing_data")):
            success, msg = ingest_moneywiz(user, snapshot, csv_path)
    else:
        xlsx_path = input(f"  {_t('enter_xlsx_path')}: ").strip()
        json_path = input(f"  {_t('enter_json_path')}: ").strip()
        if not xlsx_path or not json_path:
            print(f"\n  ✗ {_t('ui_both_paths_required')}")
            input(f"  {_t('press_enter')}")
            return False

        snapshot = _prompt_snapshot(ws)
        if snapshot is None:
            return False

        with Spinner(_t("importing_data")):
            success, msg = import_preprocessed(user, snapshot, xlsx_path, json_path)

    print()
    if success:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")

    input(f"\n  {_t('press_enter')}")
    return success


# ═══════════════════════════════════════════════════════════════════════
# Generic editing helpers
# ═══════════════════════════════════════════════════════════════════════


def _edit_field(label: str, current: str) -> str:
    raw = input(f"  {label} [{current}]: ").strip()
    return raw if raw else current


def _edit_int(label: str, current: int, min_val: int, max_val: int) -> int:
    raw = input(f"  {label} [{current}]: ").strip()
    if not raw:
        return current
    try:
        val = int(raw)
        if min_val <= val <= max_val:
            return val
    except ValueError:
        pass
    return current


def _edit_float(label: str, current: float) -> float:
    raw = input(f"  {label} [{current:.4f}]: ").strip()
    if not raw:
        return current
    try:
        return float(raw)
    except ValueError:
        return current


def _edit_percent(label: str, current: float) -> float:
    raw = input(f"  {label} [{current * 100:.1f}%]: ").strip()
    if not raw:
        return current
    try:
        return float(raw) / 100
    except ValueError:
        return current


# ═══════════════════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════════════════


def _load_config_managers(
    repo: ScenarioRepository, scenario_name: str
) -> tuple[Any, Any]:
    from prospere.simulation.config import (
        AccountConfigurationManager,
        CategoryConfigurationManager,
    )

    paths = repo.get_configuration_file_paths(scenario_name)
    cat_mgr = CategoryConfigurationManager(paths["category_config"])
    acc_mgr = AccountConfigurationManager(paths["account_config"])
    cat_mgr.load_from_disk()
    acc_mgr.load_from_disk()
    return cat_mgr, acc_mgr


# ═══════════════════════════════════════════════════════════════════════
# Metadata summary (shared by overview and edit)
# ═══════════════════════════════════════════════════════════════════════


def _print_metadata_summary(console: Console, meta: Any) -> None:
    gp = meta.growth_policy
    console.print(
        f"  [meta]Years {meta.years}  ·  Iterations {meta.iterations:,}"
        f"  ·  {meta.currency}  ·  Snapshot {meta.snapshot_name}[/meta]"
    )
    if gp:
        parts: list[str] = []
        # Income
        if gp.dynamic_income_growth:
            dg = gp.dynamic_income_growth
            parts.append(
                _t("income_dyn_fmt", dg.initial_rate * 100, dg.terminal_rate * 100)
            )
        else:
            parts.append(_t("income_fmt", gp.default_income_growth * 100))
        # Expense
        if gp.dynamic_expense_growth:
            dg = gp.dynamic_expense_growth
            parts.append(
                _t("expense_dyn_fmt", dg.initial_rate * 100, dg.terminal_rate * 100)
            )
        else:
            parts.append(_t("expense_fmt", gp.default_expense_growth * 100))
        parts.append(_t("inflation_fmt", gp.inflation_rate * 100))
        console.print(f"  [meta]{_t('growth')}: {'  ·  '.join(parts)}[/meta]")
    console.print()


# ═══════════════════════════════════════════════════════════════════════
# L1: Scenario list
# ═══════════════════════════════════════════════════════════════════════


def _scenario_menu(console: Console, user: str) -> None:
    repo = ScenarioRepository(WorkspaceManager(WorkspaceContext(user=user)))
    scenarios = repo.list_available_scenarios()

    if not scenarios:
        console.clear()
        cli_header(console, user, _t("scenarios"))
        console.print(f"[meta]{_t('no_scenarios_yet')}[/meta]")
        console.print(f"[meta]{_t('create_one_message')}[/meta]\n")
        input(f"  {_t('press_enter')}")
        return

    sorted_scenarios = sorted(scenarios)
    items = [_t("new_scenario_btn")] + sorted_scenarios
    title = f"{user}  ›  {_t('scenarios')}"

    while True:
        console.clear()
        idx = tui_choice(
            console,
            title,
            items,
            delete_key="d",
            delete_label=_t("delete_label"),
        )
        if idx is None:
            return
        if idx == 0:
            _launch_bootstrap(user)
            scenarios = repo.list_available_scenarios()
            if not scenarios:
                console.clear()
                cli_header(console, user, _t("scenarios"))
                console.print(f"[meta]{_t('no_scenarios_remaining')}[/meta]")
                console.print(f"[meta]{_t('create_one_short')}[/meta]\n")
                input(f"  {_t('press_enter')}")
                return
            sorted_scenarios = sorted(scenarios)
            items = [_t("new_scenario_btn")] + sorted_scenarios
        elif idx == -2:
            _delete_scenario(console, repo, sorted_scenarios)
            scenarios = repo.list_available_scenarios()
            if not scenarios:
                console.clear()
                cli_header(console, user, _t("scenarios"))
                console.print(f"[meta]{_t('no_scenarios_remaining')}[/meta]")
                console.print(f"[meta]{_t('create_one_short')}[/meta]\n")
                input(f"  {_t('press_enter')}")
                return
            sorted_scenarios = sorted(scenarios)
            items = [_t("new_scenario_btn")] + sorted_scenarios
        else:
            _scenario_overview(console, repo, sorted_scenarios[idx - 1], user)


def _delete_scenario(
    console: Console, repo: ScenarioRepository, names: list[str]
) -> None:
    """Select and delete a scenario with confirmation."""
    idx = tui_choice(console, _t("delete_scenario_title"), names)
    if idx is None:
        return

    name = names[idx]
    import shutil

    dir_path = repo.resolve_scenario_directory(name)
    if not os.path.exists(dir_path):
        console.print(f"\n[meta]{_t('scenario_not_found', name)}[/meta]")
        input(f"  {_t('press_enter')}")
        return

    confirm = input(f"\n  {_t('delete_confirm', name)} [y/N]: ").strip()
    if confirm.lower() == "y":
        shutil.rmtree(dir_path)
        console.print(f"\n[success]{_t('deleted', name)}[/success]")
        input(f"  {_t('press_enter')}")


# ═══════════════════════════════════════════════════════════════════════
# L2: Scenario overview → drill into categories / accounts / tax / edit
# ═══════════════════════════════════════════════════════════════════════


def _scenario_overview(
    console: Console,
    repo: ScenarioRepository,
    name: str,
    user: str,
) -> None:
    meta = repo.retrieve_scenario_metadata(name)
    cat_mgr, acc_mgr = _load_config_managers(repo, name)
    categories = dict(cat_mgr.registry) if cat_mgr else {}
    accounts = dict(acc_mgr.registry) if acc_mgr else {}

    while True:
        console.clear()
        cli_header(console, user, _t("scenarios"), name)
        _print_metadata_summary(console, meta)

        sections = [
            _t("categories_section", len(categories)),
            _t("accounts_section", len(accounts)),
            _t("tax_config"),
            _t("edit_metadata"),
        ]
        descs = [
            ", ".join(sorted(categories.keys())[:5]),
            ", ".join(a for a in sorted(accounts.keys())[:5]),
            _t(
                "taxable_desc",
                len(meta.taxable_income_categories),
                len(meta.tax_categories),
            ),
            _t("metadata_desc"),
        ]

        idx = tui_choice(console, None, sections, descs, "e", _t("edit"))
        if idx is None:
            return

        if idx == 0:
            _category_list(console, cat_mgr, name, user)
        elif idx == 1:
            _account_list(console, acc_mgr, name, user)
        elif idx == 2:
            _edit_tax(console, repo, meta, categories, name, user)
        elif idx == 3 or idx == -1:
            _edit_metadata(console, repo, meta, name, user)


# ═══════════════════════════════════════════════════════════════════════
# L3 / L4: Categories — list → detail → edit
# ═══════════════════════════════════════════════════════════════════════


def _category_list(
    console: Console, cat_mgr: Any, scenario_name: str, user: str
) -> None:
    names = sorted(cat_mgr.registry.keys())
    if not names:
        _show_empty(console, _t("categories_title"), scenario_name, user)
        return

    while True:
        descs = [_fmt_category_row(cat_mgr.registry[n]) for n in names]
        cur = [0]
        idx = tui_choice(
            console,
            f"{user}  ›  {scenario_name}  ›  {_t('categories_title')}",
            names,
            descs,
            "e",
            _t("edit"),
            cursor_ref=cur,
        )
        if idx is None:
            return
        if idx == -1:
            _edit_category(console, cat_mgr, names, names[cur[0]], user)
        else:
            _category_detail(console, cat_mgr, names[idx], scenario_name, user)


def _fmt_category_row(data: dict) -> str:
    role = data.get("role", "?")
    growth = data.get("annual_growth_rate", 0)
    flexible = data.get("flexibility_score", "?")
    subs = len(data.get("sub_categories", {}))
    parts = [
        f"{_t('category_role_label')}={role}",
        f"{_t('ui_growth_rate')}={growth * 100:.1f}%",
        f"{_t('ui_flexibility')}={flexible}",
    ]
    if subs:
        parts.append(f"subs={subs}")
    return "  ·  ".join(parts)


def _category_detail(
    console: Console, cat_mgr: Any, cat_name: str, scenario_name: str, user: str
) -> None:
    data = cat_mgr.registry.get(cat_name, {})
    subs = data.get("sub_categories", {})

    while True:
        console.clear()
        cli_header(console, user, scenario_name, cat_name)
        _print_category_fields(console, data)
        if subs:
            console.print(f"  [meta]{_t('sub_categories')}[/meta]")
            for sub_name in sorted(subs):
                sub = subs[sub_name]
                console.print(
                    f"    [meta]{sub_name}  "
                    f"{_t('ui_flexibility')}={sub.get('flexibility_score', '?')}  "
                    f"{_t('ui_growth_rate')}="
                    f"{(sub.get('annual_growth_rate') or 0) * 100:.1f}%"
                    f"[/meta]"
                )
        console.print()
        input(f"  {_t('press_enter')}")
        return


def _print_category_fields(console: Console, data: dict) -> None:
    fields = [
        (_t("category_role_label"), str(data.get("role", "-"))),
        (_t("ui_recurring"), str(data.get("is_recurring", "-"))),
        (_t("ui_flexibility"), str(data.get("flexibility_score", "-"))),
        (_t("ui_necessity"), str(data.get("necessity_level", "-"))),
        (_t("ui_growth_rate"), f"{data.get('annual_growth_rate', 0) * 100:.1f}%"),
        (_t("ui_income_linked"), f"{data.get('income_linked_rate', 0):.2f}"),
    ]
    for label, value in fields:
        console.print(f"  [meta]{label:<20}[/meta] {value}")


# ═══════════════════════════════════════════════════════════════════════
# Edit: Category
# ═══════════════════════════════════════════════════════════════════════


def _edit_category(
    console: Console, cat_mgr: Any, cat_names: list[str], cat_name: str, user: str
) -> None:
    data = cat_mgr.registry.get(cat_name, {})
    subs = data.get("sub_categories", {})

    console.clear()
    cli_header(console, user, cat_name, _t("edit_label"))
    _print_category_fields(console, data)

    console.print()
    new_role = _edit_field("role", str(data.get("role", FinancialRole.EXPENSE.value)))
    new_flex = _edit_int(
        f"{_t('ui_flexibility')} (0-10)", data.get("flexibility_score", 3), 0, 10
    )
    new_nec = _edit_field(
        _t("ui_necessity"),
        str(data.get("necessity_level", NecessityLevel.DISCRETIONARY.value)),
    )
    new_growth = _edit_percent(_t("ui_growth_rate"), data.get("annual_growth_rate", 0))
    new_linked = _edit_float(
        f"{_t('ui_income_linked')} (0-1)", data.get("income_linked_rate", 0)
    )

    data["role"] = new_role
    data["flexibility_score"] = new_flex
    data["necessity_level"] = new_nec
    data["annual_growth_rate"] = new_growth
    data["income_linked_rate"] = new_linked

    # Sub-categories
    if subs:
        console.print(f"\n  [meta]{_t('sub_categories')}[/meta]")
        sub_names = sorted(subs)
        for sub_name in sub_names:
            prompt = f"  {_t('edit_subcategory', sub_name)} [y/N]: "
            edit = input(prompt).strip().lower()
            if edit == "y":
                _edit_subcategory(subs[sub_name], sub_name)

    cat_mgr.save_to_disk()
    console.print(f"\n[success]{_t('category_saved')}[/success]")
    input(f"  {_t('press_enter')}")


def _edit_subcategory(sub: dict, name: str) -> None:
    sub["flexibility_score"] = _edit_int(
        f"  {name} {_t('ui_flexibility')} (0-10)",
        sub.get("flexibility_score", 3),
        0,
        10,
    )
    sub["necessity_level"] = _edit_field(
        f"  {name} {_t('ui_necessity')}",
        str(sub.get("necessity_level", NecessityLevel.DISCRETIONARY.value)),
    )
    if sub.get("annual_growth_rate") is not None:
        sub["annual_growth_rate"] = _edit_percent(
            f"  {name} {_t('ui_growth_rate')}",
            sub["annual_growth_rate"],
        )
    if sub.get("income_linked_rate") is not None:
        sub["income_linked_rate"] = _edit_float(
            f"  {name} {_t('ui_income_linked')} (0-1)",
            sub["income_linked_rate"],
        )


# ═══════════════════════════════════════════════════════════════════════
# L3 / L4: Accounts — list → detail → edit
# ═══════════════════════════════════════════════════════════════════════


def _account_list(
    console: Console, acc_mgr: Any, scenario_name: str, user: str
) -> None:
    names = sorted(acc_mgr.registry.keys())
    if not names:
        _show_empty(console, _t("accounts_title"), scenario_name, user)
        return

    while True:
        descs = [_fmt_account_row(acc_mgr.registry[n]) for n in names]
        cur = [0]
        idx = tui_choice(
            console,
            f"{user}  ›  {scenario_name}  ›  {_t('accounts_title')}",
            names,
            descs,
            "e",
            _t("edit"),
            cursor_ref=cur,
        )
        if idx is None:
            return
        if idx == -1:
            _edit_account(console, acc_mgr, names[cur[0]], user, scenario_name)
        else:
            _account_detail(console, acc_mgr, names[idx], scenario_name, user)


def _fmt_account_row(data: dict) -> str:
    atype = data.get("account_type", "?")
    ret = data.get("annual_return", 0) * 100
    bal = data.get("initial_balance", 0)
    return (
        f"{_t('account_type_label')}={atype}  ·  "
        f"{_t('ui_return')}={ret:.1f}%  ·  "
        f"balance={bal:,.0f}"
    )


def _account_detail(
    console: Console, acc_mgr: Any, acc_name: str, scenario_name: str, user: str
) -> None:
    data = acc_mgr.get_account_metadata(acc_name)
    console.clear()
    cli_header(console, user, scenario_name, acc_name)
    _print_account_fields(console, data)
    console.print()
    input(f"  {_t('press_enter')}")


def _print_account_fields(console: Console, data: dict) -> None:
    at = data.get("account_type", "-")
    at_str = at.value if hasattr(at, "value") else str(at)
    fields = [
        (_t("account_type_label"), at_str),
        (_t("sim_currency"), str(data.get("currency", "EUR"))),
        (_t("initial_capital"), f"{data.get('initial_balance', 0):,.2f}"),
        (
            _t("ui_return"),
            f"{data.get('annual_return', 0) * 100:.2f}%",
        ),
        (
            f"{_t('ui_return')} STD",
            f"{data.get('annual_return_std', 0) * 100:.2f}%",
        ),
        ("allocation_ratio", f"{data.get('allocation_ratio', 0):.4f}"),
        ("deposit_priority", str(data.get("deposit_priority", "-"))),
        (
            "max_balance",
            f"{data.get('max_balance', float('inf')):,.0f}",
        ),
    ]
    for label, value in fields:
        console.print(f"  [meta]{label:<20}[/meta] {value}")


# ═══════════════════════════════════════════════════════════════════════
# Edit: Account
# ═══════════════════════════════════════════════════════════════════════


def _edit_account(
    console: Console,
    acc_mgr: Any,
    acc_name: str,
    user: str,
    scenario_name: str,
) -> None:
    enriched = acc_mgr.get_account_metadata(acc_name)
    raw = acc_mgr.registry.setdefault(acc_name, {})

    console.clear()
    cli_header(console, user, scenario_name, acc_name, _t("edit_label"))
    _print_account_fields(console, enriched)

    console.print()
    at = enriched.get("account_type", AccountType.SAVINGS.value)
    account_type_value = at.value if hasattr(at, "value") else str(at)
    new_type = _edit_field(
        _t("ui_account_type_hint"),
        account_type_value,
    )
    new_bal = _edit_float("initial_balance", enriched.get("initial_balance", 0))
    new_ret = _edit_percent("annual_return", enriched.get("annual_return", 0))
    new_std = _edit_percent("annual_return_std", enriched.get("annual_return_std", 0))
    new_alloc = _edit_float("allocation_ratio", enriched.get("allocation_ratio", 0))
    new_prio = _edit_int(
        "deposit_priority", enriched.get("deposit_priority", 100), 0, 1000
    )
    max_val = enriched.get("max_balance", float("inf"))
    max_display = _t("unlimited") if max_val == float("inf") else f"{max_val:,.0f}"
    raw_max = input(f"  max_balance [{max_display}]: ").strip()
    new_max = float(raw_max) if raw_max else max_val

    raw["account_type"] = new_type
    raw["initial_balance"] = new_bal
    raw["annual_return"] = new_ret
    raw["annual_return_std"] = new_std
    raw["allocation_ratio"] = new_alloc
    raw["deposit_priority"] = new_prio
    raw["max_balance"] = new_max

    acc_mgr.save_to_disk()
    console.print(f"\n[success]{_t('account_saved')}[/success]")
    input(f"  {_t('press_enter')}")


# ═══════════════════════════════════════════════════════════════════════
# Edit: Metadata (scenario.json)
# ═══════════════════════════════════════════════════════════════════════


def _edit_metadata(
    console: Console, repo: ScenarioRepository, meta: Any, name: str, user: str
) -> None:
    from prospere.simulation.models import (
        GrowthPolicy,
        ScenarioMetadata,
    )

    gp = meta.growth_policy
    console.clear()
    cli_header(console, user, name, _t("edit_metadata_label"))
    _print_metadata_summary(console, meta)

    console.print()
    new_years = _edit_int(_t("years_label"), meta.years, 1, 100)
    new_iterations = _edit_int(_t("iterations_label"), meta.iterations, 100, 1_000_000)

    income = gp.default_income_growth if gp else 0.0
    expense = gp.default_expense_growth if gp else 0.0
    inflation = gp.inflation_rate if gp else 0.02
    overrides = dict(gp.category_overrides) if gp and gp.category_overrides else {}
    dyn_income = gp.dynamic_income_growth if gp else None
    dyn_expense = gp.dynamic_expense_growth if gp else None

    new_income = _edit_percent(_t("income_growth_label"), income)
    new_expense = _edit_percent(_t("expense_growth_label"), expense)
    new_inflation = _edit_percent(_t("inflation_label"), inflation)

    # Dynamic growth
    console.print(f"\n  [meta]{_t('dynamic_growth_hint')}[/meta]")
    new_dyn_income = _edit_dynamic_growth("income", dyn_income)
    new_dyn_expense = _edit_dynamic_growth("expense", dyn_expense)

    updated = ScenarioMetadata(
        name=name,
        initial_capital=meta.initial_capital,
        years=new_years,
        iterations=new_iterations,
        currency=meta.currency,
        start_date=meta.start_date,
        end_date=meta.end_date,
        growth_policy=GrowthPolicy(
            new_expense,
            new_income,
            new_inflation,
            overrides,
            new_dyn_income,
            new_dyn_expense,
        ),
        taxable_income_categories=meta.taxable_income_categories,
        tax_categories=meta.tax_categories,
        tax_rules=meta.tax_rules,
        estimated_effective_tax_rate=meta.estimated_effective_tax_rate,
        snapshot_name=meta.snapshot_name,
    )
    repo.persist_scenario_metadata(updated)
    console.print(f"\n[success]{_t('metadata_saved')}[/success]")
    input(f"  {_t('press_enter')}")


def _edit_dynamic_growth(label: str, current: Any) -> Any:
    from prospere.simulation.models import DynamicGrowth

    enable = input(f"  {_t('edit_dynamic', label)} [y/N]: ").strip().lower()
    if enable != "y":
        return current

    init = current.initial_rate if current else 0.08
    term = current.terminal_rate if current else 0.03
    trans = current.transition_years if current else 10

    init = _edit_percent(f"    {_t('initial_rate_fmt', label)}", init)
    term = _edit_percent(f"    {_t('terminal_rate_fmt', label)}", term)
    trans = _edit_int(f"    {_t('transition_years_fmt', label)}", trans, 1, 100)
    return DynamicGrowth(init, term, trans)


# ═══════════════════════════════════════════════════════════════════════
# Edit: Tax config
# ═══════════════════════════════════════════════════════════════════════


def _prepare_tax_groups(
    categories: dict, config_entries: list[str], role: str
) -> tuple[dict[str, list[str]], dict[str, bool]]:
    """Helper to build groups and initial selection for tax checklist."""
    groups: dict[str, list[str]] = {}
    init: dict[str, bool] = {}
    for cat, data in categories.items():
        if data.get("role") != role:
            continue
        sub_names = sorted(data.get("sub_categories", {}).keys())
        groups[cat] = sub_names
        init[cat] = cat in config_entries or any(
            f"{cat}::{s}" in config_entries for s in sub_names
        )
        for sub in sub_names:
            init[f"{cat} > {sub}"] = f"{cat}::{sub}" in config_entries
    return groups, init


def _edit_tax(
    console: Console,
    repo: ScenarioRepository,
    meta: Any,
    categories: dict,
    name: str,
    user: str,
) -> None:
    from prospere.simulation.models import (
        GrowthPolicy,
        ScenarioMetadata,
    )

    console.clear()
    cli_header(console, user, name, _t("tax_config_label"))

    if not categories:
        console.print(f"[meta]{_t('no_categories')}[/meta]\n")
        input(f"  {_t('press_enter')}")
        return

    # 1. Taxable income categories
    groups_taxable, init_taxable = _prepare_tax_groups(
        categories, meta.taxable_income_categories, "income"
    )
    console.clear()
    cli_header(console, user, name, _t("tax_config_label"))
    console.print(f"[meta]{_t('select_taxable')}[/meta]")
    taxable = hierarchical_checklist(
        console,
        _t("taxable_income_categories"),
        groups_taxable,
        initial_selected=init_taxable,
    )
    if taxable is None:
        return
    taxable_cats = [k.replace(" > ", "::") for k in taxable]

    # 2. Tax-rate categories
    groups_tax, init_tax = _prepare_tax_groups(
        categories, meta.tax_categories, "expense"
    )
    console.clear()
    cli_header(console, user, name, _t("tax_config_label"))
    console.print(f"[meta]{_t('select_tax_rate')}[/meta]")
    tax_rate = hierarchical_checklist(
        console,
        _t("tax_rate_categories"),
        groups_tax,
        initial_selected=init_tax,
    )
    if tax_rate is None:
        return
    tax_cats = [k.replace(" > ", "::") for k in tax_rate]

    gp = meta.growth_policy
    updated = ScenarioMetadata(
        name=name,
        initial_capital=meta.initial_capital,
        years=meta.years,
        iterations=meta.iterations,
        currency=meta.currency,
        start_date=meta.start_date,
        end_date=meta.end_date,
        growth_policy=GrowthPolicy(
            gp.default_expense_growth if gp else 0.0,
            gp.default_income_growth if gp else 0.0,
            gp.inflation_rate if gp else 0.02,
            dict(gp.category_overrides) if gp and gp.category_overrides else {},
            gp.dynamic_income_growth if gp else None,
            gp.dynamic_expense_growth if gp else None,
        ),
        taxable_income_categories=taxable_cats,
        tax_categories=tax_cats,
        tax_rules=meta.tax_rules,
        estimated_effective_tax_rate=meta.estimated_effective_tax_rate,
        snapshot_name=meta.snapshot_name,
    )
    repo.persist_scenario_metadata(updated)
    console.print(f"\n[success]{_t('tax_saved')}[/success]")
    input(f"  {_t('press_enter')}")


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _show_empty(console: Console, section: str, scenario_name: str, user: str) -> None:
    console.clear()
    cli_header(console, user, scenario_name, section)
    console.print(f"[meta]{_t('no_entries')}[/meta]\n")
    input(f"  {_t('press_enter')}")


# ═══════════════════════════════════════════════════════════════════════
# Top-level screens
# ═══════════════════════════════════════════════════════════════════════


def _get_users() -> list[str]:
    root = WorkspaceConfig.ROOT_DIR
    if not os.path.exists(root):
        return []
    return sorted(
        d
        for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and not d.startswith(".")
    )


def _select_user(console: Console, force_select: bool = False) -> str | None:
    users = _get_users()
    if not force_select and not users:
        return _create_user(console)

    # Try last used user if not forcing select
    if not force_select and settings_manager.last_user in users:
        return settings_manager.last_user

    if not force_select and len(users) == 1:
        user = users[0]
        settings_manager.last_user = user
        return user

    choices = users + [_t("new_user_choice")]
    back_label = _t("back") if force_select else _t("quit")
    idx = tui_choice(console, "", choices, back_label=back_label)
    if idx is None:
        return None
    if idx < len(users):
        user = users[idx]
        settings_manager.last_user = user
        return user
    return _create_user(console)


def _create_user(console: Console) -> str | None:
    console.clear()
    cli_header(console, _t("new_user_title"))
    console.print(f"[meta]{_t('enter_username')}[/meta]")
    console.print()
    name = input("  ").strip()
    if not name:
        return None
    ws = WorkspaceManager(WorkspaceContext(user=name))
    ws.ensure_structure()

    # Optionally collect user profile
    print(f"\n  ✨ {_t('fill_profile')} [y/N]:", end=" ")
    fill = input().strip().lower()
    if fill == "y":
        profile = {}
        fields = [
            ("age", _t("profile_age")),
            ("industry", _t("profile_industry")),
            ("location", _t("profile_location")),
            ("family_status", _t("profile_family")),
            ("financial_goal", _t("profile_goal")),
        ]
        for key, label in fields:
            val = input(f"    {label}: ").strip()
            if val:
                profile[key] = val
        if profile:
            identity = Identity(name=name, **profile)
            ws.save_identity(identity)

    settings_manager.last_user = name
    print(f"\n  ✓ {_t('ui_user_created', name)}")
    print(f"  📁 {_t('raw_dir_hint')}:")
    print(f"     {ws.get_raw_dir()}/")
    print()
    input(f"  {_t('press_enter')}")
    return name


def _main_menu(
    console: Console, user: str, has_scenarios: bool, has_datasets: bool
) -> int | None:
    if has_scenarios:
        items = [
            _t("chat_with_prospere"),
            _t("scenarios"),
            _t("settings"),
            _t("exit"),
        ]
        descs = [
            _t("chat_desc"),
            _t("scenarios_desc"),
            _t("settings_desc"),
            _t("exit_desc"),
        ]
    elif has_datasets:
        items = [_t("new_scenario"), _t("settings"), _t("exit")]
        descs = [
            _t("new_scenario_desc"),
            _t("settings_desc"),
            _t("exit_desc"),
        ]
    else:
        items = [_t("import_data"), _t("settings"), _t("exit")]
        descs = [
            _t("import_data_desc"),
            _t("settings_desc"),
            _t("exit_desc"),
        ]
    return tui_choice(console, user, items, descs, back_label=_t("quit"))


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════


def _switch_user(console: Console, current_user: str) -> str | None:
    """Show a dedicated user-switch screen and return new user (or None)."""
    console.clear()
    users = _get_users()
    if not users:
        cli_header(console, _t("switch_user_title"))
        console.print(f"[meta]{_t('no_other_users')}[/meta]\n")
        input(f"  {_t('press_enter')}")
        return None

    choices = users + [_t("new_user_choice")]
    idx = tui_choice(console, _t("switch_user_title"), choices)
    if idx is None:
        return None
    if idx < len(users):
        if users[idx] != current_user:
            return users[idx]
        return None
    return _create_user(console)


def _delete_user(console: Console, user: str) -> bool:
    """Confirm and delete the user workspace. Returns True if deleted."""
    console.clear()
    cli_header(console, _t("delete_user_title"))
    console.print(f"[warning]{_t('delete_user_confirm', user)}[/warning]\n")
    confirm = input(f"  {_t('delete_user_prompt')} [y/N]: ").strip().lower()
    if confirm == "y":
        import shutil

        ws = WorkspaceManager(WorkspaceContext(user=user))
        shutil.rmtree(ws.user_root, ignore_errors=True)
        console.print(f"\n[success]{_t('user_deleted', user)}[/success]")
        input(f"  {_t('press_enter')}")
        return True
    return False


def _language_menu(console: Console, user: str) -> None:
    """Dedicated submenu for switching languages."""
    _lang_map = {"en": "English", "zh-Hant": "繁體中文", "zh-Hans": "简体中文"}
    choices = list(_lang_map.values())
    codes = list(_lang_map.keys())

    while True:
        console.clear()
        title = f"{user}  ›  {_t('settings')}  ›  {_t('language')}"
        idx = tui_choice(console, title, choices)

        if idx is None:
            return

        selected_code = codes[idx]
        _set_language(selected_code)
        settings_manager.language = selected_code
        return


def _settings_menu(console: Console, user: str) -> str | None:
    """Settings screen. Returns new user if switched, or 'DELETED' if deleted."""
    while True:
        console.clear()
        current_lang = get_language()
        lang_label = (
            _t(f"lang_{current_lang}")
            if f"lang_{current_lang}" in MENU_I18N["en"]
            else current_lang
        )

        items = [
            _t("switch_user"),
            f"{_t('language')}: {lang_label}",
            _t("settings_ai_config"),
            _t("import_data"),
            _t("delete_user_title"),
        ]
        descs = [
            _t("switch_user_desc"),
            _t("language_desc"),
            _t("settings_ai_config_desc"),
            _t("import_data_desc"),
            _t("delete_user_desc"),
        ]
        idx = tui_choice(
            console,
            f"{user}  ›  {_t('settings')}",
            items,
            descs,
        )
        if idx is None:
            return None
        if idx == 0:
            new_user = _switch_user(console, user)
            if new_user:
                settings_manager.last_user = new_user
                return new_user
        elif idx == 1:
            _language_menu(console, user)
        elif idx == 2:
            _setup_ai_config(console, force=True)
        elif idx == 3:
            _import_data_menu(console, user)
        elif idx == 4:
            if _delete_user(console, user):
                if settings_manager.last_user == user:
                    settings_manager.last_user = None
                return "DELETED"


def _run_scenario_loop(console: Console, user: str, scenarios: list[str]) -> str | None:
    """Main loop when scenarios exist."""
    while True:
        console.clear()
        idx = _main_menu(console, user, has_scenarios=True, has_datasets=True)
        if idx is None or idx == 3:
            return None
        if idx == 0:
            if len(scenarios) == 1:
                _launch_chat(user, scenarios[0])
            else:
                _launch_chat(user)
        elif idx == 1:
            _scenario_menu(console, user)
        elif idx == 2:
            new_user = _settings_menu(console, user)
            if new_user == "DELETED":
                return "DELETED"
            if new_user:
                return new_user
    return None


def _run_dataset_loop(console: Console, user: str) -> str | None:
    """Main loop when datasets exist but no scenarios."""
    while True:
        console.clear()
        idx = _main_menu(console, user, has_scenarios=False, has_datasets=True)
        if idx is None or idx == 2:
            return None
        if idx == 0:
            _launch_bootstrap(user)
        elif idx == 1:
            new_user = _settings_menu(console, user)
            if new_user == "DELETED":
                return "DELETED"
            if new_user:
                return new_user
    return None


def _run_no_data_loop(console: Console, user: str) -> str | None:
    """Main loop when no datasets exist."""
    while True:
        console.clear()
        idx = _main_menu(console, user, has_scenarios=False, has_datasets=False)
        if idx is None or idx == 2:
            return None
        if idx == 0:
            _import_data_menu(console, user)
        elif idx == 1:
            new_user = _settings_menu(console, user)
            if new_user == "DELETED":
                return "DELETED"
            if new_user:
                return new_user
    return None


def _setup_ai_config(console: Console, force: bool = False) -> None:
    if settings_manager.ai_provider and not force:
        return

    console.clear()
    cli_header(console, _t("setup_ai_title"))
    console.print(f"[meta]{_t('setup_ai_prompt')}[/meta]")

    choices = [
        _t("ai_provider_openai"),
        _t("ai_provider_deepseek"),
        _t("ai_provider_custom"),
        _t("ai_provider_skip"),
    ]
    idx = tui_choice(console, None, choices)

    if idx is None or idx == 3:
        settings_manager.ai_provider = "skipped"
        console.print(f"\n[warning]{_t('ai_skip_warning')}[/warning]")
        input(f"  {_t('press_enter')}")
        return

    if idx == 0:
        provider = "openai"
        base_url = "https://api.openai.com/v1"
        raw_model = input(f"  {_t('enter_model_name')} [gpt-5-mini]: ").strip()
        model = raw_model if raw_model else "gpt-5-mini"
        api_key = input(f"  {_t('enter_api_key')}: ").strip()
    elif idx == 1:
        provider = "deepseek"
        base_url = "https://api.deepseek.com"
        raw_model = input(f"  {_t('enter_model_name')} [deepseek-v4-flash]: ").strip()
        model = raw_model if raw_model else "deepseek-v4-flash"
        api_key = input(f"  {_t('enter_api_key')}: ").strip()
    else:
        provider = "custom"
        base_url = input(f"  {_t('enter_base_url')}: ").strip()
        model = input(f"  {_t('enter_model_name')}: ").strip()
        api_key = input(f"  {_t('enter_api_key')}: ").strip()

    settings_manager.ai_provider = provider
    settings_manager.ai_base_url = base_url
    settings_manager.ai_model = model
    settings_manager.ai_api_key = api_key

    console.print(f"\n[success]{_t('ai_setup_complete')}[/success]")
    input(f"  {_t('press_enter')}")


def run_menu() -> None:
    # Load saved language or detect
    saved_lang = settings_manager.language
    _set_language(saved_lang or _detect_lang())

    console = Console(theme=MENU_THEME, highlight=False)

    _setup_ai_config(console)

    user = _select_user(console)
    if user is None:
        console.clear()
        console.print(f"\n[meta]{_t('goodbye')}[/meta]\n")
        return

    while True:
        ws = WorkspaceManager(WorkspaceContext(user=user))
        repo = ScenarioRepository(ws)
        scenarios = repo.list_available_scenarios()

        if scenarios:
            res = _run_scenario_loop(console, user, scenarios)
        elif _has_datasets(user):
            res = _run_dataset_loop(console, user)
        else:
            res = _run_no_data_loop(console, user)

        if res == "DELETED":
            user = _select_user(console, force_select=True)
            if user is None:
                break
            continue

        if res:
            user = res
            continue
        break

    console.clear()
    console.print(f"\n[meta]{_t('goodbye')}[/meta]\n")
