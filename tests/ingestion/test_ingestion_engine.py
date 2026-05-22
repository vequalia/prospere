import os
import unittest
from tempfile import TemporaryDirectory

from prospere.core.constants import MoneyWizConstants
from prospere.ingestion.engine import (
    IngestionEngineFactory,
    MoneyWizCSVEngine,
)

# CSV content strings in tests are unavoidably long due to the header line
MW_HEADER = (
    '"Name","Current balance","Account","Transfers","Description","Payee",'
    '"Category","Date","Time","Memo","Amount","Currency","Check #","Tags"\n'
)


class TestMoneyWizCSVEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MoneyWizCSVEngine()
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _write_csv(self, name: str, content: str) -> str:
        path = os.path.join(self.tmp_dir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_parse_moneywiz_csv_basic(self) -> None:
        csv_content = (
            "sep=,\n"
            f"{MW_HEADER}"
            '"Checking","10000.00","EUR","","","","","","","","","","",""\n'
            '"","","Checking","","Monthly Salary","Company","Income ► Salary",'
            '"2024/01/01","10:00","","5000.00","EUR","",""\n'
            '"","","Checking","","Rent","Landlord","Housing ► Rent",'
            '"2024/01/05","10:00","","-1500.00","EUR","",""\n'
            '"","","Checking","","Groceries","Supermarket","Food ► Groceries",'
            '"2024/01/15","10:00","","-480.00","EUR","",""\n'
        )
        path = self._write_csv("test_basic.csv", csv_content)

        transactions, balances = self.engine.parse_data(path)

        self.assertGreater(len(balances), 0)
        checking_bal = balances[0]
        if checking_bal is not None:
            self.assertEqual(checking_bal.account_name, "Checking")
            self.assertEqual(checking_bal.balance, 10000.0)
        else:
            self.fail("Checking balance is None")

        salary_txn = next((t for t in transactions if t.amount > 0), None)
        if salary_txn is not None:
            self.assertEqual(salary_txn.primary_category, "Income")
            self.assertEqual(salary_txn.secondary_category, "Salary")
        else:
            self.fail("Salary transaction is None")

    def test_parse_transfers_are_skipped(self) -> None:
        csv_content = (
            "sep=,\n"
            f"{MW_HEADER}"
            '"","","Checking","Transfer_001","Transfer to Savings","","",'
            '"2024/03/15","10:00","","-1000.00","EUR","",""\n'
            '"","","Checking","","Regular Payment","","Food ► Groceries",'
            '"2024/03/15","10:00","","-500.00","EUR","",""\n'
        )
        path = self._write_csv("test_transfer.csv", csv_content)

        transactions, _ = self.engine.parse_data(path)
        self.assertEqual(len(transactions), 1, "Transfer should be skipped")
        txn = transactions[0]
        if txn is not None:
            self.assertEqual(txn.amount, -500.0)
        else:
            self.fail("Transaction is None")

    def test_parse_no_category_is_skipped(self) -> None:
        csv_content = (
            "sep=,\n"
            f"{MW_HEADER}"
            '"","","Checking","","No Category Entry","","","2024/01/15","10:00","",'
            '"-300.00","EUR","",""\n'
            '"","","Checking","","Has Category","","Food ► Groceries",'
            '"2024/01/15","10:00","","-500.00","EUR","",""\n'
        )
        path = self._write_csv("test_no_cat.csv", csv_content)

        transactions, _ = self.engine.parse_data(path)
        self.assertEqual(len(transactions), 1, "Row without category should be skipped")
        txn = transactions[0]
        if txn is not None:
            self.assertEqual(txn.amount, -500.0)
        else:
            self.fail("Transaction is None")

    def test_parse_without_sep_header(self) -> None:
        csv_content = (
            f"{MW_HEADER}"
            '"","","Checking","","Test","","Income ► Salary",'
            '"2024/01/15","10:00","","1000.00","EUR","",""\n'
        )
        path = self._write_csv("test_no_sep.csv", csv_content)

        transactions, _ = self.engine.parse_data(path)
        self.assertEqual(len(transactions), 1)
        txn = transactions[0]
        if txn is not None:
            self.assertEqual(txn.amount, 1000.0)
        else:
            self.fail("Transaction is None")

    def test_parse_file_not_found(self) -> None:
        transactions, balances = self.engine.parse_data("/nonexistent/path.csv")
        self.assertEqual(transactions, [])
        self.assertEqual(balances, [])

    def test_parse_duplicate_prevention(self) -> None:
        csv_content = (
            "sep=,\n"
            f"{MW_HEADER}"
            '"","","Checking","","Monthly Salary","Company","Income ► Salary",'
            '"2024/01/01","10:00","","5000.00","EUR","",""\n'
            '"","","Checking","","Monthly Salary","Company","Income ► Salary",'
            '"2024/01/01","10:00","","5000.00","EUR","",""\n'
        )
        path = self._write_csv("test_dup.csv", csv_content)

        transactions, _ = self.engine.parse_data(path)
        self.assertEqual(len(transactions), 2, "Both rows should be parsed")


class TestIngestionEngineFactory(unittest.TestCase):
    def test_create_moneywiz_engine(self) -> None:
        engine = IngestionEngineFactory.create_engine(MoneyWizConstants.SOURCE_NAME)
        self.assertIsInstance(engine, MoneyWizCSVEngine)

    def test_create_unknown_engine_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            IngestionEngineFactory.create_engine("unknown_source")
        self.assertIn("Unsupported source type", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
