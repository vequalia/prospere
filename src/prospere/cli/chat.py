"""Unified AI Chat — simulation Q&A + optimization capabilities via OptimChatEngine."""

import argparse
import logging
import os
import readline
import sys
from typing import Any, Final

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.theme import Theme

from prospere.cli.i18n import _set_language, _t, detect_lang, get_language
from prospere.cli.utils import Spinner, cli_header, tui_choice
from prospere.core.constants import UITheme
from prospere.core.models import WorkspaceContext
from prospere.core.workspace import WorkspaceManager
from prospere.optimization.chat import OptimChatEngine
from prospere.simulation.models import SimulationResult
from prospere.simulation.scenario import ScenarioRepository

_CHAT_THEME: Final = Theme(UITheme.THEME_DICT)
_PROMPT: Final = "\001\033[1;38;2;212;168;83m\002❯ \001\033[0m\002"
_HISTORY_FILE: Final = os.path.expanduser("~/.prospere_chat_history")

logger = logging.getLogger(__name__)


def _select_scenario(repo: ScenarioRepository, user: str) -> str:
    console = Console(theme=_CHAT_THEME, highlight=False)
    scenarios = repo.list_available_scenarios()
    if not scenarios:
        console.print(f"[error]{_t('chat_no_scenarios', user)}[/error]")
        console.print(f"[meta]{_t('chat_run_bootstrap_first', user)}[/meta]")
        return ""
    if len(scenarios) == 1:
        chosen = scenarios[0]
        console.print(f"[meta]{_t('chat_using_scenario', chosen)}[/meta]")
        return chosen
    idx = tui_choice(
        console,
        f"{user}  ›  {_t('chat_select_scenario_title')}",
        sorted(scenarios),
    )
    if idx is None:
        console.print(f"[meta]{_t('chat_no_scenario_selected')}[/meta]")
        return ""
    return sorted(scenarios)[idx]


def _print_banner(
    console: Console,
    engine: OptimChatEngine,
    sim_name: str,
    user: str,
    first_time: bool = False,
) -> None:
    from prospere.cli.utils import format_currency

    console.print()
    cli_header(console, user, _t("chat_brand"), sim_name)

    baseline_final = engine.baseline_result.percentile_50[-1]
    years = engine.scenario_meta["years"]
    cagr = _compute_cagr(engine.baseline_result, years)

    stats = Text.assemble(
        ("▎ ", "accent"),
        (f"{_t('chat_years')} ", "dim"),
        (f"{years}  ", ""),
        ("·  ", "dim"),
        (f"{_t('chat_p50_wealth')} ", "dim"),
        (f"{format_currency(baseline_final)}  ", ""),
        ("·  ", "dim"),
        (f"{_t('chat_cagr')} ", "dim"),
        (f"{cagr:.1f}%", ""),
    )
    console.print(stats)
    console.print()

    hint = f"[meta]{_t('chat_help_cmd')}[/meta]"
    if first_time:
        hint += f"    [dim]{_t('chat_first_time_hint')}[/dim]"
    console.print(hint)
    console.print()


def _compute_cagr(result: SimulationResult, years: int) -> float:
    initial = result.percentile_50[0]
    final = result.percentile_50[-1]
    if initial <= 0 or years <= 0:
        return 0.0
    return float(((final / initial) ** (1 / years) - 1) * 100)


def _init_engine(
    console: Console, ws_manager: WorkspaceManager, scenario: str, lang: dict
) -> OptimChatEngine | None:
    """Initializes the OptimChatEngine with a spinner."""
    try:
        with Spinner(_t("chat_loading")):
            engine = OptimChatEngine(
                sim_scenario=scenario, ws_manager=ws_manager, lang_dict=lang
            )
        if not engine.is_available():
            console.print(f"[error]{_t('chat_no_api')}[/error]")
            return None
        return engine
    except Exception as e:
        console.print(f"[error]{_t('chat_engine_init_failed', e)}[/error]")
        return None


