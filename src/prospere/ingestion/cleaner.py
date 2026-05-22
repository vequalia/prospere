"""Utility for cleaning financial data from arbitrary sources into Prospere format.

Provides file analysis, column-mapping heuristics, data normalization,
and output writing so that CSV / TSV / XLSX exports from any accounting
tool can be transformed into the standard ``processed_transactions.xlsx``
+ ``processed_balances.json`` pair that Prospere consumes.
"""

import csv
import datetime as dt
import hashlib
import io
import logging
import os
from dataclasses import dataclass
from typing import Any

import pandas as pd

from prospere.core.models import AccountBalance, Transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ColumnHeuristics:
    """Best-guess column mapping produced by ``suggest_column_mappings``."""

    date_column: str | None = None
    amount_column: str | None = None
    description_column: str | None = None
    category_column: str | None = None
    subcategory_column: str | None = None
    account_column: str | None = None
    currency_column: str | None = None
    balance_account_column: str | None = None
    balance_value_column: str | None = None


@dataclass
class ColumnInfo:
    """Lightweight column descriptor for the analysis report."""

    name: str
    dtype: str
    non_null_count: int
    sample_values: list[str] | None = None


@dataclass
class FileAnalysis:
    """Result of ``analyze_file`` — everything needed to present findings."""

    file_path: str
    file_type: str  # "csv", "xlsx", "tsv"
    encoding: str
    delimiter: str | None
    total_rows: int
    columns: list[ColumnInfo]
    sample_rows: list[dict[Any, Any]]
    suggested_mapping: ColumnHeuristics


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENCODING_CANDIDATES = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
_DELIMITER_CANDIDATES = [",", ";", "\t", "|"]

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%Y%m%d",
    "%d.%m.%Y",
    "%m.%d.%Y",
]

_CATEGORY_DELIMITERS = [" ► ", "::", " > ", " / ", "\\"]

# Heuristic keywords per standard field, ordered by priority.
_HEURISTIC_KEYWORDS: dict[str, list[str]] = {
    "date": [
        "date",
        "txn_date",
        "transaction_date",
        "posting_date",
        "posted_date",
        "trade_date",
        "trans date",
        "trans.date",
        "value date",
        "valuedate",
    ],
    "amount": [
        "amount",
        "sum",
        "value",
        "net",
        "net amount",
        "transaction_amount",
        "txn_amount",
        "debit",
        "credit",
    ],
    "description": [
        "description",
        "desc",
        "payee",
        "memo",
        "narrative",
        "details",
        "note",
        "remarks",
        "comment",
    ],
    "category": [
        "category",
        "cat",
        "primary_category",
        "primary category",
        "type",
        "transaction type",
        "txn_type",
    ],
    "subcategory": [
        "subcategory",
        "sub_category",
        "secondary_category",
        "secondary category",
        "sub-category",
        "sub cat",
    ],
    "account": [
        "account",
        "account_name",
        "account name",
        "accountname",
        "source account",
        "from account",
    ],
    "currency": [
        "currency",
        "ccy",
        "cur",
        "currency code",
        "currency_code",
    ],
    "balance_account": [
        "account name",
        "account_name",
        "account",
    ],
    "balance_value": [
        "balance",
        "current balance",
        "current_balance",
        "balance amount",
        "closing balance",
        "ending balance",
    ],
}

_CURRENCY_SYMBOL_MAP: dict[str, str] = {
    "$": "USD",
    "US$": "USD",
    "usd": "USD",
    "us dollar": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "¥": "CNY",
    "￥": "CNY",
    "cny": "CNY",
    "rmb": "CNY",
    "£": "GBP",
    "gbp": "GBP",
    "₪": "ILS",
    "ils": "ILS",
    "₩": "KRW",
    "krw": "KRW",
    "₹": "INR",
    "inr": "INR",
}

# MoneyWiz-specific column names (from MoneyWizConstants).
_MONEYWIZ_SIGNATURE_COLUMNS = {
    "Name",
    "Account",
    "Date",
    "Time",
    "Amount",
    "Category",
}

_UNKNOWN = "Unknown"

# Canonical field names used internally after _apply_column_mapping.
_TXN_DATE = "transaction_date"
_AMOUNT = "amount"
_CURRENCY = "currency"
_PRIMARY_CAT = "primary_category"
_SECONDARY_CAT = "secondary_category"
_ACCOUNT_NAME = "account_name"
_DESCRIPTION = "description"
_CATEGORY_RAW = "category_raw"

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def is_moneywiz_format(df: pd.DataFrame) -> bool:
    """Return True when *df* columns match the MoneyWiz CSV signature."""
    return _MONEYWIZ_SIGNATURE_COLUMNS.issubset(set(df.columns))


