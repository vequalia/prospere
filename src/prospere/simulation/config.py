import json
import os
from typing import Any

import pandas as pd

from prospere.core.constants import (
    AccountType,
    ExchangeRates,
    FinancialRole,
    NecessityLevel,
    PathConfig,
    SimulationDefaults,
)


class CategoryConfigurationManager:
    """Manages roles and behavioral metadata for financial categories."""

    def __init__(self, file_path: str = PathConfig.CATEGORY_CONFIG):
        self.file_path = file_path
        self.registry: dict[str, Any] = {}

    def load_from_disk(self) -> None:
        """Loads configuration from disk. Raises FileNotFoundError if missing."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(
                f"Required configuration file missing: {self.file_path}"
            )
        with open(self.file_path, encoding="utf-8") as f:
            self.registry = json.load(f)

    def get_metadata(self, name: str) -> dict[str, Any]:
        """Returns complete metadata with guaranteed default values."""
        entry = self.registry.get(name, {})
        defaults = {
            "role": FinancialRole.IGNORE.value,
            "is_recurring": True,
            "flexibility_score": 3,
            "necessity_level": NecessityLevel.DISCRETIONARY.value,
            "annual_growth_rate": 0.0,
            "income_linked_rate": 0.0,
            "projected_values": None,
        }
        return {**defaults, **entry}


class AccountConfigurationManager:
    """Manages metadata, investment strategy and waterfall traits for accounts."""

    def __init__(self, file_path: str = PathConfig.ACCOUNT_CONFIG):
        self.file_path = file_path
        self.registry: dict[str, dict[str, Any]] = {}

    def load_from_disk(self) -> None:
        """Loads configuration from disk. Raises FileNotFoundError if missing."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(
                f"Required configuration file missing: {self.file_path}"
            )
        with open(self.file_path, encoding="utf-8") as f:
            self.registry = json.load(f)

    def save_to_disk(self) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.registry, f, indent=4, ensure_ascii=False)

    def _get_safe_defaults(
        self, account_type: str = AccountType.SAVINGS.value
    ) -> dict[str, Any]:
        """Returns fundamental safe defaults based on core type definitions."""
        defaults: dict[str, Any] = {
            "annual_return": SimulationDefaults.SAVINGS_RETURN_RATE,
            "annual_return_std": 0.0,
            "allocation_ratio": 0.0,
            "deposit_priority": SimulationDefaults.PRIORITY_SAVINGS_BUFFER,
            "max_balance": float("inf"),
        }

        if account_type == AccountType.CREDIT.value:
            defaults["deposit_priority"] = SimulationDefaults.PRIORITY_DEBT_REPAYMENT
            defaults["annual_return"] = 0.0  # Debts usually don't have positive returns
        elif account_type == AccountType.INVESTMENT.value:
            defaults["deposit_priority"] = (
                SimulationDefaults.PRIORITY_STANDARD_INVESTMENT
            )
            defaults["annual_return"] = SimulationDefaults.INVESTMENT_RETURN_RATE
            defaults["annual_return_std"] = SimulationDefaults.RETURN_STD_DEFAULT

        return defaults

    def get_account_metadata(self, account_name: str) -> dict[str, Any]:
        """Returns enriched metadata, ensuring NO missing fields for the engine."""
        entry = self.registry.get(account_name, {}).copy()

        account_type_raw = entry.get("account_type", AccountType.SAVINGS.value)
        if isinstance(account_type_raw, str):
            if account_type_raw.startswith("AccountType."):
                account_type_raw = account_type_raw.split(".", 1)[1].lower()
            account_type_raw = AccountType(account_type_raw)

        base_traits = self._get_safe_defaults(account_type_raw.value)

        result: dict[str, Any] = {
            "currency": ExchangeRates.BASE_CURRENCY,
            "initial_balance": 0.0,
            "account_type": account_type_raw,
            **base_traits,
            **entry,
        }
        if isinstance(result.get("account_type"), str):
            result["account_type"] = AccountType(result["account_type"])
        return result

    def bootstrap_from_dataset(
        self,
        historical_df: pd.DataFrame,
        initial_balances: dict[str, float] | None = None,
        currencies: dict[str, str] | None = None,
    ) -> None:
        """Initializes a clean registry from historical transaction data."""
        total_value_base = 0.0
        account_values_base = {}

        if initial_balances:
            for name, balance in initial_balances.items():
                currency = (currencies or {}).get(name, ExchangeRates.BASE_CURRENCY)
                exchange_rate = ExchangeRates.RATES.get(currency, 1.0)
                base_value = balance * exchange_rate
                account_values_base[name] = base_value
                total_value_base += base_value

        processed_names = set()

        for account_name in historical_df["account_name"].unique():
            if pd.isna(account_name):
                continue
            name_str = str(account_name)
            processed_names.add(name_str)
            allocation_ratio = (
                round(account_values_base.get(name_str, 0.0) / total_value_base, 4)
                if total_value_base > 0
                else 0.0
            )

            self.registry[name_str] = {
                "initial_balance": initial_balances.get(name_str, 0.0)
                if initial_balances
                else 0.0,
                "currency": (currencies or {}).get(
                    name_str, ExchangeRates.BASE_CURRENCY
                ),
                "allocation_ratio": allocation_ratio,
                "account_type": AccountType.SAVINGS.value,  # Default for new accounts
            }

        # Also process accounts in initial_balances that have no transactions
        if initial_balances:
            for name_str, balance in initial_balances.items():
                if name_str in processed_names:
                    continue
                currency = (currencies or {}).get(name_str, ExchangeRates.BASE_CURRENCY)
                exchange_rate = ExchangeRates.RATES.get(currency, 1.0)
                base_value = balance * exchange_rate
                allocation_ratio = (
                    round(base_value / total_value_base, 4)
                    if total_value_base > 0
                    else 0.0
                )
                self.registry[name_str] = {
                    "initial_balance": balance,
                    "currency": currency,
                    "allocation_ratio": allocation_ratio,
                    "account_type": AccountType.SAVINGS.value,
                }
