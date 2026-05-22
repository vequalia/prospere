import sys
from typing import Final

from prospere.cli.menu import run_menu

_VERSION: Final = "0.1.0"

_HELP: Final = """\
Prospere — Professional Financial Forecasting Engine

Usage:
  prospere              Launch interactive menu

Options:
  -h, --help            Show this help message and exit
  --version             Show version and exit
"""


def main() -> None:
    """Prospere CLI — interactive financial forecasting engine."""
    if "--version" in sys.argv:
        print(f"Prospere v{_VERSION}")
        return
    if "-h" in sys.argv or "--help" in sys.argv:
        print(_HELP)
        return

    # Check for updates and perform forced automatic upgrade if necessary
    try:
        from prospere.cli.updater import check_and_perform_update

        check_and_perform_update(_VERSION)
    except Exception:  # nosec B110 # noqa: S110 - Prevent updater issues from blocking CLI core functionality.
        # Prevent any updater failure from breaking the core CLI
        pass

    run_menu()


if __name__ == "__main__":
    main()
