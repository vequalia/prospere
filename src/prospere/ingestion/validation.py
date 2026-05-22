"""Shared validators for processed financial data files."""

import json
import os
from typing import Any

import pandas as pd

REQUIRED_XLSX_COLUMNS = [
    "unique_id",
    "transaction_date",
    "amount",
    "currency",
    "primary_category",
    "secondary_category",
    "account_name",
]

REQUIRED_BALANCE_FIELDS: set[str] = {"account_name", "balance", "currency"}


def validate_transactions_xlsx(path: str) -> tuple[bool, str]:
    """Validate that an XLSX file has the required structure.

    Returns:
        (valid, message).  Message explains the first validation failure.
    """
    if not os.path.exists(path):
        return False, f"File not found: {path}"

    try:
        df = pd.read_excel(path)
    except Exception as e:
        return False, f"Failed to read XLSX: {e}"

    missing = [c for c in REQUIRED_XLSX_COLUMNS if c not in df.columns]
    if missing:
        return False, f"Missing columns: {', '.join(missing)}"

    if df.empty:
        return False, "File contains no rows"

    try:
        pd.to_datetime(df["transaction_date"].astype(str), format="%Y-%m-%d")
    except Exception:
        return False, "Column 'transaction_date' must be in YYYY-MM-DD format"

    try:
        df["amount"].astype(float)
    except Exception:
        return False, "Column 'amount' must be numeric"

    return True, "OK"


def validate_balances_json(path: str) -> tuple[bool, str]:
    """Validate that a JSON file is a valid balances array.

    Returns:
        (valid, message).  Message explains the first validation failure.
    """
    if not os.path.exists(path):
        return False, f"File not found: {path}"

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    except Exception as e:
        return False, f"Failed to read file: {e}"

    if not isinstance(data, list):
        return False, "Balances file must be a JSON array"

    if not data:
        return False, "Balances array is empty"

    for i, entry in enumerate(data):
        err = _validate_balance_entry(entry, i)
        if err:
            return False, err

    return True, "OK"


def _validate_balance_entry(entry: dict[str, Any], i: int) -> str | None:
    """Validate a single balance entry. Returns error string or None."""
    if not isinstance(entry, dict):
        return f"Entry {i} is not an object"
    missing = REQUIRED_BALANCE_FIELDS - set(entry.keys())
    if missing:
        return f"Entry {i} missing fields: {', '.join(sorted(missing))}"
    try:
        float(entry["balance"])
    except (ValueError, TypeError):
        return f"Entry {i}: 'balance' must be numeric"
    if not entry["account_name"] or not str(entry["account_name"]).strip():
        return f"Entry {i}: 'account_name' must be non-empty"
    return None