def _handle_chat_command(
    user_input: str,
    console: Console,
    engine: OptimChatEngine,
    user: str,
    scenario: str,
) -> tuple[bool, list[dict[str, Any]] | None]:
    """Handles special chat commands. Returns (should_continue, new_messages)."""
    cmd = user_input.lower()
    if cmd in ("exit", "quit", "/exit", "/quit", "退出"):
        return False, None
    if cmd in ("clear", "/clear", "清除"):
        console.clear()
        _print_banner(console, engine, scenario, user)
        return True, [engine._build_system_message()]
    if cmd in ("/help", "help"):
        console.print(Markdown(_t("chat_help_text")))
        return True, []
    if cmd in ("/result", "result"):
        engine.display_simulation_report_rich(user)
        return True, []
    if cmd in ("/export", "/report", "export", "report"):
        path = engine.export_html_chat()
        if path:
            import webbrowser

            url = f"file://{path}"
            console.print(_t("sim_html_report_exported_chat", url))
            webbrowser.open(url)
        return True, []
    return True, None


def _handle_chat_cycle(
    console: Console,
    engine: OptimChatEngine,
    user: str,
    scenario: str,
    messages: list[dict[str, Any]],
    chat_history: list[dict[str, str]],
    lang_info: dict,
) -> tuple[bool, list[dict[str, Any]]]:
    """Processes a single chat cycle. Returns (should_continue, updated_messages)."""
    try:
        console.print()
        user_input = input(_PROMPT).strip()
        if not user_input:
            return True, messages

        sys.stdout.write("\033[A\r\033[K")
        console.print(Text("▎ ", style=f"dim {UITheme.META}") + Text(user_input))

        cont, new_msgs = _handle_chat_command(
            user_input, console, engine, user, scenario
        )
        if not cont:
            return False, messages
        if new_msgs is not None and len(new_msgs) > 0:
            return True, new_msgs
        if new_msgs is not None:
            return True, messages

        engine.process_turn(console, messages, chat_history, lang_info, user_input)
        try:
            readline.write_history_file(_HISTORY_FILE)
        except Exception:
            logger.debug("Could not write chat history", exc_info=True)
        return True, messages

    except (KeyboardInterrupt, EOFError):
        console.print()
        return False, messages
    except Exception as e:
        console.print(f"\n[error]Error: {e}[/error]")
        return True, messages


def run_chat_cli() -> None:
    parser = argparse.ArgumentParser(description="Prospere AI Chat")
    parser.add_argument("--user", type=str, default="default_user")
    parser.add_argument("--scenario", type=str, default="")
    parser.add_argument(
        "--lang",
        type=str,
        choices=["en", "zh", "zh-Hant", "zh-Hans"],
        default=detect_lang(),
        help="UI language",
    )
    args = parser.parse_args()

    _set_language(args.lang)
    lang_info = {"_code": get_language()}
    console = Console(theme=_CHAT_THEME, highlight=False)

    ws_manager = WorkspaceManager(WorkspaceContext(user=args.user))
    repo = ScenarioRepository(ws_manager=ws_manager)
    scenario = args.scenario or _select_scenario(repo, args.user)
    if not scenario:
        if not args.scenario:
            input("  " + _t("press_enter"))
        return

    engine = _init_engine(console, ws_manager, scenario, lang_info)
    if not engine:
        input("  " + _t("press_enter"))
        return

    messages: list[dict[str, Any]] = [engine._build_system_message()]
    chat_history: list[dict[str, str]] = []

    try:
        if os.path.exists(_HISTORY_FILE):
            readline.read_history_file(_HISTORY_FILE)
    except Exception:
        logger.debug("Could not read chat history", exc_info=True)

    console.clear()
    _print_banner(console, engine, scenario, args.user, first_time=True)

    cont = True
    while cont:
        cont, messages = _handle_chat_cycle(
            console, engine, args.user, scenario, messages, chat_history, lang_info
        )

    console.print(f"\n[meta]{_t('chat_exit')}[/meta]")


if __name__ == "__main__":
    run_chat_cli()
