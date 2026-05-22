import os
import re
import subprocess  # nosec B404
import sys
import time
import tomllib  # Built-in in Python 3.11+
import urllib.error
import urllib.request
from typing import Final

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from prospere.cli.i18n import get_language

# Dynamic Translations
LOCALIZED_TEXTS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "checking": "Checking for updates...",
        "available": "Prospere Update Available!",
        "new_version_detected": "A new version of Prospere has been detected.",
        "current_version": "Current Version:",
        "latest_version": "Latest Version:",
        "whats_new": "What's New:",
        "upgrading": "Upgrading Prospere automatically. Please wait...",
        "downloading": "Downloading and installing latest version...",
        "success": "Update successful! Restarting Prospere...",
        "failed": "Update failed!",
        "unexpected_error": "An unexpected error occurred during update:",
        "continuing": "Continuing with current version...",
        "more": "... (and more)",
    },
    "zh-Hant": {
        "checking": "正在檢查更新...",
        "available": "發現 Prospere 新版本！",
        "new_version_detected": "檢測到 Prospere 有可用的升級版本。",
        "current_version": "當前版本：",
        "latest_version": "最新版本：",
        "whats_new": "更新日誌：",
        "upgrading": "正在自動升級 Prospere，請稍候...",
        "downloading": "正在下載並安裝最新版本...",
        "success": "升級成功！正在重啟 Prospere...",
        "failed": "升級失敗！",
        "unexpected_error": "升級過程中發生未預期的錯誤：",
        "continuing": "將繼續使用當前版本運行...",
        "more": "... （以及更多）",
    },
    "zh-Hans": {
        "checking": "正在检查更新...",
        "available": "发现 Prospere 新版本！",
        "new_version_detected": "检测到 Prospere 有可用的升级版本。",
        "current_version": "当前版本：",
        "latest_version": "最新版本：",
        "whats_new": "更新日志：",
        "upgrading": "正在自动升级 Prospere，请稍候...",
        "downloading": "正在下载并安装最新版本...",
        "success": "升级成功！正在重启 Prospere...",
        "failed": "升级失败！",
        "unexpected_error": "升级过程中发生未预期的错误：",
        "continuing": "将继续使用当前版本运行...",
        "more": "... （以及更多）",
    },
}


GITHUB_REPO: Final[str] = "vequalia/prospere"
HEADERS: Final[dict[str, str]] = {"User-Agent": "Prospere-CLI-Updater"}
NO_UPDATE_ENV_VAR: Final[str] = "PROSPERE_NO_UPDATE"