# ---------------------------------------------------------------------------
# File analysis
# ---------------------------------------------------------------------------


def analyze_file(file_path: str) -> FileAnalysis:
    """Detect format, encoding, delimiter and return a full ``FileAnalysis``.

    Only the first 1 000 rows are read for sampling; the full row count is
    still reported.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".xlsx", ".xls"):
        return _analyze_xlsx(file_path)

    return _analyze_csv(file_path)


def _analyze_xlsx(file_path: str) -> FileAnalysis:
    df = pd.read_excel(file_path, nrows=1000)
    full_rows = _count_xlsx_rows(file_path)

    return _build_analysis(
        file_path=file_path,
        df=df,
        total_rows=full_rows,
        file_type="xlsx",
        encoding="n/a",
        delimiter=None,
    )


def _count_xlsx_rows(file_path: str) -> int:
    try:
        df = pd.read_excel(file_path)
        return len(df)
    except Exception:
        return 0


def _analyze_csv(file_path: str) -> FileAnalysis:
    encoding, delimiter = _sniff_csv(file_path)

    try:
        df = pd.read_csv(
            file_path,
            encoding=encoding,
            sep=delimiter,
            nrows=1000,
            quoting=csv.QUOTE_MINIMAL,
            on_bad_lines="skip",
        )
    except Exception:
        # Last-resort fallback: UTF-8 with comma
        encoding = "utf-8"
        delimiter = ","
        df = pd.read_csv(
            file_path,
            encoding=encoding,
            sep=delimiter,
            nrows=1000,
            on_bad_lines="skip",
        )

    total_rows = _count_csv_rows(file_path, encoding, delimiter)
    ext = os.path.splitext(file_path)[1].lower()
    file_type = "tsv" if delimiter == "\t" or ext == ".tsv" else "csv"

    return _build_analysis(
        file_path=file_path,
        df=df,
        total_rows=total_rows,
        file_type=file_type,
        encoding=encoding,
        delimiter=delimiter,
    )


def _sniff_csv(file_path: str) -> tuple[str, str]:
    """Try encoding/delimiter combos and return the best pair."""
    for encoding in _ENCODING_CANDIDATES:
        try:
            with open(file_path, encoding=encoding) as fh:
                snippet = fh.read(8192)
        except (UnicodeDecodeError, LookupError):
            continue

        for delim in _DELIMITER_CANDIDATES:
            try:
                dialect = csv.Sniffer().sniff(snippet, delimiters=delim)
                return encoding, dialect.delimiter
            except Exception:
                # Sniffer failed with this delimiter – try a simple column
                # count heuristic.
                reader = csv.reader(io.StringIO(snippet), delimiter=delim)
                first = next(reader, [])
                if len(first) >= 2:
                    return encoding, delim
    return "utf-8", ","


def _count_csv_rows(file_path: str, encoding: str, delimiter: str) -> int:
    try:
        with open(file_path, encoding=encoding) as fh:
            return sum(1 for _ in fh) - 1  # subtract header
    except Exception:
        return 0


def _build_analysis(
    *,
    file_path: str,
    df: pd.DataFrame,
    total_rows: int,
    file_type: str,
    encoding: str,
    delimiter: str | None,
) -> FileAnalysis:
    columns = []
    for col_name in df.columns:
        col_name_str = str(col_name)
        series = df[col_name_str]
        sample_vals = series.dropna().head(5).astype(str).tolist()
        columns.append(
            ColumnInfo(
                name=col_name_str,
                dtype=str(series.dtype),
                non_null_count=int(series.notna().sum()),
                sample_values=sample_vals,
            )
        )

    sample_rows = df.head(5).to_dict(orient="records")

    suggested = suggest_column_mappings(df)

    return FileAnalysis(
        file_path=file_path,
        file_type=file_type,
        encoding=encoding,
        delimiter=delimiter,
        total_rows=total_rows,
        columns=columns,
        sample_rows=sample_rows,
        suggested_mapping=suggested,
    )


# ---------------------------------------------------------------------------
# Column-mapping heuristics
# ---------------------------------------------------------------------------


def suggest_column_mappings(df: pd.DataFrame) -> ColumnHeuristics:
    """Build a ``ColumnHeuristics`` by matching column names against keywords."""
    raw_names = [str(c) for c in df.columns]
    norm_map = {_normalize_name(n): n for n in raw_names}
    norm_names = list(norm_map.keys())

    def _match(keywords: list[str]) -> str | None:
        for kw in keywords:
            kw_norm = _normalize_name(kw)
            # 1. exact normalized match
            if kw_norm in norm_map:
                return norm_map[kw_norm]
            # 2. contains match (word-boundary aware)
            for nn in norm_names:
                if kw_norm in nn:
                    return norm_map[nn]
        return None

    return ColumnHeuristics(
        date_column=_match(_HEURISTIC_KEYWORDS["date"]),
        amount_column=_match(_HEURISTIC_KEYWORDS["amount"]),
        description_column=_match(_HEURISTIC_KEYWORDS["description"]),
        category_column=_match(_HEURISTIC_KEYWORDS["category"]),
        subcategory_column=_match(_HEURISTIC_KEYWORDS["subcategory"]),
        account_column=_match(_HEURISTIC_KEYWORDS["account"]),
        currency_column=_match(_HEURISTIC_KEYWORDS["currency"]),
        balance_account_column=_match(_HEURISTIC_KEYWORDS["balance_account"]),
        balance_value_column=_match(_HEURISTIC_KEYWORDS["balance_value"]),
    )


def _normalize_name(name: str) -> str:
    return " ".join(str(name).strip().lower().split())


# ---------------------------------------------------------------------------
# Data normalization
# ---------------------------------------------------------------------------


def normalize_date_series(series: pd.Series) -> pd.Series:
    """Parse *series* with multiple format attempts, return ``YYYY-MM-DD``."""

    def _parse(val: Any) -> str:
        if pd.isna(val):
            return ""
        s = str(val).strip()

        for fmt in _DATE_FORMATS:
            try:
                return dt.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

        try:
            ts = pd.to_datetime(s, errors="coerce")
            if pd.notna(ts):
                return ts.strftime("%Y-%m-%d")
        except Exception:
            logger.debug("Failed to coerce date value: %s", s)

        return ""

    return series.apply(_parse)


def normalize_amount_series(series: pd.Series) -> pd.Series:
    """Clean *series* into floats.

    Handles currency symbols, parenthetical negatives, and both
    US (1,234.56) and European (1.234,56) number formats.
    """

    def _clean(val: Any) -> float | None:
        if pd.isna(val):
            return None
        s = str(val).strip()
        if not s:
            return None

        negative = False

        # Parenthetical negatives: (123.45)
        if s.startswith("(") and s.endswith(")"):
            negative = True
            s = s[1:-1]

        # Trailing minus / CR suffix
        if s.endswith("-"):
            negative = True
            s = s[:-1]
        s = s.removesuffix("CR").removesuffix("cr").strip()

        # Strip common currency symbols / prefixes.
        for sym in ["$", "€", "£", "¥", "₪", "₹", "₩", "R$", "RM", "Rp"]:
            s = s.replace(sym, "")
        s = s.strip()

        # Detect European format: period as thousands-sep + comma as decimal.
        # Heuristic: if comma is present and period is also present, check
        # which is last and which has exactly 2 digits after it.
        if "," in s and "." in s:
            last_comma = s.rfind(",")
            last_dot = s.rfind(".")
            if last_comma > last_dot:
                # likely European: 1.234,56 → remove dots, comma → dot
                s = s.replace(".", "").replace(",", ".")
            else:
                # likely US: 1,234.56 → remove commas
                s = s.replace(",", "")
        elif "," in s:
            # Single separator — could be decimal or thousands.
            # If 3-digit group after comma → thousands; else decimal.
            parts = s.rsplit(",", 1)
            if len(parts) == 2 and len(parts[1]) == 2 and "." not in s:
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")

        try:
            value = float(s)
        except ValueError:
            return None

        return -value if negative else value

    return series.apply(_clean)


def normalize_currency_series(series: pd.Series) -> pd.Series:
    """Map currency codes/symbols to ISO 4217 three-letter codes."""

    def _map(val: Any) -> str:
        if pd.isna(val):
            return _UNKNOWN
        key = str(val).strip().lower()
        mapped = _CURRENCY_SYMBOL_MAP.get(key)
        if mapped:
            return mapped
        if len(key) == 3 and key.isalpha():
            upper = key.upper()
            if upper in _KNOWN_ISO_CODES:
                return upper
        return _UNKNOWN

    return series.apply(_map)


_KNOWN_ISO_CODES = frozenset(
    {
        "USD",
        "EUR",
        "CNY",
        "GBP",
        "ILS",
        "KRW",
        "INR",
        "JPY",
        "CHF",
        "AUD",
        "CAD",
        "SGD",
        "HKD",
        "TWD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "BGN",
        "HRK",
        "RSD",
        "UAH",
        "TRY",
        "BRL",
        "MXN",
        "ARS",
        "CLP",
        "COP",
        "PEN",
        "ZAR",
        "NGN",
        "KES",
        "EGP",
        "SAR",
        "AED",
        "THB",
        "VND",
        "IDR",
        "MYR",
        "PHP",
    }
)


def generate_unique_ids(
    account_series: pd.Series,
    date_series: pd.Series,
    amount_series: pd.Series,
    description_series: pd.Series,
) -> list[str]:
    """Generate deterministic MD5-based dedup keys (same algorithm as MoneyWiz)."""
    ids: list[str] = []
    for i in range(len(account_series)):
        seed = (
            f"{_safe_str(account_series.iloc[i])}-"
            f"{_safe_str(date_series.iloc[i])}-"
            f"{_safe_str(amount_series.iloc[i])}-"
            f"{_safe_str(description_series.iloc[i])}-"
            f"{i}"
        )
        ids.append(hashlib.md5(seed.encode(), usedforsecurity=False).hexdigest())
    return ids


def _is_numeric(value: Any) -> bool:
    """Return True when *value* can be parsed as a non-empty float."""
    if pd.isna(value):
        return False
    s = str(value).strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _safe_str(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value)


# ---------------------------------------------------------------------------
# Core cleaning pipeline
# ---------------------------------------------------------------------------


def clean_dataframe(
    df: pd.DataFrame,
    mapping: ColumnHeuristics,
    category_delimiter: str | None = None,
) -> tuple[list[Transaction], list[AccountBalance]]:
    """Apply *mapping* to *df* and return (transactions, balances)."""
    balances = _extract_balances(df, mapping)
    tx_mask = _build_transaction_mask(df, mapping)
    tx_df = df[tx_mask].copy()

    if tx_df.empty:
        return [], balances

    tx_df = _apply_column_mapping(tx_df, mapping)
    tx_df = _normalize_transaction_fields(tx_df)
    tx_df = _split_categories(tx_df, category_delimiter)

    ids = generate_unique_ids(
        account_series=tx_df.get(_ACCOUNT_NAME, pd.Series([""] * len(tx_df))),
        date_series=tx_df.get(_TXN_DATE, pd.Series([""] * len(tx_df))),
        amount_series=tx_df.get(_AMOUNT, pd.Series([0] * len(tx_df))),
        description_series=tx_df.get(_DESCRIPTION, pd.Series([""] * len(tx_df))),
    )

    transactions: list[Transaction] = []
    for i in range(len(tx_df)):
        row = tx_df.iloc[i]
        date_str = str(row.get(_TXN_DATE, ""))
        try:
            txn_date = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, KeyError):
            txn_date = dt.date.today()

        transactions.append(
            Transaction(
                unique_id=ids[i],
                transaction_date=txn_date,
                amount=float(row.get(_AMOUNT, 0) or 0),
                currency=str(row.get(_CURRENCY, _UNKNOWN) or _UNKNOWN),
                primary_category=str(row.get(_PRIMARY_CAT, "") or ""),
                secondary_category=str(row.get(_SECONDARY_CAT, "") or ""),
                account_name=str(row.get(_ACCOUNT_NAME, _UNKNOWN) or _UNKNOWN),
            )
        )

    return transactions, balances


def _build_transaction_mask(df: pd.DataFrame, mapping: ColumnHeuristics) -> pd.Series:
    """Create a boolean mask for rows that are transactions (not balances)."""
    if not (mapping.balance_value_column and mapping.balance_account_column):
        return pd.Series(True, index=df.index)

    return ~df[mapping.balance_value_column].apply(_is_numeric)


def _extract_balances(
    df: pd.DataFrame, mapping: ColumnHeuristics
) -> list[AccountBalance]:
    """Extract ``AccountBalance`` objects from balance rows."""
    if not (mapping.balance_value_column and mapping.balance_account_column):
        return []

    bal_val_col = mapping.balance_value_column
    bal_acct_col = mapping.balance_account_column
    bal_currency_col = mapping.currency_column
    bal_mask = df[bal_val_col].apply(_is_numeric)
    balances: list[AccountBalance] = []

    for _, row in df[bal_mask].iterrows():
        balances.append(
            AccountBalance(
                account_name=str(row[bal_acct_col]),
                balance=float(row[bal_val_col]),
                currency=(
                    str(row[bal_currency_col])
                    if bal_currency_col and pd.notna(row.get(bal_currency_col))
                    else _UNKNOWN
                ),
            )
        )

    return balances


def _apply_column_mapping(
    tx_df: pd.DataFrame, mapping: ColumnHeuristics
) -> pd.DataFrame:
    """Rename source columns to canonical names."""
    rename_map: dict[str, str] = {}
    if mapping.date_column:
        rename_map[mapping.date_column] = _TXN_DATE
    if mapping.amount_column:
        rename_map[mapping.amount_column] = _AMOUNT
    if mapping.currency_column:
        rename_map[mapping.currency_column] = _CURRENCY
    if mapping.account_column:
        rename_map[mapping.account_column] = _ACCOUNT_NAME
    if mapping.description_column:
        rename_map[mapping.description_column] = _DESCRIPTION
    if mapping.category_column:
        rename_map[mapping.category_column] = _CATEGORY_RAW
    tx_df.rename(columns=rename_map, inplace=True)
    return tx_df


def _normalize_transaction_fields(tx_df: pd.DataFrame) -> pd.DataFrame:
    """Apply date, amount, and currency normalizers in-place."""
    if _TXN_DATE in tx_df.columns:
        tx_df[_TXN_DATE] = normalize_date_series(tx_df[_TXN_DATE])
    else:
        tx_df[_TXN_DATE] = ""

    if _AMOUNT in tx_df.columns:
        tx_df[_AMOUNT] = normalize_amount_series(tx_df[_AMOUNT])
    else:
        tx_df[_AMOUNT] = 0.0

    if _CURRENCY in tx_df.columns:
        tx_df[_CURRENCY] = normalize_currency_series(tx_df[_CURRENCY])
    else:
        tx_df[_CURRENCY] = _UNKNOWN

    if _ACCOUNT_NAME not in tx_df.columns:
        tx_df[_ACCOUNT_NAME] = _UNKNOWN

    return tx_df


def _split_categories(
    tx_df: pd.DataFrame, category_delimiter: str | None
) -> pd.DataFrame:
    """Split ``category_raw`` into primary/secondary category columns."""
    raw_cats = tx_df.get(_CATEGORY_RAW, pd.Series([""] * len(tx_df)))
    delim = category_delimiter or _detect_category_delimiter(raw_cats)

    primary_cat: list[str] = []
    secondary_cat: list[str] = []

    for val in raw_cats:
        s = str(val).strip() if pd.notna(val) else ""
        if delim and delim in s:
            p, sec = s.split(delim, 1)
            primary_cat.append(p.strip())
            secondary_cat.append(sec.strip())
        else:
            primary_cat.append(s)
            secondary_cat.append("")

    tx_df[_PRIMARY_CAT] = primary_cat
    tx_df[_SECONDARY_CAT] = secondary_cat
    return tx_df


def _detect_category_delimiter(raw_cats: pd.Series) -> str | None:
    """Heuristically detect the most common category delimiter in the series."""
    candidates = {d: 0 for d in _CATEGORY_DELIMITERS}
    for val in raw_cats.dropna().head(200):
        s = str(val)
        for delim in _CATEGORY_DELIMITERS:
            if delim in s:
                candidates[delim] += 1
    # mypy infers dict[str, int].__getitem__ as invariant on the key type.
    best = max(candidates, key=lambda k: candidates[k])  # type: ignore[type-var]
    return best if candidates[best] > 0 else None


# ---------------------------------------------------------------------------
# Convenience: format analysis as readable text
# ---------------------------------------------------------------------------


def format_analysis(analysis: FileAnalysis) -> str:
    """Render *analysis* as a human-readable summary string."""
    lines = [
        f"File: {analysis.file_path}",
        f"Type: {analysis.file_type} | Encoding: {analysis.encoding}"
        + (f" | Delimiter: {repr(analysis.delimiter)}" if analysis.delimiter else ""),
        f"Rows: {analysis.total_rows} | Columns: {len(analysis.columns)}",
        "",
        "Columns:",
    ]
    for ci in analysis.columns:
        samples = ", ".join((ci.sample_values or [])[:3])
        lines.append(
            f"  [{ci.dtype}] {ci.name}  "
            f"(non-null: {ci.non_null_count})  "
            f"samples: {samples}"
        )

    m = analysis.suggested_mapping
    lines.append("")
    lines.append("Suggested mapping:")
    for attr in (
        "date_column",
        "amount_column",
        "description_column",
        "category_column",
        "subcategory_column",
        "account_column",
        "currency_column",
        "balance_account_column",
        "balance_value_column",
    ):
        val = getattr(m, attr)
        label = attr.replace("_column", "").replace("_", " ")
        lines.append(f"  {label}: {val or '(not detected)'}")

    return "\n".join(lines)
