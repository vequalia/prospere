import os
import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from prospere.ingestion.cleaner import (
    ColumnHeuristics,
    analyze_file,
    clean_dataframe,
    format_analysis,
    generate_unique_ids,
    is_moneywiz_format,
    normalize_amount_series,
    normalize_currency_series,
    normalize_date_series,
    suggest_column_mappings,
)
from prospere.ingestion.writer import write_dataset


class TestIsMoneyWizFormat(unittest.TestCase):
    def test_moneywiz_columns_detected(self) -> None:
        df = pd.DataFrame(
            columns=["Name", "Account", "Date", "Time", "Amount", "Category"]
        )
        self.assertTrue(is_moneywiz_format(df))

    def test_non_moneywiz_columns(self) -> None:
        df = pd.DataFrame(columns=["txn_date", "amount", "description"])
        self.assertFalse(is_moneywiz_format(df))

    def test_moneywiz_extra_columns(self) -> None:
        df = pd.DataFrame(
            columns=[
                "Name",
                "Account",
                "Date",
                "Time",
                "Amount",
                "Category",
                "ExtraColumn",
            ]
        )
        self.assertTrue(is_moneywiz_format(df))

    def test_moneywiz_missing_column(self) -> None:
        df = pd.DataFrame(columns=["Name", "Account", "Date", "Time", "Amount"])
        self.assertFalse(is_moneywiz_format(df))


class TestSuggestColumnMappings(unittest.TestCase):
    def test_standard_names(self) -> None:
        df = pd.DataFrame(
            columns=["date", "amount", "description", "category", "account"]
        )
        result = suggest_column_mappings(df)
        self.assertEqual(result.date_column, "date")
        self.assertEqual(result.amount_column, "amount")
        self.assertEqual(result.description_column, "description")
        self.assertEqual(result.category_column, "category")
        self.assertEqual(result.account_column, "account")

    def test_variant_names(self) -> None:
        df = pd.DataFrame(
            columns=[
                "Transaction Date",
                "Net Amount",
                "Payee",
                "Category",
                "Account Name",
                "Currency Code",
            ]
        )
        result = suggest_column_mappings(df)
        self.assertEqual(result.date_column, "Transaction Date")
        self.assertEqual(result.amount_column, "Net Amount")
        self.assertEqual(result.description_column, "Payee")
        self.assertEqual(result.account_column, "Account Name")
        self.assertEqual(result.currency_column, "Currency Code")

    def test_no_matches(self) -> None:
        df = pd.DataFrame(columns=["foo", "bar", "baz", "qux"])
        result = suggest_column_mappings(df)
        self.assertIsNone(result.date_column)
        self.assertIsNone(result.amount_column)
        self.assertIsNone(result.description_column)
        self.assertIsNone(result.category_column)

    def test_balance_columns(self) -> None:
        df = pd.DataFrame(columns=["Date", "Amount", "Account", "Current Balance"])
        result = suggest_column_mappings(df)
        self.assertEqual(result.balance_value_column, "Current Balance")
        self.assertEqual(result.balance_account_column, "Account")

    def test_subcategory_detection(self) -> None:
        df = pd.DataFrame(columns=["Date", "Amount", "Category", "Subcategory"])
        result = suggest_column_mappings(df)
        self.assertEqual(result.category_column, "Category")
        self.assertEqual(result.subcategory_column, "Subcategory")

    def test_whitespace_normalized(self) -> None:
        df = pd.DataFrame(columns=["  Transaction   Date  ", "  Net  Amount  "])
        result = suggest_column_mappings(df)
        self.assertIsNotNone(result.date_column)
        self.assertIsNotNone(result.amount_column)


