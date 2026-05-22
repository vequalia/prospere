import logging

import numpy as np
import pandas as pd

from prospere.core.constants import ExchangeRates, FinancialRole
from prospere.simulation.config import (
    AccountConfigurationManager,
    CategoryConfigurationManager,
)
from prospere.simulation.models import (
    AccountStats,
    CategoryStats,
    FinancialProfile,
    NecessityLevel,
    SubCategoryStats,
)

logger = logging.getLogger(__name__)


class HistoricalDataAnalyzer:
    """Extracts behavioral financial patterns from transaction history."""

    def __init__(self, excel_file_path: str):
        self.excel_file_path = excel_file_path

    def _normalize_transactions(
        self,
        df_raw: pd.DataFrame,
        base_currency: str,
        start_date: str | None,
        end_date: str | None,
    ) -> pd.DataFrame:
        """
        Filters and normalizes transactions by date and converts to base currency.
        """
        df = df_raw.copy()
        df["transaction_date"] = pd.to_datetime(df["transaction_date"])

        if start_date:
            df = df[df["transaction_date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["transaction_date"] <= pd.to_datetime(end_date)]

        if df.empty:
            logger.warning(f"No transactions found in range {start_date} to {end_date}")
            raise ValueError("No transactions found in specified date range.")

        # Normalize currency to base
        rates = ExchangeRates.RATES
        if base_currency not in rates:
            raise ValueError(f"Unsupported base currency: {base_currency}")

        def convert_amount(row: pd.Series) -> float:
            currency = row["currency"]
            if currency not in rates:
                raise ValueError(f"Unsupported transaction currency: {currency}")

            if currency == base_currency:
                return float(row["amount"])
            return float(row["amount"] * rates[currency])

        df["amount"] = df.apply(convert_amount, axis=1)
        return df

    def construct_financial_profile(
        self,
        currency: str = ExchangeRates.BASE_CURRENCY,
        start_date: str | None = None,
        end_date: str | None = None,
        category_config: CategoryConfigurationManager | None = None,
        account_config: AccountConfigurationManager | None = None,
    ) -> FinancialProfile:
        """Builds a statistical profile using historical data and configs."""
        transactions_dataframe = self._normalize_transactions(
            pd.read_excel(self.excel_file_path), currency, start_date, end_date
        )
        transactions_dataframe["month"] = transactions_dataframe[
            "transaction_date"
        ].dt.to_period("M")
        num_months = len(transactions_dataframe["month"].unique()) or 1

        category_manager = category_config or CategoryConfigurationManager()
        account_manager = account_config or AccountConfigurationManager()

        category_stats_list = []
        monthly_income_sum, monthly_expense_sum = 0.0, 0.0

        for category_name in transactions_dataframe["primary_category"].unique():
            metadata = category_manager.get_metadata(str(category_name))
            if metadata["role"] == FinancialRole.IGNORE.value:
                continue

            category_subset = transactions_dataframe[
                transactions_dataframe["primary_category"] == category_name
            ]

            # Use mean of monthly sums to handle recurring patterns
            monthly_sums = category_subset.groupby("month")["amount"].sum()
            mean_value = abs(float(category_subset["amount"].sum() / num_months))
            std_deviation = float(monthly_sums.std()) if num_months > 1 else 0.0

            if metadata["role"] == FinancialRole.INCOME.value:
                monthly_income_sum += mean_value
            else:
                monthly_expense_sum += mean_value

            # Build sub-category stats from config and transaction data
            sub_stats_list = []
            for sub_name, sub_meta in metadata.get("sub_categories", {}).items():
                sub_subset = category_subset[
                    category_subset["secondary_category"] == sub_name
                ]
                if sub_subset.empty:
                    continue
                sub_monthly = sub_subset.groupby("month")["amount"].sum()
                sub_mean = abs(float(sub_subset["amount"].sum() / num_months))
                sub_std = float(sub_monthly.std()) if num_months > 1 else 0.0
                sub_stats_list.append(
                    SubCategoryStats(
                        name=sub_name,
                        mean=sub_mean,
                        std=sub_std,
                        is_income=(metadata["role"] == FinancialRole.INCOME.value),
                        is_recurring=sub_meta.get("is_recurring", False),
                        flexibility_score=sub_meta.get("flexibility_score", 3),
                        necessity_level=NecessityLevel(
                            sub_meta.get(
                                "necessity_level", NecessityLevel.DISCRETIONARY.value
                            )
                        ),
                        annual_growth_rate=sub_meta.get("annual_growth_rate"),
                        income_linked_rate=sub_meta.get("income_linked_rate"),
                        shock_events=sub_meta.get("shock_events", []),
                        projected_values=sub_meta.get("projected_values"),
                    )
                )

            category_stats_list.append(
                CategoryStats(
                    name=str(category_name),
                    mean=mean_value,
                    std=std_deviation,
                    is_income=(metadata["role"] == FinancialRole.INCOME.value),
                    is_recurring=metadata["is_recurring"],
                    flexibility_score=metadata["flexibility_score"],
                    necessity_level=NecessityLevel(metadata["necessity_level"]),
                    annual_growth_rate=metadata["annual_growth_rate"],
                    income_linked_rate=metadata["income_linked_rate"],
                    shock_events=metadata.get("shock_events", []),
                    sub_categories=sub_stats_list,
                    projected_values=metadata.get("projected_values"),
                )
            )

        # Compute actual monthly std deviations for income and expense
        income_cats = set(
            category.name for category in category_stats_list if category.is_income
        )
        monthly_income_values = []
        monthly_expense_values = []
        for _, group in transactions_dataframe.groupby("month"):
            income_sum = group[group["primary_category"].isin(income_cats)][
                "amount"
            ].sum()
            expense_sum = group[~group["primary_category"].isin(income_cats)][
                "amount"
            ].sum()
            monthly_income_values.append(income_sum)
            monthly_expense_values.append(expense_sum)

        monthly_income_std = (
            float(np.std(monthly_income_values))
            if len(monthly_income_values) > 1
            else 0.0
        )
        monthly_expense_std = (
            float(np.std(monthly_expense_values))
            if len(monthly_expense_values) > 1
            else 0.0
        )

        account_stats_list = self._build_account_stats(
            transactions_dataframe, account_manager, num_months, currency
        )

        return FinancialProfile(
            monthly_income_mean=monthly_income_sum,
            monthly_income_std=monthly_income_std,
            monthly_expense_mean=monthly_expense_sum,
            monthly_expense_std=monthly_expense_std,
            currency=currency,
            categories=category_stats_list,
            accounts=account_stats_list,
        )

    def _build_account_stats(
        self,
        transactions_dataframe: pd.DataFrame,
        account_manager: AccountConfigurationManager,
        num_months: int,
        base_currency: str,
    ) -> list[AccountStats]:
        """Maps physical transactions and metadata into unified AccountStats objects."""
        monthly_flows = transactions_dataframe.groupby(["account_name", "month"])[
            "amount"
        ].sum()
        account_stats_results = []

        all_account_names = set(transactions_dataframe["account_name"].unique()) | set(
            account_manager.registry.keys()
        )

        for name in all_account_names:
            if pd.isna(name):
                continue
            account_metadata = account_manager.get_account_metadata(str(name))

            mean_net_flow = (
                float(monthly_flows.loc[name].sum() / num_months)
                if name in monthly_flows.index
                else 0.0
            )

            # Convert initial balance to base currency
            initial_balance_raw = account_metadata.get("initial_balance", 0.0)
            account_currency = account_metadata.get(
                "currency", ExchangeRates.BASE_CURRENCY
            )

            rates = ExchangeRates.RATES
            initial_balance_base = (
                initial_balance_raw * rates.get(account_currency, 1.0)
                if account_currency != base_currency
                else initial_balance_raw
            )

            account_stats_results.append(
                AccountStats(
                    name=str(name),
                    account_type=account_metadata["account_type"],
                    annual_return=account_metadata["annual_return"],
                    monthly_net_flow_mean=mean_net_flow,
                    monthly_net_flow_std=0.0,
                    allocation_ratio=account_metadata["allocation_ratio"],
                    annual_return_std=account_metadata["annual_return_std"],
                    max_balance=account_metadata["max_balance"],
                    deposit_priority=account_metadata["deposit_priority"],
                    initial_balance=initial_balance_base,
                    currency=account_currency,
                    asset_class=account_metadata.get("asset_class", ""),
                )
            )
        return account_stats_results
