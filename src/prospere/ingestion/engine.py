import csv
import hashlib
import io
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Final

from prospere.core.constants import MoneyWizConstants
from prospere.core.models import AccountBalance, Transaction

logger = logging.getLogger(__name__)


class DataIngestionEngine(ABC):
    """Abstract interface for processing raw financial data exports."""

    @abstractmethod
    def parse_data(
        self, file_path: str
    ) -> tuple[list[Transaction], list[AccountBalance]]:
        """
        Parses a raw file and extracts transactions and current balances.

        Returns:
            A tuple containing (List of Transactions, List of AccountBalances).
        """
        pass


class MoneyWizCSVEngine(DataIngestionEngine):
    """Engine specialized in parsing CSV exports from MoneyWiz."""

    def _process_balance_row(
        self, row_data: dict[str, str], row_index: int
    ) -> AccountBalance | None:
        """Processes a single row as an account balance if applicable."""
        name_val = row_data.get(MoneyWizConstants.COL_NAME, "").strip()
        balance_val = row_data.get(MoneyWizConstants.COL_CURRENT_BALANCE, "").strip()

        if name_val and balance_val:
            try:
                return AccountBalance(
                    account_name=name_val,
                    balance=float(balance_val.replace(",", "")),
                    currency=row_data.get(
                        MoneyWizConstants.COL_ACCOUNT,
                        MoneyWizConstants.UNKNOWN_CURRENCY,
                    ),
                )
            except ValueError as exc:
                logger.debug(f"Skipping balance row {row_index}: {exc}")
        return None

    def _process_transaction_row(
        self, row_data: dict[str, str], row_index: int
    ) -> Transaction | None:
        """Processes a single row as a transaction if applicable."""
        name_val = row_data.get(MoneyWizConstants.COL_NAME, "").strip()
        if name_val:
            return None

        is_transfer = (
            row_data.get(MoneyWizConstants.COL_TRANSFERS)
            and row_data[MoneyWizConstants.COL_TRANSFERS].strip()
        )
        if is_transfer:
            return None

        account_identifier = row_data.get(MoneyWizConstants.COL_ACCOUNT)
        if not account_identifier:
            return None

        try:
            # Extract and parse core transaction fields
            txn_date_str = row_data[MoneyWizConstants.COL_DATE]
            txn_time_str = row_data[MoneyWizConstants.COL_TIME]
            amount_str = row_data[MoneyWizConstants.COL_AMOUNT]
            description = row_data.get(MoneyWizConstants.COL_DESCRIPTION, "")

            transaction_date = datetime.strptime(
                txn_date_str, MoneyWizConstants.DATE_FORMAT
            ).date()
            amount = float(amount_str.replace(",", ""))
            currency = row_data.get(
                MoneyWizConstants.COL_CURRENCY, MoneyWizConstants.UNKNOWN_CURRENCY
            )

            # Handle category hierarchy
            category_raw = row_data.get(MoneyWizConstants.COL_CATEGORY, "").strip()
            if not category_raw:
                # Skip records without a category
                # (usually internal movements or ghost rows)
                return None

            full_category_path = category_raw
            if MoneyWizConstants.CATEGORY_DELIMITER in full_category_path:
                primary_cat, secondary_cat = full_category_path.split(
                    MoneyWizConstants.CATEGORY_DELIMITER, 1
                )
            else:
                primary_cat = full_category_path or MoneyWizConstants.DEFAULT_CATEGORY
                secondary_cat = ""

            # Generate a unique ID to prevent duplicates
            unique_seed = (
                f"{account_identifier}-{txn_date_str}-{txn_time_str}-"
                f"{amount_str}-{description}-{row_index}"
            )
            unique_id = hashlib.md5(
                unique_seed.encode(), usedforsecurity=False
            ).hexdigest()

            return Transaction(
                unique_id=unique_id,
                transaction_date=transaction_date,
                amount=amount,
                currency=currency,
                primary_category=primary_cat,
                secondary_category=secondary_cat,
                account_name=account_identifier,
            )
        except (ValueError, KeyError) as exc:
            logger.warning(f"Malformed transaction row {row_index}: {exc}")
        return None

    def parse_data(
        self, file_path: str
    ) -> tuple[list[Transaction], list[AccountBalance]]:
        """
        Parses MoneyWiz CSV and separates transactions from account balances.
        """
        standardized_transactions: list[Transaction] = []
        account_balances: list[AccountBalance] = []

        try:
            with open(file_path, encoding="utf-8-sig") as csv_file:
                raw_content = csv_file.read()
        except FileNotFoundError:
            logger.error(f"Source file not found: {file_path}")
            return [], []

        if raw_content.startswith(MoneyWizConstants.ROW_SEPARATOR):
            raw_content = raw_content.split("\n", 1)[1]

        content_buffer = io.StringIO(raw_content)
        csv_reader = csv.DictReader(content_buffer)

        for row_index, row_data in enumerate(csv_reader):
            # 1. Try to process as balance row
            balance = self._process_balance_row(row_data, row_index)
            if balance:
                account_balances.append(balance)
                continue

            # 2. Try to process as transaction row
            txn = self._process_transaction_row(row_data, row_index)
            if txn:
                standardized_transactions.append(txn)

        return standardized_transactions, account_balances


class IngestionEngineFactory:
    """Factory to retrieve ingestion engines based on source type."""

    _SUPPORTED_ENGINES: Final[dict[str, DataIngestionEngine]] = {
        "moneywiz": MoneyWizCSVEngine()
    }

    @classmethod
    def create_engine(cls, source_type: str) -> DataIngestionEngine:
        engine = cls._SUPPORTED_ENGINES.get(source_type.lower())
        if not engine:
            available = ", ".join(cls._SUPPORTED_ENGINES.keys())
            raise ValueError(
                f"Unsupported source type '{source_type}'. Available: {available}"
            )
        return engine
