import itertools
import os
import sys
import threading
import time
import typing
from typing import Any

from rich.console import Console
from rich.text import Text

from prospere.cli.i18n import _t as i18n_t
from prospere.core.constants import CLIConfig

# Platform-specific getch
try:
    import termios
    import tty

    def getch() -> str:
        """Reads a single character from stdin without requiring Enter (Unix)."""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
            # Handle escape sequences (arrows)
            if ch == "\033":
                ch += sys.stdin.read(2)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

except ImportError:
    # Fallback for Windows or non-TTY environments
    try:
        import msvcrt

        def getch() -> str:
            """Reads a single character from stdin without requiring Enter (Windows)."""
            # Use typing.Any to avoid Mypy issues with msvcrt
            m: Any = msvcrt
            return str(m.getch().decode("utf-8"))

    except ImportError:

        def getch() -> str:
            """Fallback read for restricted environments."""
            return sys.stdin.read(1)


class CLIStyles:
    """Centralized terminal styling constants."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    YELLOW_BOLD = "\033[93;1m"
    GRAY = "\033[90m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"

    # Symbols
    POINTER = "▶"
    CHECKED = "[x]"
    UNCHECKED = "[ ]"
    SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def format_currency(
    value: float | int,
    currency_symbol: str = "€",
    use_suffix: bool = True,
    precision: int = 0,
) -> str:
    """
    Unified currency formatter with support for K/M suffixes.

    Args:
        value: Numeric value to format.
        currency_symbol: Symbol to prepend/append.
        use_suffix: Whether to use K/M suffixes for large numbers.
        precision: Decimal precision for non-suffixed numbers.
    """
    abs_val = abs(value)
    sign = "-" if value < 0 else ""

    if use_suffix:
        if abs_val >= CLIConfig.MILLION:
            return f"{sign}{currency_symbol}{abs_val / CLIConfig.MILLION:.2f}M"
        if abs_val >= CLIConfig.THOUSAND:
            # For thousands, we still might want commas if they are below 100K
            if abs_val < 100_000:
                return f"{sign}{currency_symbol}{abs_val:,.0f}"
            return f"{sign}{currency_symbol}{abs_val / CLIConfig.THOUSAND:.1f}K"

    # Default formatting
    if isinstance(value, float) and precision > 0:
        return f"{sign}{currency_symbol}{abs_val:,.{precision}f}"
    return f"{sign}{currency_symbol}{abs_val:,.0f}"


class Spinner:
    """A simple terminal spinner for long-running operations."""

    def __init__(self, message: str | None = None):
        if message is None:
            message = i18n_t("ui_spinner_processing")
        self.message = message
        self.spinner_cycle = itertools.cycle(CLIStyles.SPINNER_CHARS)
        self.running = False
        self.thread: threading.Thread | None = None

    def _spin(self) -> None:
        while self.running:
            sys.stdout.write(f"\r  {next(self.spinner_cycle)} {self.message}")
            sys.stdout.flush()
            time.sleep(0.1)
        # Clear the line on exit
        sys.stdout.write("\r" + " " * (len(self.message) + 10) + "\r")
        sys.stdout.flush()

    def __enter__(self) -> "Spinner":
        self.running = True
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.running = False
        if self.thread:
            self.thread.join()


# Interactive Prompt Helpers


def prompt(
    label: str,
    default: str = "",
    validator: typing.Callable[[str], None] | None = None,
) -> str:
    label_text = f"  {label}"
    if default:
        label_text += f" [{default}]"
    try:
        user_input = input(label_text + ": ").strip()
    except EOFError:
        return default

    if not user_input:
        user_input = default

    if validator and user_input:
        try:
            validator(user_input)
        except ValueError as err:
            print(f"  {CLIStyles.RED}✗ {err}{CLIStyles.RESET}")
            return prompt(label, default, validator)
    return user_input


def prompt_int(
    label: str, default: int, min_value: int = 1, max_value: int = 1_000_000_000
) -> int:
    def _validate(v: str) -> None:
        val = int(v)
        if val < min_value or val > max_value:
            raise ValueError(i18n_t("ui_range_validation", min_value, max_value))

    return int(prompt(label, str(default), _validate))


def prompt_float(
    label: str, default: float, min_value: float = -1e12, max_value: float = 1e12
) -> float:
    def _validate(v: str) -> None:
        val = float(v)
        if val < min_value or val > max_value:
            raise ValueError(i18n_t("ui_range_validation", min_value, max_value))

    return float(prompt(label, str(default), _validate))


def prompt_bool(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = prompt(f"{label} ({hint})", "y" if default else "n")
    return raw.lower().startswith("y")


def prompt_choice(label: str, choices: list[str], default: str) -> str:
    print(f"  {label}:")
    for i, choice in enumerate(choices, 1):
        marker = "●" if choice == default else "○"
        print(f"    {i}. {marker} {choice}")
    raw = prompt("  " + i18n_t("ui_prompt_enter_number"), default)
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(choices):
            return choices[idx]
    return raw if raw in choices else default


def prompt_csv(label: str, detected: list[str], defaults: list[str]) -> list[str]:
    print(f"  {label}\n    {i18n_t('ui_prompt_csv_available', ', '.join(detected))}")
    raw = prompt(f"  {i18n_t('ui_prompt_csv_enter')}", ", ".join(defaults))
    return [i.strip() for i in raw.split(",") if i.strip()]


# TUI Checklists


def _render_checklist(
    console: Console,
    title: str,
    items: list[str],
    selected: dict[str, bool],
    cursor: int,
    num_rows: int,
    num_cols: int,
    col_width: int,
    move_up_count: int,
    is_first: bool,
    back_key: str | None = None,
) -> None:
    if not is_first:
        sys.stdout.write(f"\033[{move_up_count}A\r\033[J")

    console.print(f"  ✨ [bold]{title}[/bold]")
    for r in range(num_rows):
        row = Text("    ")
        for c in range(num_cols):
            idx = r + c * num_rows
            if idx < len(items):
                item = items[idx]
                pointer = "▶" if idx == cursor else " "
                check = "✓" if selected[item] else "○"
                display_width = col_width - 7
                display_name = item[:display_width]
                padded = f"{display_name:<{display_width}}"
                style = (
                    "accent"
                    if idx == cursor
                    else ("success" if selected[item] else "meta")
                )
                if c > 0:
                    row.append("  ")
                row.append(f"{pointer}{check} ", style="meta")
                row.append(padded, style=style)
        console.print(row)

    hint = i18n_t("ui_checklist_hint")
    if back_key:
        hint += "  ·  " + back_key + " " + i18n_t("back")
    console.print(f" [meta]{hint}[/meta]")
    sys.stdout.flush()


def _handle_checklist_keys(
    key: str, cursor: int, num_rows: int, num_cols: int, items: list[str]
) -> int:
    if key in ("w", "W", "\033[A"):
        if cursor % num_rows > 0:
            return cursor - 1
    elif key in ("s", "S", "\033[B"):
        if cursor % num_rows < num_rows - 1 and cursor + 1 < len(items):
            return cursor + 1
    elif key in ("a", "A", "\033[D"):
        if cursor >= num_rows:
            return cursor - num_rows
    elif key in ("d", "D", "\033[C"):
        if cursor + num_rows < len(items):
            return cursor + num_rows
    return cursor


def interactive_checklist(
    console: Console,
    title: str,
    items: list[str],
    back_key: str | None = None,
) -> list[str] | None:
    """A multi-column interactive checklist.

    Returns the list of deselected items, or ``None`` if *back_key* was pressed.
    """
    if not items:
        return []

    selected = {item: True for item in items}
    cursor = 0

    try:
        term_width = os.get_terminal_size().columns - 5
    except (OSError, AttributeError):
        term_width = CLIConfig.TABLE_WIDTH - 5

    num_cols = max(1, term_width // 25)
    num_rows = (len(items) + num_cols - 1) // num_cols
    move_up_count = num_rows + 2
    is_first = True

    print()
    while True:
        _render_checklist(
            console,
            title,
            items,
            selected,
            cursor,
            num_rows,
            num_cols,
            25,
            move_up_count,
            is_first,
            back_key,
        )
        is_first = False
        key = getch()

        if key in ("f", "F"):
            sys.stdout.write(f"\033[{move_up_count}A\r\033[J")
            sys.stdout.flush()
            break
        elif back_key and key.lower() == back_key.lower():
            sys.stdout.write(f"\033[{move_up_count}A\r\033[J")
            sys.stdout.flush()
            return None
        elif key in ("\r", "\n", " "):
            selected[items[cursor]] = not selected[items[cursor]]
        else:
            cursor = _handle_checklist_keys(key, cursor, num_rows, num_cols, items)

    return [item for item in items if not selected[item]]


# Hierarchical Tree Checklist


def _render_hierarchical(
    console: Console,
    title: str,
    visible_items: list[dict],
    selected: dict[str, bool],
    expanded: dict[str, bool],
    cursor: int,
    viewport_start: int,
    move_up_count: int,
    is_first: bool,
    back_key: str | None = None,
) -> None:
    max_rows = 15
    if not is_first:
        sys.stdout.write(f"\033[{move_up_count}A\r\033[J")

    console.print(f"  ✨ [bold]{title}[/bold]")

    visible_slice = visible_items[viewport_start : viewport_start + max_rows]

    for i, item in enumerate(visible_slice):
        idx = viewport_start + i
        pointer = "▶" if idx == cursor else " "
        is_sub = item["parent"] is not None
        indent = "      " if is_sub else "    "

        item_id = str(item["id"])
        is_sel = selected.get(item_id, False)
        check = "✓" if is_sel else "○"

        prefix = ""
        if not is_sub:
            exp_sym = "▼" if expanded.get(item_id, False) else "▶"
            prefix = f"{exp_sym} "

        style = "accent" if idx == cursor else ("success" if is_sel else "meta")

        line = Text(indent)
        line.append(f"{pointer}{check} {prefix}", style="meta")
        line.append(item["name"], style=style)
        console.print(line)

    for _ in range(max_rows - len(visible_slice)):
        console.print()

    hint = i18n_t("ui_tree_hint")
    if back_key:
        hint += "  ·  " + back_key + " " + i18n_t("back")
    console.print(f" [meta]{hint}[/meta]")
    sys.stdout.flush()


def _get_visible_tree_items(
    groups: dict[str, list[str]], expanded: dict[str, bool]
) -> list[dict]:
    """Calculates visible items based on expansion state."""
    visible_items = []
    for cat in sorted(groups.keys()):
        visible_items.append({"id": cat, "name": cat, "parent": None})
        if expanded.get(cat, False):
            for sub in sorted(groups[cat]):
                sub_id = f"{cat} > {sub}"
                visible_items.append({"id": sub_id, "name": sub, "parent": cat})
    return visible_items


def _handle_tree_keys(
    key: str,
    cur_item: dict,
    expanded: dict[str, bool],
    selected: dict[str, bool],
    groups: dict[str, list[str]],
) -> None:
    """Handles interaction keys for the hierarchical checklist."""
    cur_id = str(cur_item["id"])
    if key in ("d", "D", "\033[C"):
        if cur_item["parent"] is None:
            expanded[cur_id] = True
    elif key in ("a", "A", "\033[D"):
        if cur_item["parent"] is None:
            expanded[cur_id] = False
    elif key in ("\r", "\n", " "):
        new_state = not selected.get(cur_id, False)
        selected[cur_id] = new_state
        if cur_item["parent"] is None:
            for sub in groups[cur_id]:
                selected[f"{cur_id} > {sub}"] = new_state


def _init_hierarchical_state(
    groups: dict[str, list[str]],
    default_val: bool,
    initial_selected: dict[str, bool] | None,
) -> tuple[dict[str, bool], dict[str, bool]]:
    expanded = {cat: False for cat in groups}
    selected: dict[str, bool] = {}
    for cat, subs in groups.items():
        selected[cat] = (
            initial_selected.get(cat, default_val) if initial_selected else default_val
        )
        for sub in subs:
            sub_key = f"{cat} > {sub}"
            selected[sub_key] = (
                initial_selected.get(sub_key, default_val)
                if initial_selected
                else default_val
            )
    return expanded, selected


def hierarchical_checklist(
    console: Console,
    title: str,
    groups: dict[str, list[str]],
    default_val: bool = False,
    initial_selected: dict[str, bool] | None = None,
    back_key: str | None = None,
) -> list[str] | None:
    """Interactive tree-view checklist for Categories and Sub-categories."""
    expanded, selected = _init_hierarchical_state(groups, default_val, initial_selected)
    cursor, viewport_start, is_first = 0, 0, True
    max_rows = 15

    while True:
        visible_items = _get_visible_tree_items(groups, expanded)
        cursor = max(0, min(cursor, len(visible_items) - 1))

        if cursor < viewport_start:
            viewport_start = cursor
        elif cursor >= viewport_start + max_rows:
            viewport_start = cursor - max_rows + 1

        move_up_count = max_rows + 2
        _render_hierarchical(
            console,
            title,
            visible_items,
            selected,
            expanded,
            cursor,
            viewport_start,
            move_up_count,
            is_first,
            back_key,
        )
        is_first = False

        key = getch()
        if key in ("f", "F"):
            sys.stdout.write(f"\033[{move_up_count}A\r\033[J")
            sys.stdout.flush()
            break
        if back_key and key.lower() == back_key.lower():
            sys.stdout.write(f"\033[{move_up_count}A\r\033[J")
            sys.stdout.flush()
            return None
        if key in ("w", "W", "\033[A"):
            cursor -= 1
        elif key in ("s", "S", "\033[B"):
            cursor += 1
        else:
            _handle_tree_keys(key, visible_items[cursor], expanded, selected, groups)

    return [k for k, v in selected.items() if v]


# ── TUI Arrow-Key Selector ────────────────────────────────────────────


def cli_header(console: Console, *levels: str) -> None:
    """Print a hierarchical CLI header with breadcrumbs.

    L1 ``✦ Prospere`` is always rendered in accent-bold.
    Additional *levels* are joined with `` › `` in dim style.
    """
    _level_sep = "  ›  "
    parts: list[tuple[str, str]] = [("✦ Prospere", "accent bold")]
    if levels:
        trail = _level_sep.join(levels)
        parts.append((_level_sep + trail, "dim"))
    text = Text()
    for content, style in parts:
        text.append(content, style=style)
    console.print(text)
    console.print(Text("━" * min(console.width, 50), style="accent"))
    console.print()


def _tui_header(console: Console, title: str | None) -> None:
    """Print a minimal TUI header delegating to the hierarchy system.

    When *title* is ``None`` the header is suppressed entirely, allowing
    the caller to have already rendered a hierarchy header.
    """
    if title is None:
        return
    if title:
        cli_header(console, title)
    else:
        cli_header(console)


def _get_choice_hint(
    action_key: str | None,
    action_label: str,
    delete_key: str | None,
    delete_label: str,
    back_label: str,
) -> str:
    hint = i18n_t("ui_choice_hint")
    if action_key:
        hint += i18n_t("ui_choice_action_hint", action_key, action_label)
    if delete_key:
        hint += i18n_t("ui_choice_action_hint", delete_key, delete_label)
    hint += "  ·  q " + back_label
    return hint


def _render_choice_cycle(
    console: Console,
    title: str | None,
    visible: list[str],
    view_start: int,
    cursor: int,
    descriptions: list[str] | None,
    slot_count: int,
    hint: str,
) -> None:
    _tui_header(console, title)
    for i, item in enumerate(visible):
        global_idx = view_start + i
        pointer = "▶ " if global_idx == cursor else "  "
        style = "accent" if global_idx == cursor else "meta"
        line = f"{pointer}[{style}]{item}[/{style}]"
        if descriptions and global_idx < len(descriptions):
            line += f"  — [dim]{descriptions[global_idx]}[/dim]"
        console.print(line)

    for _ in range(slot_count - len(visible)):
        console.print()
    console.print(f"\n [meta]{hint}[/meta]")
    sys.stdout.flush()


def _handle_choice_cycle(
    key: str,
    cursor: int,
    item_count: int,
    action_key: str | None,
    delete_key: str | None,
    cursor_ref: list[int] | None,
) -> tuple[bool, int, int | None]:
    """Handles a single key press. Returns (should_cont, cursor, res_code)."""
    if key in ("\033[A", "w", "W") and cursor > 0:
        return True, cursor - 1, None
    if key in ("\033[B", "s", "S") and cursor < item_count - 1:
        return True, cursor + 1, None
    if key in ("\r", "\n", " "):
        return False, cursor, cursor
    if action_key and key.lower() == action_key.lower():
        if cursor_ref is not None:
            cursor_ref[0] = cursor
        return False, cursor, -1
    if delete_key and key.lower() == delete_key.lower():
        if cursor_ref is not None:
            cursor_ref[0] = cursor
        return False, cursor, -2
    if key in ("q", "Q", "\033"):
        return False, cursor, None
    return True, cursor, None


def tui_choice(
    console: Console,
    title: str | None,
    items: list[str],
    descriptions: list[str] | None = None,
    action_key: str | None = None,
    action_label: str = "",
    delete_key: str | None = None,
    delete_label: str = "",
    back_label: str = "back",
    cursor_ref: list[int] | None = None,
) -> int | None:
    """Arrow-key selector with viewport scrolling."""
    if not items:
        return None

    reserved = (3 if title is not None else 0) + 2
    max_v = max(1, os.get_terminal_size().lines - reserved)
    cursor, v_start = 0, 0
    slot_count = min(len(items), max_v)
    total_lines = reserved + slot_count
    hint = _get_choice_hint(
        action_key, action_label, delete_key, delete_label, back_label
    )

    first_render = True
    while True:
        if cursor < v_start:
            v_start = cursor
        elif cursor >= v_start + max_v:
            v_start = cursor - max_v + 1
        visible = items[v_start : v_start + max_v]

        if not first_render:
            sys.stdout.write(f"\033[{total_lines}A\r\033[J")
        first_render = False

        _render_choice_cycle(
            console, title, visible, v_start, cursor, descriptions, slot_count, hint
        )

        cont, cursor, res = _handle_choice_cycle(
            getch(), cursor, len(items), action_key, delete_key, cursor_ref
        )
        if not cont:
            return res