class TestAnalyzeFile(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _path(self, name: str) -> str:
        return os.path.join(self.tmp_dir.name, name)

    def test_analyze_csv_comma(self) -> None:
        path = self._path("test.csv")
        content = (
            "date,amount,description,category,account\n"
            "2024-01-01,100.0,Test,Food,Checking\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        result = analyze_file(path)
        self.assertEqual(result.file_type, "csv")
        self.assertGreater(result.total_rows, 0)
        self.assertEqual(len(result.columns), 5)
        self.assertEqual(result.suggested_mapping.date_column, "date")

    def test_analyze_csv_semicolon(self) -> None:
        path = self._path("test.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("date;amount;description\n2024-01-01;100.0;Test\n")

        result = analyze_file(path)
        self.assertEqual(result.delimiter, ";")

    def test_analyze_csv_tab(self) -> None:
        path = self._path("test.tsv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("date\tamount\tdescription\n2024-01-01\t100.0\tTest\n")

        result = analyze_file(path)
        self.assertEqual(result.file_type, "tsv")

    def test_analyze_xlsx(self) -> None:
        path = self._path("test.xlsx")
        df = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "amount": [100.0],
                "description": ["Test"],
            }
        )
        df.to_excel(path, index=False)

        result = analyze_file(path)
        self.assertEqual(result.file_type, "xlsx")
        self.assertEqual(result.total_rows, 1)
        self.assertEqual(result.suggested_mapping.date_column, "date")

    def test_analyze_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            analyze_file("/nonexistent/path.csv")

    def test_analyze_utf8_with_bom(self) -> None:
        path = self._path("test.csv")
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("date,amount\n2024-01-01,100.0\n")

        result = analyze_file(path)
        self.assertEqual(result.encoding, "utf-8-sig")

    def test_sample_rows_included(self) -> None:
        path = self._path("test.csv")
        content = (
            "date,amount,description\n2024-01-01,100.0,Test\n2024-01-02,200.0,Test2\n"
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        result = analyze_file(path)
        self.assertEqual(len(result.sample_rows), 2)


class TestNormalizeDateSeries(unittest.TestCase):
    def test_iso_format(self) -> None:
        s = pd.Series(["2024-01-15", "2024-12-31"])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "2024-01-15")
        self.assertEqual(result.iloc[1], "2024-12-31")

    def test_slash_format(self) -> None:
        s = pd.Series(["2024/01/15", "2024/12/31"])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "2024-01-15")

    def test_dmy_format(self) -> None:
        s = pd.Series(["15/01/2024", "31/12/2024"])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "2024-01-15")

    def test_mdy_format(self) -> None:
        s = pd.Series(["01/15/2024", "12/31/2024"])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "2024-01-15")

    def test_dot_format(self) -> None:
        s = pd.Series(["15.01.2024"])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "2024-01-15")

    def test_mixed_formats(self) -> None:
        s = pd.Series(["2024-01-15", "15/01/2024", "2024/12/31"])
        result = normalize_date_series(s)
        self.assertIn("2024-01-15", result.iloc[0])
        self.assertIn("2024-01-15", result.iloc[1])

    def test_invalid_date_returns_empty(self) -> None:
        s = pd.Series(["not-a-date", "garbage"])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "")

    def test_nan_returns_empty(self) -> None:
        s = pd.Series([None, float("nan")])
        result = normalize_date_series(s)
        self.assertEqual(result.iloc[0], "")
        self.assertEqual(result.iloc[1], "")


class TestNormalizeAmountSeries(unittest.TestCase):
    def test_plain_float(self) -> None:
        s = pd.Series(["100.50", "-50.25"])
        result = normalize_amount_series(s)
        self.assertEqual(result.iloc[0], 100.50)
        self.assertEqual(result.iloc[1], -50.25)

    def test_dollar_sign(self) -> None:
        s = pd.Series(["$1,234.56", "$-500.00"])
        result = normalize_amount_series(s)
        self.assertEqual(result.iloc[0], 1234.56)
        self.assertEqual(result.iloc[1], -500.00)

    def test_euro_sign(self) -> None:
        s = pd.Series(["€1.234,56"])
        result = normalize_amount_series(s)
        self.assertAlmostEqual(result.iloc[0], 1234.56)

    def test_parentheses_negative(self) -> None:
        s = pd.Series(["(123.45)", "(1,000.00)"])
        result = normalize_amount_series(s)
        self.assertEqual(result.iloc[0], -123.45)
        self.assertEqual(result.iloc[1], -1000.00)

    def test_trailing_minus(self) -> None:
        s = pd.Series(["123.45-", "1000-"])
        result = normalize_amount_series(s)
        self.assertEqual(result.iloc[0], -123.45)
        self.assertEqual(result.iloc[1], -1000.00)

    def test_credit_suffix(self) -> None:
        s = pd.Series(["123.45CR", "1000cr"])
        result = normalize_amount_series(s)
        self.assertEqual(result.iloc[0], 123.45)
        self.assertEqual(result.iloc[1], 1000.00)

    def test_nan_returns_none(self) -> None:
        s = pd.Series([None, float("nan"), ""])
        result = normalize_amount_series(s)
        self.assertIsNone(result.iloc[0])
        self.assertIsNone(result.iloc[1])
        self.assertIsNone(result.iloc[2])


