import argparse
import logging
import os
from collections.abc import Callable

from rich.console import Console
from rich.theme import Theme

from prospere.ai.assistant import AIAssistant
from prospere.cli.bootstrap_pages import (
    _page_accounts,
    _page_ai_classify,
    _page_audit,
    _page_categories,
    _page_growth,
    _page_market,
    _page_params,
    _page_scope,
    _page_summary,
    _page_tax,
    set_tui_auto,
)
from prospere.cli.i18n import _set_language, _t
from prospere.cli.utils import cli_header, prompt_int, tui_choice
from prospere.core.constants import SimulationDefaults, UITheme
from prospere.core.models import WorkspaceContext
from prospere.core.workspace import WorkspaceManager
from prospere.simulation.scenario_builder import ScenarioBuilder

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
BOOTSTRAP_THEME = Theme(UITheme.THEME_DICT)

# ═══════════════════════════════════════════════════════════════════════
# Page: Snapshot Selection
# ═══════════════════════════════════════════════════════════════════════


def _page_snapshot(console: Console, ws: WorkspaceManager, user: str) -> str | None:
    datasets_root = ws.get_datasets_root()
    snaps = sorted(os.listdir(datasets_root))
    while True:
        console.clear()
        cli_header(console, user, _t("bootstrap"))
        idx = tui_choice(console, None, snaps, back_label=_t("back"))
        if idx is None:
            return None
        return snaps[idx]


# ═══════════════════════════════════════════════════════════════════════
# Step Navigator
# ═══════════════════════════════════════════════════════════════════════


def _step_navigator(
    console: Console,
    builder: ScenarioBuilder,
    ai: AIAssistant | None,
    is_auto: bool,
    ws: WorkspaceManager,
    user: str,
) -> None:
    steps: list[tuple[str, Callable[[], str]]] = []

    steps.append(
        (
            _t("step_scope"),
            lambda: _page_scope(console, builder, is_auto, user),
        )
    )
    steps.append(
        (
            _t("step_audit"),
            lambda: _page_audit(console, builder, is_auto, user),
        )
    )
    steps.append(
        (
            _t("step_params"),
            lambda: _page_params(console, builder, is_auto, user),
        )
    )
    if ai and ai.is_available():
        steps.append(
            (
                _t("step_ai_classify"),
                lambda: _page_ai_classify(console, builder, ai, user),
            )
        )
    steps.append(
        (
            _t("step_accounts"),
            lambda: _page_accounts(console, builder, is_auto, user),
        )
    )
    steps.append(
        (
            _t("step_categories"),
            lambda: _page_categories(console, builder, is_auto, user),
        )
    )
    steps.append(
        (
            _t("step_growth"),
            lambda: _page_growth(console, builder, ai, is_auto, ws, user),
        )
    )
    steps.append(
        (
            _t("step_market"),
            lambda: _page_market(console, builder, user, is_auto),
        )
    )
    steps.append(
        (
            _t("step_tax"),
            lambda: _page_tax(console, builder, ai, ws, user, is_auto),
        )
    )
    steps.append(
        (
            _t("step_summary"),
            lambda: _page_summary(console, builder, ws, user, is_auto),
        )
    )

    step_idx = 0
    while 0 <= step_idx < len(steps):
        label, page_fn = steps[step_idx]
        result = page_fn()
        if result == "next":
            step_idx += 1
        elif result == "back":
            step_idx -= 1
            if step_idx < 0:
                return
        elif result == "quit":
            return


# ═══════════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════════


def run_bootstrap_cli() -> None:
    parser = argparse.ArgumentParser(description="Prospere Scenario Bootstrap")
    parser.add_argument("--user", type=str, default="default_user")
    parser.add_argument("--lang", type=str, default="en")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ai-assist", action="store_true")
    group.add_argument("--ai-auto", action="store_true")
    group.add_argument("--manual", action="store_true")
    args = parser.parse_args()

    _set_language(args.lang)
    set_tui_auto(False)

    cli_mode_explicit = args.ai_assist or args.ai_auto or args.manual
    is_auto, use_ai = args.ai_auto, not args.manual
    if is_auto:
        set_tui_auto(True)
    ws = WorkspaceManager(WorkspaceContext(user=args.user))

    datasets_root = ws.get_datasets_root()
    if not os.path.exists(datasets_root) or not os.listdir(datasets_root):
        print(_t("no_datasets", args.user))
        return

    console = Console(theme=BOOTSTRAP_THEME)

    snap = _page_snapshot(console, ws, args.user)
    if snap is None:
        return

    ws = WorkspaceManager(WorkspaceContext(user=args.user, snapshot=snap))
    builder = ScenarioBuilder(
        ws.get_dataset_path("processed_transactions.xlsx"),
        ws.get_dataset_path("processed_balances.json"),
    )
    builder.set_snapshot_name(snap)

    if not cli_mode_explicit:
        console.clear()
        cli_header(console, args.user, _t("bootstrap"), _t("setup_mode"))
        mode_idx = tui_choice(
            console,
            _t("choose_setup_mode"),
            [
                _t("guided_setup"),
                _t("quick_setup"),
            ],
            [
                _t("guided_setup_desc"),
                _t("quick_setup_desc"),
            ],
        )
        if mode_idx is None:
            return
        if mode_idx == 1:
            set_tui_auto(True)
            is_auto = True
            use_ai = True
            years = prompt_int(_t("param_years"), SimulationDefaults.YEARS, 1, 100)
            builder.set_scenario_field("years", years)
        else:
            is_auto = False
            use_ai = True

    ai = AIAssistant() if use_ai else None

    try:
        _step_navigator(console, builder, ai, is_auto, ws, args.user)
    except KeyboardInterrupt:
        print(_t("operation_interrupted"))
    except Exception as err:
        logger.exception("Bootstrap failed")
        print(_t("critical_error", err))


if __name__ == "__main__":
    run_bootstrap_cli()