def _get_txt(key: str) -> str:
    """Helper to retrieve localized text based on system settings."""
    try:
        lang = get_language()
    except Exception:
        lang = "en"
    if lang not in LOCALIZED_TEXTS:
        lang = "en"
    return LOCALIZED_TEXTS[lang].get(key, LOCALIZED_TEXTS["en"][key])


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parses a version string (e.g. '0.1.0' or 'v1.2.3') into integers.

    Returns a tuple of integers for version comparison.
    """
    # Clean leading 'v'
    cleaned = version_str.lstrip("v")
    # Match digits
    matches = re.findall(r"\d+", cleaned)
    if not matches:
        return (0, 0, 0)
    # Convert to tuple of ints, pad if shorter than 3
    parsed = [int(m) for m in matches]
    while len(parsed) < 3:
        parsed.append(0)
    return tuple(parsed[:3])


def get_remote_version_and_changelog() -> tuple[str | None, str | None]:
    """Fetches the remote version and changelog from GitHub.

    Uses GitHub Releases API first, falls back to raw pyproject.toml if
    rate-limited or fails.
    """
    # 1. Try GitHub Releases API
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        # Secure: URL is hardcoded to official HTTPS endpoint.
        req = urllib.request.Request(url, headers=HEADERS)  # nosec B310 # noqa: S310
        with urllib.request.urlopen(req, timeout=1.5) as response:  # nosec B310 # noqa: S310
            import json

            data = json.loads(response.read().decode("utf-8"))
            tag_name = data.get("tag_name", "")
            remote_version = tag_name.lstrip("v")
            changelog = data.get("body", "")
            return remote_version, changelog
    except Exception:  # nosec B110 # noqa: S110 - Fallback if Releases API fails.
        pass

    # 2. Fall back to raw pyproject.toml
    try:
        url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/pyproject.toml"
        # Secure: URL is hardcoded to official HTTPS endpoint.
        req = urllib.request.Request(url, headers=HEADERS)  # nosec B310 # noqa: S310
        with urllib.request.urlopen(req, timeout=1.5) as response:  # nosec B310 # noqa: S310
            toml_data = tomllib.loads(response.read().decode("utf-8"))
            remote_version = toml_data.get("project", {}).get("version")
            return remote_version, None
    except Exception:
        return None, None


def check_and_perform_update(local_version_str: str) -> None:
    """Checks for updates and performs automatic update if a new version is

    available.
    """
    # Escape hatch
    if os.environ.get(NO_UPDATE_ENV_VAR) in ("1", "true", "TRUE", "yes", "YES"):
        return

    console = Console()

    # Check for updates with a timeout and spinner
    try:
        with console.status(
            f"[bold accent]{_get_txt('checking')}[/bold accent]", spinner="dots"
        ):
            remote_version_str, changelog = get_remote_version_and_changelog()
    except Exception:
        return  # Gracefully skip on error

    if not remote_version_str:
        return  # Failed to query, skip gracefully

    local_version = parse_version(local_version_str)
    remote_version = parse_version(remote_version_str)

    if remote_version <= local_version:
        return  # Already up to date or newer

    # New version detected! Render the update dashboard.
    console.clear()

    title = Text(f"🚀 {_get_txt('available')}", style="bold magenta")
    content = Text()
    content.append(f"\n{_get_txt('new_version_detected')}\n\n", style="bold white")
    content.append(f"  {_get_txt('current_version')}  ", style="dim")
    content.append(f"v{local_version_str}\n", style="bold red")
    content.append(f"  {_get_txt('latest_version')}   ", style="dim")
    content.append(f"v{remote_version_str}\n\n", style="bold green")

    if changelog:
        content.append(f"✨ {_get_txt('whats_new')}\n", style="bold cyan")
        lines = changelog.strip().split("\n")
        truncated = "\n".join(lines[:10])
        if len(lines) > 10:
            truncated += f"\n  {_get_txt('more')}"
        content.append(f"{truncated}\n\n", style="italic gray")

    content.append(f"{_get_txt('upgrading')}\n", style="bold yellow")

    panel = Panel(
        content, title=title, border_style="magenta", expand=False, padding=(1, 4)
    )
    console.print(panel)

    # Trigger upgrade subprocess
    upgrade_cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        f"git+https://github.com/{GITHUB_REPO}.git",
    ]

    try:
        with console.status(
            f"[bold green]📥 {_get_txt('downloading')}[/bold green]", spinner="arc"
        ):
            # Safe as upgrade command components are hardcoded inside the application.
            subprocess.run(  # nosec B603 # noqa: S603
                upgrade_cmd,
                capture_output=True,
                text=True,
                check=True,
            )

        console.print(f"\n[bold green]✓ {_get_txt('success')}[/bold green]")
        time.sleep(1.0)

        # Hot Reload: reload/restart CLI process. Safe as sys.executable is explicit.
        os.execv(sys.executable, [sys.executable] + sys.argv)  # nosec B606 # noqa: S606

    except subprocess.CalledProcessError as e:
        console.print(f"\n[bold red]❌ {_get_txt('failed')}[/bold red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.strip()}[/dim]")
        console.print(f"[yellow]{_get_txt('continuing')}[/yellow]")
        time.sleep(2.0)
    except Exception as e:
        console.print(f"\n[bold red]❌ {_get_txt('unexpected_error')} {e}[/bold red]")
        console.print(f"[yellow]{_get_txt('continuing')}[/yellow]")
        time.sleep(2.0)
