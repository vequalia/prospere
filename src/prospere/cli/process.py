import argparse
import logging
import os
import shutil

from prospere.core.constants import WorkspaceConfig
from prospere.core.models import WorkspaceContext
from prospere.core.workspace import WorkspaceManager
from prospere.ingestion.engine import IngestionEngineFactory
from prospere.ingestion.validation import (
    validate_balances_json,
    validate_transactions_xlsx,
)
from prospere.ingestion.writer import write_dataset

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def ingest_moneywiz(user: str, snapshot: str, csv_path: str) -> tuple[bool, str]:
    """Parse a MoneyWiz CSV and write processed files to the user's dataset.

    Returns:
        (success, message).  On failure the message explains why.
    """
    if not os.path.exists(csv_path):
        return False, f"File not found: {csv_path}"

    try:
        engine = IngestionEngineFactory.create_engine("moneywiz")
    except ValueError as err:
        return False, f"Engine initialization failed: {err}"

    transactions, balances = engine.parse_data(csv_path)

    if not transactions and not balances:
        return False, "No transactions or balances found in the file."

    ws = WorkspaceManager(WorkspaceContext(user=user, snapshot=snapshot))
    ws.ensure_structure()
    os.makedirs(ws.get_dataset_dir(), exist_ok=True)

    success, msg = write_dataset(
        transactions,
        balances,
        ws.get_dataset_path(WorkspaceConfig.PROCESSED_TX_FILENAME),
        ws.get_dataset_path(WorkspaceConfig.PROCESSED_BAL_FILENAME),
    )
    if not success:
        return False, msg
    return True, f"Imported {len(transactions)} transactions, {len(balances)} balances"


def import_preprocessed(
    user: str, snapshot: str, xlsx_path: str, json_path: str
) -> tuple[bool, str]:
    """Validate pre-processed XLSX + JSON files and copy them into the user's dataset.

    Returns:
        (success, message).
    """
    valid, msg = validate_transactions_xlsx(xlsx_path)
    if not valid:
        return False, f"XLSX validation failed: {msg}"

    valid, msg = validate_balances_json(json_path)
    if not valid:
        return False, f"JSON validation failed: {msg}"

    ws = WorkspaceManager(WorkspaceContext(user=user, snapshot=snapshot))
    ws.ensure_structure()
    os.makedirs(ws.get_dataset_dir(), exist_ok=True)

    try:
        shutil.copy2(
            xlsx_path, ws.get_dataset_path(WorkspaceConfig.PROCESSED_TX_FILENAME)
        )
        shutil.copy2(
            json_path, ws.get_dataset_path(WorkspaceConfig.PROCESSED_BAL_FILENAME)
        )
    except OSError as e:
        return False, f"Failed to copy files: {e}"

    return True, f"Files copied to dataset '{snapshot}'"


def run_ingestion_pipeline() -> None:
    """CLI entry point for data ingestion (backward-compatible)."""
    parser = argparse.ArgumentParser(description="Prospere Data Ingestion")
    parser.add_argument("--user", type=str, default="default_user")
    parser.add_argument("--snapshot", type=str, default="default")
    parser.add_argument("--input", type=str, default=None)
    args = parser.parse_args()

    csv_path = args.input
    if csv_path is None:
        ws = WorkspaceManager(WorkspaceContext(user=args.user))
        csv_path = os.path.join(ws.get_raw_dir(), WorkspaceConfig.RAW_CSV_FILENAME)

    success, msg = ingest_moneywiz(args.user, args.snapshot, csv_path)
    if success:
        logger.info(msg)
    else:
        logger.error(msg)


if __name__ == "__main__":
    run_ingestion_pipeline()
