---
name: data-cleaner
description: Clean financial data from any accounting tool (YNAB, Mint, bank exports, custom spreadsheets) into Prospere's standard format. Supports CSV, TSV, XLSX.
---

# Data Cleaner

Transform raw financial data from any source into Prospere's standard input format:
- `processed_transactions.xlsx` (7 columns: `unique_id`, `transaction_date`, `amount`, `currency`, `primary_category`, `secondary_category`, `account_name`)
- `processed_balances.json` (array of `{account_name, balance, currency}`)

## Usage

```
/data-cleaner [file_path]
```

If no file path is provided, ask the user for one.

## Installation

Copy this file to `~/.claude/skills/` or your project's `.claude/skills/` directory:

```bash
mkdir -p ~/.claude/skills
cp skills/data-cleaner.md ~/.claude/skills/
```

## Prerequisites

This skill depends on Prospere being installed. Ensure the user has run `pip install prospere` or `uv sync` before using this skill.

Check availability:
```python
try:
    from prospere.ingestion.cleaner import analyze_file, clean_dataframe, suggest_column_mappings
    from prospere.ingestion.writer import write_dataset
    HAS_CLEANER = True
except ImportError:
    HAS_CLEANER = False
```

If `HAS_CLEANER` is False, tell the user to install Prospere first.

## Workflow

### Step 1: Analyze File

Call `analyze_file(file_path)` from `cleaner.py`. Present the `FileAnalysis` result:

1. File type, encoding, delimiter
2. Total row count and column count
3. All columns with types and sample values
4. Suggested column mapping from `suggest_column_mappings()`

### Step 2: Confirm Column Mapping

Present the suggested mapping and ask the user to confirm or adjust.

Read `_HEURISTIC_KEYWORDS` from `cleaner.py` for the canonical keyword lists used by `suggest_column_mappings()`. The matching priority is: exact > normalized exact > contains > prefix.

**Special cases**:
- **MoneyWiz format**: If `is_moneywiz_format()` returns True, tell the user their file is already in MoneyWiz format and suggest using the standard import flow (`uv run prospere` → Data Import).
- **Missing date column**: Stop and explain — date is required.
- **Missing amount column**: Stop and explain — amount is required.
- **Large files (>10,000 rows)**: Suggest processing a sample first.

The user may:
- Confirm auto-detected mappings
- Override specific column assignments
- Specify special formatting (e.g. "amount column has $ prefix with parentheses for negatives")
- Specify a category delimiter (e.g. `::` or `>`, used to split primary/subcategory)

### Step 3: Clean Data

Build a `ColumnHeuristics` with the confirmed mapping, then call `clean_dataframe(df, mapping)`.

```python
from prospere.ingestion.cleaner import ColumnHeuristics, clean_dataframe

mapping = ColumnHeuristics(
    date_column=user_confirmed_date_col,
    amount_column=user_confirmed_amount_col,
    # ... other fields
)

transactions, balances = clean_dataframe(df, mapping)
```

`clean_dataframe` returns `list[Transaction]` and `list[AccountBalance]` — the same types used by the MoneyWiz engine. Cleaning rules (`_DATE_FORMATS`, `_CATEGORY_DELIMITERS`, `_CURRENCY_SYMBOL_MAP`, `_KNOWN_ISO_CODES`) are all defined in `cleaner.py` source.

**Show cleaning summary**:
- Dates parsed
- Amounts normalized
- Currencies standardized
- Primary/secondary categories generated
- Balance records extracted (if any)
- Unique IDs generated

### Step 4: Write and Validate

Ask the user for output location — two options:
- **Option A**: Write to a Prospere workspace (ask for `user` and `snapshot` name)
- **Option B**: Write to a custom directory

Use the shared write pipeline:
```python
from prospere.ingestion.writer import write_dataset

success, msg = write_dataset(transactions, balances, xlsx_path, json_path)
```

For Option A, also copy into the workspace:
```python
from prospere.cli.process import import_preprocessed
success, msg = import_preprocessed(user, snapshot, xlsx_path, json_path)
```

**Report the final result**:
- "Cleaned X transactions and Y balances. Validation passed."
- Or show the specific validation failure.

### Step 5: Suggest Next Steps

- Run `prospere` to launch the TUI menu and start a simulation
- Use the bootstrap wizard to create a scenario based on this data

## Edge Cases

### Balances only, no transactions
`clean_dataframe` returns an empty transactions list. Tell the user balances are imported but a simulation requires transaction data for volatility computation.

### Encoding errors
`analyze_file` tries encodings in order: utf-8-sig → utf-8 → latin-1 → cp1252. If all fail, show the error and suggest the user check file integrity.

### Duplicate column matches
If multiple columns match the same standard field, list the conflict and ask the user to choose.

### Headerless files
If the file has no header row (columns are numeric indices), show the first 3 data rows and ask the user to name the columns.

### Inconsistent sign convention
Check the amount distribution: if most values are negative, the sign convention may be flipped — ask the user whether to negate all amounts.
