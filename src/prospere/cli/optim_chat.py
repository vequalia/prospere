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

from prospere.cli.i18n import _set_language, _t, detect_lang
from prospere.cli.utils import Spinner, cli_header, format_currency
from prospere.core.constants import UITheme
from prospere.core.models import WorkspaceContext
from prospere.core.workspace import WorkspaceManager
from prospere.optimization.chat import OptimChatEngine

_HISTORY_FILE: Final = os.path.expanduser("~/.prospere_optim_chat_history")
_CHAT_THEME: Final = Theme(UITheme.THEME_DICT)

_PROMPT: Final = "\001\033[1;38;2;212;168;83m\002❯ \001\033[0m\002"
_USER_BORDER_STYLE: Final = f"dim {UITheme.META}"
_USER_BORDER_CHAR: Final = "▎ "

logger = logging.getLogger(__name__)


def _print_banner(
    console: Console,
    engine: OptimChatEngine,
    user: str,
    first_time: bool = False,
) -> None:
    console.print()
    cli_header(console, user, _t("optim_brand"))

    baseline_final = engine.baseline_result.percentile_50[-1]
    years = engine.scenario_meta["years"]
    b_initial = engine.baseline_result.percentile_50[0]
    multiplier = baseline_final / b_initial if b_initial > 0 else 0
    cagr = (multiplier ** (1 / years) - 1) * 100 if years > 0 and multiplier > 0 else 0

    stats = Text.assemble(
        ("▎ ", "accent"),
        (f"{_t('optim_scenario')} ", "dim"),
        (f"{engine.scenario_id}  ", ""),
        ("·  ", "dim"),
        (f"{_t('optim_years')} ", "dim"),
        (f"{years}  ", ""),
        ("·  ", "dim"),
        (f"{_t('optim_p50_wealth')} ", "dim"),
        (f"{format_currency(baseline_final)}  ", ""),
        ("·  ", "dim"),
        (f"{_t('optim_cagr')} ", "dim"),
        (f"{cagr:.1f}%", ""),
    )
    console.print(stats)
    console.print()

    hint = f"[meta]{_t('optim_help')}[/meta]"
    if first_time:
        hint += f"    [dim]{_t('optim_first_time_hint')}[/dim]"
    console.print(hint)
    console.print()


def _load_history() -> None:
    try:
        if os.path.exists(_HISTORY_FILE):
            readline.read_history_file(_HISTORY_FILE)
    except Exception:
        logger.debug("Could not read optim chat history", exc_info=True)


def _save_history() -> None:
    try:
        readline.write_history_file(_HISTORY_FILE)
    except Exception:
        logger.debug("Could not write optim chat history", exc_info=True)


def _print_user_input(console: Console, user_input: str) -> None:
    sys.stdout.write("\033[A\r\033[K")
    console.print(Text(_USER_BORDER_CHAR, style=_USER_BORDER_STYLE) + Text(user_input))


def _init_engine(
    args: Any, ws_manager: WorkspaceManager, console: Console
) -> OptimChatEngine:
    try:
        with Spinner(_t("optim_loading")):
            engine = OptimChatEngine(args.scenario, ws_manager)
        if not engine.is_available():
            console.print(f"[error]{_t('optim_no_api')}[/error]")
            sys.exit(1)
        return engine
    except FileNotFoundError as e:
        console.print(f"[error]{e}[/error]")
        sys.exit(1)


def _handle_optim_chat_command(
    user_input: str, console: Console, engine: OptimChatEngine, user: str
) -> tuple[bool, list[dict[str, Any]] | None]:
    cmd = user_input.lower()
    if cmd in ("exit", "quit", "/exit", "/quit", "退出"):
        return False, None
    if cmd in ("clear", "/clear", "清除"):
        console.clear()
        _print_banner(console, engine, user)
        return True, [engine._build_system_message()]
    if cmd in ("/help", "help"):
        console.print(Markdown(_t("optim_help_text")))
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


def _handle_optim_chat_cycle(
    console: Console,
    engine: OptimChatEngine,
    user: str,
    messages: list[dict[str, Any]],
    chat_history: list[dict[str, str]],
) -> tuple[bool, list[dict[str, Any]]]:
    try:
        console.print()
        user_input = input(_PROMPT).strip()
        if not user_input:
            return True, messages
        _print_user_input(console, user_input)

        cont, new_msgs = _handle_optim_chat_command(user_input, console, engine, user)
        if not cont:
            return False, messages
        if new_msgs:
            return True, new_msgs
        if new_msgs is not None:
            return True, messages

        engine.process_turn(console, messages, chat_history, {}, user_input)
        _save_history()
        return True, messages
    except (KeyboardInterrupt, EOFError):
        console.print()
        return False, messages
    except Exception as e:
        console.print(f"\n[error]Error: {e}[/error]")
        return True, messages


def run_optim_chat_cli() -> None:
    parser = argparse.ArgumentParser(description="Prospere Optim Chat")
    parser.add_argument("--user", type=str, default="default_user")
    parser.add_argument("--scenario", type=str, required=True)
    parser.add_argument(
        "--lang",
        type=str,
        choices=["en", "zh-Hant", "zh-Hans"],
        default=detect_lang(),
        help="UI language",
    )
    args = parser.parse_args()

    _set_language(args.lang)
    console = Console(theme=_CHAT_THEME, highlight=False)
    ws_manager = WorkspaceManager(WorkspaceContext(user=args.user))
    engine = _init_engine(args, ws_manager, console)

    messages: list[dict[str, Any]] = [engine._build_system_message()]
    chat_history: list[dict[str, str]] = []

    _load_history()
    _print_banner(console, engine, args.user, first_time=True)

    cont = True
    while cont:
        cont, messages = _handle_optim_chat_cycle(
            console, engine, args.user, messages, chat_history
        )

    console.print(f"\n[meta]{_t('optim_exit')}[/meta]")


if __name__ == "__main__":
    run_optim_chat_cli()
