import unittest
from unittest.mock import patch

from prospere.cli.utils import (
    CLIStyles,
    Spinner,
    format_currency,
    prompt,
    prompt_bool,
    prompt_csv,
    prompt_float,
    prompt_int,
)


class TestFormatCurrency(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(format_currency(1234), "€1,234")

    def test_million(self) -> None:
        self.assertEqual(format_currency(2_500_000), "€2.50M")

    def test_large_thousand(self) -> None:
        self.assertEqual(format_currency(150_000), "€150.0K")

    def test_small_thousand(self) -> None:
        self.assertEqual(format_currency(45_000, use_suffix=True), "€45,000")

    def test_negative(self) -> None:
        self.assertEqual(format_currency(-500), "-€500")

    def test_negative_million(self) -> None:
        self.assertEqual(format_currency(-1_200_000), "-€1.20M")

    def test_no_suffix(self) -> None:
        result = format_currency(5_000_000, use_suffix=False)
        self.assertNotIn("M", result)
        self.assertEqual(result, "€5,000,000")

    def test_zero(self) -> None:
        self.assertEqual(format_currency(0), "€0")

    def test_custom_symbol(self) -> None:
        self.assertEqual(format_currency(1000, currency_symbol="$"), "$1,000")

    def test_precision(self) -> None:
        result = format_currency(100.567, use_suffix=False, precision=2)
        self.assertIn(".57", result)

    def test_negative_hundred_k(self) -> None:
        self.assertEqual(format_currency(-200_000), "-€200.0K")

    def test_float_input(self) -> None:
        result = format_currency(1500000.75, use_suffix=True)
        self.assertIn("M", result)


class TestCLIStyles(unittest.TestCase):
    def test_styles_exist(self) -> None:
        self.assertIsInstance(CLIStyles.RESET, str)
        self.assertIsInstance(CLIStyles.BOLD, str)
        self.assertIsInstance(CLIStyles.GREEN, str)
        self.assertIsInstance(CLIStyles.RED, str)
        self.assertIsInstance(CLIStyles.YELLOW, str)
        self.assertIsInstance(CLIStyles.POINTER, str)
        self.assertIsInstance(CLIStyles.SPINNER_CHARS, list)

    def test_spinner_has_chars(self) -> None:
        self.assertGreater(len(CLIStyles.SPINNER_CHARS), 0)


class TestSpinner(unittest.TestCase):
    def test_context_manager_enters_and_exits(self) -> None:
        with Spinner(message="Testing..."):
            pass

    def test_context_manager_custom_message(self) -> None:
        spinner = Spinner(message="Loading data")
        self.assertEqual(spinner.message, "Loading data")


class TestPromptHelpers(unittest.TestCase):
    @patch("builtins.input", return_value="simple_answer")
    def test_prompt_returns_input(self, mock_input: object) -> None:
        result = prompt("Enter value", default="fallback")
        self.assertEqual(result, "simple_answer")

    @patch("builtins.input", return_value="")
    def test_prompt_uses_default(self, mock_input: object) -> None:
        result = prompt("Enter value", default="fallback")
        self.assertEqual(result, "fallback")

    @patch("builtins.input", return_value="42")
    def test_prompt_int_valid(self, mock_input: object) -> None:
        result = prompt_int("Enter number", default=10)
        self.assertEqual(result, 42)

    @patch("builtins.input", side_effect=["-1", "5"])
    def test_prompt_int_retry_on_invalid(self, mock_input: object) -> None:
        result = prompt_int("Enter number", default=10, min_value=1)
        self.assertEqual(result, 5)

    @patch("builtins.input", return_value="3.14")
    def test_prompt_float_valid(self, mock_input: object) -> None:
        result = prompt_float("Enter float", default=1.0)
        self.assertEqual(result, 3.14)

    @patch("builtins.input", return_value="y")
    def test_prompt_bool_true(self, mock_input: object) -> None:
        result = prompt_bool("Continue?", default=True)
        self.assertTrue(result)

    @patch("builtins.input", return_value="N")
    def test_prompt_bool_false(self, mock_input: object) -> None:
        result = prompt_bool("Continue?", default=True)
        self.assertFalse(result)

    @patch("builtins.input", return_value="")
    def test_prompt_csv_defaults(self, mock_input: object) -> None:
        result = prompt_csv(
            "Select categories",
            detected=["A", "B", "C"],
            defaults=["A", "C"],
        )
        self.assertEqual(result, ["A", "C"])


if __name__ == "__main__":
    unittest.main()