class TestNormalizeCurrencySeries(unittest.TestCase):
    def test_iso_codes_passthrough(self) -> None:
        s = pd.Series(["USD", "EUR", "CNY"])
        result = normalize_currency_series(s)
        self.assertEqual(result.iloc[0], "USD")
        self.assertEqual(result.iloc[1], "EUR")
        self.assertEqual(result.iloc[2], "CNY")

    def test_symbols(self) -> None:
        s = pd.Series(["$", "€", "¥"])
        result = normalize_currency_series(s)
        self.assertEqual(result.iloc[0], "USD")
        self.assertEqual(result.iloc[1], "EUR")
        self.assertEqual(result.iloc[2], "CNY")

    def test_lowercase_codes(self) -> None:
        s = pd.Series(["usd", "eur", "gbp"])
        result = normalize_currency_series(s)
        self.assertEqual(result.iloc[0], "USD")
        self.assertEqual(result.iloc[1], "EUR")
        self.assertEqual(result.iloc[2], "GBP")

    def test_unknown_returns_unknown(self) -> None:
        s = pd.Series(["XYZ", "something-weird"])
        result = normalize_currency_series(s)
        self.assertEqual(result.iloc[0], "Unknown")
        self.assertEqual(result.iloc[1], "Unknown")

    def test_nan_returns_unknown(self) -> None:
        s = pd.Series([None, float("nan")])
        result = normalize_currency_series(s)
        self.assertEqual(result.iloc[0], "Unknown")


class TestGenerateUniqueIds(unittest.TestCase):
    def test_deterministic(self) -> None:
        acct = pd.Series(["Checking", "Checking"])
        date = pd.Series(["2024-01-01", "2024-01-01"])
        amt = pd.Series([100.0, 100.0])
        desc = pd.Series(["Test", "Test"])

        ids1 = generate_unique_ids(acct, date, amt, desc)
        ids2 = generate_unique_ids(acct, date, amt, desc)
        self.assertEqual(ids1, ids2)

    def test_unique_per_row(self) -> None:
        acct = pd.Series(["Checking", "Checking"])
        date = pd.Series(["2024-01-01", "2024-01-01"])
        amt = pd.Series([100.0, 200.0])
        desc = pd.Series(["Test", "Test"])

        ids = generate_unique_ids(acct, date, amt, desc)
        self.assertNotEqual(ids[0], ids[1])

    def test_length_is_32(self) -> None:
        acct = pd.Series(["Checking"])
        date = pd.Series(["2024-01-01"])
        amt = pd.Series([100.0])
        desc = pd.Series(["Test"])

        ids = generate_unique_ids(acct, date, amt, desc)
        self.assertEqual(len(ids[0]), 32)


