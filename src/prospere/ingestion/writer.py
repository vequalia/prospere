"""Shared write pipeline for persisting processed financial data.

Every ingestion path (MoneyWiz engine, cleaner, future engines) funnels
through ``write_dataset`` so output format and validation stay consistent.
"""

import json
import logging
import os
from dataclasses import asdict

import pandas as pd

from prospere.core.models import AccountBalance, Transaction
from prospere.ingestion.validation import (
    validate_balances_json,
    validate_transactions_xlsx,
)

logger = logging.getLogger(__name__)


def write_dataset(
    transactions: list[Transaction],
    balances: list[AccountBalance],
    xlsx_path: str,
    json_path: str,
) -> tuple[bool, str]:
    """Persist *transactions* and *balances* as XLSX + JSON and validate.

    Returns:
        (success, message).
    """
    if not transactions:
        return False, "No transactions to write."

    os.makedirs(os.path.dirname(xlsx_path) or ".", exist_ok=True)

    records = [asdict(txn) for txn in transactions]
    df = pd.DataFrame(records)
    df.to_excel(xlsx_path, index=False)

    balance_records = [asdict(b) for b in balances]
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(balance_records, fh, indent=4, ensure_ascii=False)

    valid, msg = validate_transactions_xlsx(xlsx_path)
    if not valid:
        return False, f"XLSX validation failed: {msg}"

    valid, msg = validate_balances_json(json_path)
    if not valid:
        return False, f"JSON validation failed: {msg}"

    return True, f"Written: {xlsx_path}, {json_path}"
