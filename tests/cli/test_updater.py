import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from prospere.cli.updater import (
    check_and_perform_update,
    get_remote_version_and_changelog,
    parse_version,
)


class TestUpdater(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("0.1.0"), (0, 1, 0))
        self.assertEqual(parse_version("1.23.456"), (1, 23, 456))
        self.assertEqual(parse_version("v1.0"), (1, 0, 0))
        self.assertEqual(parse_version("invalid"), (0, 0, 0))

    @patch("urllib.request.urlopen")
    def test_get_remote_version_and_changelog_releases_success(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Mocking Releases API success
        mock_response = MagicMock()
        mock_response.read.return_value = (
            b'{"tag_name": "v0.2.0", "body": "Fix all bugs"}'
        )
        mock_urlopen.return_value.__enter__.return_value = mock_response

        version, changelog = get_remote_version_and_changelog()
        self.assertEqual(version, "0.2.0")
        self.assertEqual(changelog, "Fix all bugs")

    @patch("urllib.request.urlopen")
    def test_get_remote_version_and_changelog_fallback_to_pyproject(
        self, mock_urlopen: MagicMock
    ) -> None:
        # First call (Releases API) raises Exception,
        # Second call (pyproject.toml) succeeds
        mock_response_pyproject = MagicMock()
        mock_response_pyproject.read.return_value = (
            b'[project]\nname = "prospere"\nversion = "0.3.0"'
        )

        # side_effect returns exception first, then pyproject response
        mock_urlopen.side_effect = [Exception("Rate limit"), mock_response_pyproject]

        # When enters context manager
        mock_response_pyproject.__enter__.return_value = mock_response_pyproject

        version, changelog = get_remote_version_and_changelog()
        self.assertEqual(version, "0.3.0")
        self.assertIsNone(changelog)

    @patch("urllib.request.urlopen")
    def test_get_remote_version_and_changelog_all_fail(
        self, mock_urlopen: MagicMock
    ) -> None:
        mock_urlopen.side_effect = Exception("No internet")

        version, changelog = get_remote_version_and_changelog()
        self.assertIsNone(version)
        self.assertIsNone(changelog)

    @patch.dict(os.environ, {"PROSPERE_NO_UPDATE": "1"})
    @patch("prospere.cli.updater.get_remote_version_and_changelog")
    def test_check_and_perform_update_bypass(self, mock_get_remote: MagicMock) -> None:
        check_and_perform_update("0.1.0")
        mock_get_remote.assert_not_called()

    @patch(
        "prospere.cli.updater.get_remote_version_and_changelog",
        return_value=("0.1.0", None),
    )
    @patch("subprocess.run")
    def test_check_and_perform_update_no_upgrade_needed(
        self, mock_run: MagicMock, mock_get_remote: MagicMock
    ) -> None:
        check_and_perform_update("0.1.0")
        mock_run.assert_not_called()

    @patch(
        "prospere.cli.updater.get_remote_version_and_changelog",
        return_value=("0.2.0", "New release notes"),
    )
    @patch("subprocess.run")
    @patch("os.execv")
    @patch("prospere.cli.updater.get_language", return_value="en")
    def test_check_and_perform_update_success(
        self,
        mock_get_lang: MagicMock,
        mock_execv: MagicMock,
        mock_run: MagicMock,
        mock_get_remote: MagicMock,
    ) -> None:
        # Mock subprocess successful upgrade
        mock_run.return_value = MagicMock(returncode=0)

        check_and_perform_update("0.1.0")

        # Verify subprocess pip install was called
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        self.assertIn("pip", cmd)
        self.assertIn("install", cmd)
        self.assertIn("--upgrade", cmd)

        # Verify os.execv was called to hot reload
        mock_execv.assert_called_once_with(sys.executable, [sys.executable] + sys.argv)

    @patch("prospere.cli.main.run_menu")
    @patch("prospere.cli.updater.check_and_perform_update")
    def test_main_integration(
        self, mock_updater: MagicMock, mock_run_menu: MagicMock
    ) -> None:
        from prospere.cli.main import main

        # Clear command line args to avoid parsing flags during test
        with patch.object(sys, "argv", ["prospere"]):
            main()

        # Verify updater was integrated and called
        mock_updater.assert_called_once_with("0.1.0")
        # Verify run_menu was called afterwards
        mock_run_menu.assert_called_once()


if __name__ == "__main__":
    unittest.main()