class TestCleanDataFrame(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_basic_cleaning(self) -> None:
        df = pd.DataFrame(
            {
                "txn_date": ["2024-01-15", "2024-02-01"],
                "amount": ["100.50", "-50.00"],
                "currency": ["USD", "USD"],
                "description": ["Salary", "Groceries"],
                "category": ["Income", "Food"],
                "account": ["Checking", "Checking"],
            }
        )

        mapping = ColumnHeuristics(
            date_column="txn_date",
            amount_column="amount",
            currency_column="currency",
            description_column="description",
            category_column="category",
            account_column="account",
        )

        transactions, balances = clean_dataframe(df, mapping)

        self.assertEqual(len(transactions), 2)
        self.assertEqual(len(balances), 0)
        self.assertEqual(transactions[0].amount, 100.50)
        self.assertEqual(transactions[1].amount, -50.00)
        self.assertEqual(transactions[0].primary_category, "Income")
        self.assertEqual(transactions[0].account_name, "Checking")
        self.assertEqual(len(transactions[0].unique_id), 32)

    def test_category_splitting(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "amount": [100.0],
                "category": ["Income :: Salary"],
                "account": ["Checking"],
            }
        )

        mapping = ColumnHeuristics(
            date_column="date",
            amount_column="amount",
            category_column="category",
            account_column="account",
        )

        transactions, _ = clean_dataframe(df, mapping)
        self.assertEqual(transactions[0].primary_category, "Income")
        self.assertEqual(transactions[0].secondary_category, "Salary")

    def test_category_splitting_custom_delimiter(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "amount": [100.0],
                "category": ["Income > Salary"],
                "account": ["Checking"],
            }
        )

        mapping = ColumnHeuristics(
            date_column="date",
            amount_column="amount",
            category_column="category",
            account_column="account",
        )

        transactions, _ = clean_dataframe(df, mapping, category_delimiter=" > ")
        self.assertEqual(transactions[0].primary_category, "Income")
        self.assertEqual(transactions[0].secondary_category, "Salary")

    def test_balance_extraction(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2024-01-01", ""],
                "amount": [100.0, ""],
                "account": ["Checking", "Savings"],
                "balance": ["", "5000.00"],
            }
        )

        mapping = ColumnHeuristics(
            date_column="date",
            amount_column="amount",
            account_column="account",
            balance_account_column="account",
            balance_value_column="balance",
        )

        transactions, balances = clean_dataframe(df, mapping)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0].account_name, "Savings")
        self.assertEqual(balances[0].balance, 5000.00)

    def test_empty_transactions_with_balances(self) -> None:
        df = pd.DataFrame(
            {
                "account": ["Checking", "Savings"],
                "balance": ["1000.00", "2000.00"],
            }
        )

        mapping = ColumnHeuristics(
            balance_account_column="account",
            balance_value_column="balance",
        )

        transactions, balances = clean_dataframe(df, mapping)
        self.assertEqual(len(transactions), 0)
        self.assertEqual(len(balances), 2)

    def test_missing_columns_filled_with_defaults(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "amount": [100.0],
            }
        )

        mapping = ColumnHeuristics(
            date_column="date",
            amount_column="amount",
        )

        transactions, _ = clean_dataframe(df, mapping)
        self.assertEqual(transactions[0].currency, "Unknown")
        self.assertEqual(transactions[0].account_name, "Unknown")

    def test_output_feeds_write_dataset(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2024-01-15", ""],
                "amount": [100.50, ""],
                "currency": ["USD", ""],
                "category": ["Income", ""],
                "account": ["Checking", "Checking"],
                "balance": ["", "1000.00"],
            }
        )

        mapping = ColumnHeuristics(
            date_column="date",
            amount_column="amount",
            currency_column="currency",
            category_column="category",
            account_column="account",
            balance_account_column="account",
            balance_value_column="balance",
        )

        transactions, balances = clean_dataframe(df, mapping)

        xlsx_path = os.path.join(self.tmp_dir.name, "transactions.xlsx")
        json_path = os.path.join(self.tmp_dir.name, "balances.json")
        success, msg = write_dataset(transactions, balances, xlsx_path, json_path)
        self.assertTrue(success, msg)


class TestFormatAnalysis(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_format_analysis_output(self) -> None:
        path = os.path.join(self.tmp_dir.name, "test.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("date,amount,description\n2024-01-01,100.0,Test\n")

        analysis = analyze_file(path)
        text = format_analysis(analysis)
        self.assertIn("test.csv", text)
        self.assertIn("date", text)
        self.assertIn("amount", text)
        self.assertIn("Suggested mapping", text)

    def test_format_analysis_shows_not_detected(self) -> None:
        path = os.path.join(self.tmp_dir.name, "test.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("foo,bar,baz\n1,2,3\n")

        analysis = analyze_file(path)
        text = format_analysis(analysis)
        self.assertIn("(not detected)", text)
