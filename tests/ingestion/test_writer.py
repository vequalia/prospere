import os
import unittest
from tempfile import TemporaryDirectory

from prospere.core.models import AccountBalance, Transaction


class TestWriteDataset(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _path(self, name: str) -> str:
        return os.path.join(self.tmp_dir.name, name)

    def _make_transaction(self, **kwargs: object) -> Transaction:
        import datetime

        defaults: dict[str, object] = {
            "unique_id": "abc123def45678901234567890123456",
            "transaction_date": datetime.date(2024, 1, 15),
            "amount": 100.50,
            "currency": "USD",
            "primary_category": "Income",
            "secondary_category": "",
            "account_name": "Checking",
        }
        defaults.update(kwargs)
        return Transaction(**defaults)  # type: ignore[arg-type]

    def _make_balance(self, **kwargs: object) -> AccountBalance:
        defaults: dict[str, object] = {
            "account_name": "Checking",
            "balance": 1000.0,
            "currency": "USD",
        }
        defaults.update(kwargs)
        return AccountBalance(**defaults)  # type: ignore[arg-type]

    def test_write_and_validate(self) -> None:
        from prospere.ingestion.writer import write_dataset

        txns = [self._make_transaction()]
        balances = [self._make_balance()]
        xlsx_path = self._path("transactions.xlsx")
        json_path = self._path("balances.json")

        success, msg = write_dataset(txns, balances, xlsx_path, json_path)
        self.assertTrue(success, msg)
        self.assertTrue(os.path.exists(xlsx_path))
        self.assertTrue(os.path.exists(json_path))

    def test_creates_output_directory(self) -> None:
        from prospere.ingestion.writer import write_dataset

        txns = [self._make_transaction()]
        balances = [self._make_balance()]
        xlsx_path = self._path("subdir/transactions.xlsx")
        json_path = self._path("subdir/balances.json")

        success, msg = write_dataset(txns, balances, xlsx_path, json_path)
        self.assertTrue(success, msg)
        self.assertTrue(os.path.exists(xlsx_path))
        self.assertTrue(os.path.exists(json_path))

    def test_empty_transactions_fails(self) -> None:
        from prospere.ingestion.writer import write_dataset

        balances = [self._make_balance()]
        xlsx_path = self._path("transactions.xlsx")
        json_path = self._path("balances.json")

        success, msg = write_dataset([], balances, xlsx_path, json_path)
        self.assertFalse(success)
