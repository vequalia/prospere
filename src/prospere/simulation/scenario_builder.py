import json
import os
import typing
from typing import Any

import numpy as np
import pandas as pd

from prospere.core.constants import (
    AccountType,
    AssetClass,
    ExchangeRates,
    FinancialRole,
    MLForecastingConfig,
    NecessityLevel,
    PathConfig,
    SimulationDefaults,
)


class ScenarioBuilder:
    """Generates scenario config files from transaction history with overrides."""

    def __init__(
        self,
        transactions_path: str = PathConfig.PROCESSED_TRANSACTIONS,
        balances_path: str = PathConfig.PROCESSED_BALANCES,
    ):
        """Initialize builder by loading processed data."""
        self.transactions = pd.read_excel(transactions_path)
        self.transactions["transaction_date"] = pd.to_datetime(
            self.transactions["transaction_date"]
        )
        self.transactions["month"] = self.transactions["transaction_date"].dt.to_period(
            "M"
        )
        self.unique_months = self.transactions["month"].unique()
        self.total_months_count = max(len(self.unique_months), 1)

        self.balances: dict[str, float] = {}
        self.currencies: dict[str, str] = {}
        self._load_balances(balances_path)

        self._detect_accounts()
        self._detect_categories()

        self.scenario: dict = self._create_default_scenario()
        self.update_initial_capital()  # Set proper initial capital with conversion
        self.account_overrides: dict[str, dict] = {}
        self.category_overrides: dict[str, dict] = {}
        self.taxable_income_categories: list[str] = []
        self.tax_categories: list[str] = []

    def get_category_metadata(self) -> list[dict[str, Any]]:
        """Calculates rich metadata for all detected categories for AI/CLI use."""
        metadata = []
        for category_name in self.detected_categories:
            subset = self.transactions[
                self.transactions["primary_category"] == category_name
            ].copy()
            total_flow = float(subset["amount"].sum())

            # Calculate recurrence: presence in more than 50% of months
            month_presence = subset["month"].nunique()
            stat_recurring = (
                month_presence / self.total_months_count
            ) > MLForecastingConfig.RECURRENCE_CONFIDENCE_THRESHOLD

            metadata.append(
                {
                    "name": category_name,
                    "net_flow": total_flow,
                    "avg_monthly": total_flow / self.total_months_count,
                    "stat_recurring": stat_recurring,
                    "sub_categories": self.sub_categories_map.get(category_name, []),
                }
            )
        return metadata

    def run_ml_forecasting(self, years: int) -> None:
        """Uses Prophet to forecast future values for all categories."""
        import logging

        logging.getLogger("prophet").setLevel(logging.ERROR)
        logging.getLogger("cmdstanpy").setLevel(logging.ERROR)

        months_to_forecast = years * SimulationDefaults.MONTHS_PER_YEAR
        target_currency = self.scenario.get("currency", ExchangeRates.BASE_CURRENCY)

        history = self.transactions.copy()

        def _to_target_currency(row: pd.Series) -> float:
            rate_from = ExchangeRates.RATES.get(row["currency"], 1.0)
            rate_to = ExchangeRates.RATES.get(target_currency, 1.0)
            return float(row["amount"] * (rate_from / rate_to))

        history["amount_norm"] = history.apply(_to_target_currency, axis=1)
        history["ds"] = history["transaction_date"].dt.to_period("M").dt.to_timestamp()

        for category_name in self.detected_categories:
            self._forecast_category(category_name, history, months_to_forecast)

    def _forecast_category(
        self,
        category_name: str,
        history: pd.DataFrame,
        months_to_forecast: int,
    ) -> None:
        """Forecasts only expense categories using high-fidelity seasonal extraction."""
        overrides = self.category_overrides.get(category_name, {})
        role = overrides.get("role", FinancialRole.EXPENSE.value)

        if role == FinancialRole.INCOME.value:
            return

        cat_history = history[history["primary_category"] == category_name]

        active_subs = self.sub_categories_map.get(category_name, [])
        for sub_name in active_subs:
            sub_history = cat_history[cat_history["secondary_category"] == sub_name]
            if not sub_history.empty:
                sub_monthly = (
                    sub_history.groupby("ds")["amount_norm"].sum().abs().reset_index()
                )
                sub_monthly.columns = pd.Index(["ds", "y"])

                if len(sub_monthly) >= SimulationDefaults.MIN_MONTHS_FOR_ML:
                    values = self._fit_predict_robust(
                        sub_monthly, sub_name, months_to_forecast
                    )
                    if values:
                        self.configure_sub_category(
                            category_name, sub_name, projected_values=values
                        )

        if not active_subs and not cat_history.empty:
            cat_monthly = (
                cat_history.groupby("ds")["amount_norm"].sum().abs().reset_index()
            )
            cat_monthly.columns = pd.Index(["ds", "y"])
            if len(cat_monthly) >= SimulationDefaults.MIN_MONTHS_FOR_ML:
                values = self._fit_predict_robust(
                    cat_monthly, category_name, months_to_forecast
                )
                if values:
                    self.configure_category(category_name, projected_values=values)

    def _fit_predict_robust(
        self, df: pd.DataFrame, entity_name: str, months_to_forecast: int
    ) -> list[float] | None:
        """Helper to fit Prophet with flat growth and high-fidelity seasonality."""
        from prophet import Prophet  # type: ignore

        try:
            non_zero = df[df["y"] > 0]
            if non_zero.empty:
                return None
            first_date = non_zero["ds"].min()

            full_range = pd.date_range(start=first_date, end=df["ds"].max(), freq="MS")
            data = (
                pd.DataFrame({"ds": full_range})
                .merge(df, on="ds", how="left")
                .fillna(0)
            )

            is_spike_prone = any(
                kw in entity_name.lower()
                for kw in MLForecastingConfig.SPIKE_SENSITIVE_KEYWORDS
            )
            median_y = data["y"].median()

            # Robust outlier clipping using Median Absolute Deviation
            if (
                data["y"] > 0
            ).mean() > MLForecastingConfig.RECURRENCE_CONFIDENCE_THRESHOLD:
                mad_y = (data["y"] - median_y).abs().median() or (median_y * 0.2 + 1.0)
                multiplier = (
                    MLForecastingConfig.OUTLIER_MAD_MULTIPLIER_SPIKE
                    if is_spike_prone
                    else MLForecastingConfig.OUTLIER_MAD_MULTIPLIER_NORMAL
                )
                clipping_limit = median_y + multiplier * mad_y
            else:
                clipping_limit = max(
                    np.percentile(data["y"], MLForecastingConfig.OUTLIER_PERCENTILE),
                    data["y"].max() * 0.9,
                )

            data["y"] = data["y"].clip(upper=clipping_limit)

            model = Prophet(
                growth=MLForecastingConfig.GROWTH_MODE,
                seasonality_mode=MLForecastingConfig.SEASONALITY_MODE,
                yearly_seasonality=False,
            )
            fourier_order = (
                MLForecastingConfig.FOURIER_ORDER_SPIKE
                if is_spike_prone
                else MLForecastingConfig.FOURIER_ORDER_NORMAL
            )
            model.add_seasonality(
                name="yearly", period=365.25, fourier_order=fourier_order
            )
            model.fit(data)

            future = model.make_future_dataframe(periods=months_to_forecast, freq="MS")
            forecast = model.predict(future)

            return [
                max(0.0, min(float(val), clipping_limit))
                for val in forecast.tail(months_to_forecast)["yhat"]
            ]
        except Exception as e:
            print(f"      ✗ ML Robust Forecast failed for {entity_name}: {e}")
            return None

    def _infer_account_type(self, account_name: str) -> str:
        """Heuristic for account type detection (fallback when AI is unavailable)."""
        balance = self.balances.get(account_name, 0.0)
        lower_name = account_name.lower()
        if any(kw in lower_name for kw in ("trade", "invest", "stocks", "equity")):
            return AccountType.INVESTMENT.value
        if balance < 0:
            return AccountType.CREDIT.value
        return AccountType.SAVINGS.value

    def _infer_account_return(self, account_name: str, account_type: str) -> float:
        """Heuristic for annual return based on account type."""
        if account_type in (AccountType.INVESTMENT.value, AccountType.INVESTMENT):
            name_lower = account_name.lower()
            if any(kw in name_lower for kw in ("etoro", "trade", "trading")):
                return 0.15
            if any(kw in name_lower for kw in ("pea", "cto")):
                return 0.10
            return SimulationDefaults.INVESTMENT_RETURN_RATE
        if account_type in (AccountType.SAVINGS.value, AccountType.SAVINGS):
            return SimulationDefaults.SAVINGS_RETURN_RATE
        if account_type in (AccountType.CASH.value, AccountType.CASH):
            return 0.0
        return 0.0

    def infer_asset_class(self, account_name: str, account_type: str) -> str:
        """Heuristic for asset class based on account type and name."""
        name_lower = account_name.lower()
        if account_type in (AccountType.SAVINGS.value, AccountType.SAVINGS):
            return AssetClass.SAVINGS.value
        if account_type in (AccountType.CASH.value, AccountType.CASH):
            return AssetClass.CASH.value
        if account_type in (AccountType.INVESTMENT.value, AccountType.INVESTMENT):
            if any(kw in name_lower for kw in ("assurance", "groupama", "av")):
                return AssetClass.MIXED.value
            return AssetClass.EQUITY.value
        return ""

    def _compute_net_worth_eur(self) -> float:
        """Calculates current net worth in the scenario's base currency."""
        target_currency = self.scenario.get("currency", ExchangeRates.BASE_CURRENCY)
        total = 0.0
        for name, balance in self.balances.items():
            curr = self.currencies.get(name, ExchangeRates.BASE_CURRENCY)

            # Convert: balance (curr) -> Base (EUR) -> target_currency
            rate_from = ExchangeRates.RATES.get(curr, 1.0)
            rate_to = ExchangeRates.RATES.get(target_currency, 1.0)

            total += balance * (rate_from / rate_to)
        return total

    def update_initial_capital(self) -> None:
        """Recalculates initial capital based on current balances and base currency."""
        self.scenario["initial_capital"] = self._compute_net_worth_eur()

    def configure_account(self, name: str, **overrides: typing.Any) -> None:
        """Apply custom settings to a specific account."""
        self.account_overrides.setdefault(name, {}).update(overrides)

    def configure_category(self, name: str, **overrides: typing.Any) -> None:
        """Apply custom settings to a specific category."""
        self.category_overrides.setdefault(name, {}).update(overrides)

    def configure_sub_category(
        self, category: str, sub_name: str, **overrides: typing.Any
    ) -> None:
        """Apply custom settings to a specific sub-category."""
        subs = self.category_overrides.setdefault(category, {}).setdefault(
            "sub_categories", {}
        )
        subs.setdefault(sub_name, {}).update(overrides)

    def apply_scope_filter(
        self,
        exclude_accounts: list[str] | None = None,
        exclude_categories: list[str] | None = None,
        exclude_sub_categories: list[tuple[str, str]] | None = None,
    ) -> None:
        """
        Permanently filters out specified accounts and categories from this session.
        Triggers re-detection of stats.
        """
        if exclude_accounts:
            self.transactions = self.transactions[
                ~self.transactions["account_name"].isin(exclude_accounts)
            ]
            for acc in exclude_accounts:
                self.balances.pop(acc, None)
                self.currencies.pop(acc, None)

        if exclude_categories:
            self.transactions = self.transactions[
                ~self.transactions["primary_category"].isin(exclude_categories)
            ]

        if exclude_sub_categories:
            for cat, sub in exclude_sub_categories:
                self.transactions = self.transactions[
                    ~(
                        (self.transactions["primary_category"] == cat)
                        & (self.transactions["secondary_category"] == sub)
                    )
                ]

        # Re-detect based on filtered data
        self._detect_accounts()
        self._detect_categories()
        # Update net worth using correct exchange rates
        self.update_initial_capital()

    def _calculate_annual_averages(
        self, df: pd.DataFrame, years: list[int]
    ) -> list[dict]:
        """Calculates normalized monthly averages for each year."""
        annual_avgs = []
        for yr in years:
            yr_df = df[df["year"] == yr]
            num_months = yr_df["month_idx"].nunique()
            if num_months == 0:
                continue
            inc_total = yr_df[yr_df["amount_eur"] > 0]["amount_eur"].sum()
            exp_total = abs(yr_df[yr_df["amount_eur"] < 0]["amount_eur"].sum())
            annual_avgs.append(
                {
                    "year": yr,
                    "avg_income": inc_total / num_months,
                    "avg_expense": exp_total / num_months,
                }
            )
        return annual_avgs

    def calculate_historical_growth_metrics(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """Analyzes YoY growth rates using normalized monthly averages per year."""
        df = self.transactions.copy()
        if start_date:
            df = df[df["transaction_date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["transaction_date"] <= pd.to_datetime(end_date)]

        def _to_base_currency(row: pd.Series) -> float:
            rate = ExchangeRates.RATES.get(row["currency"], 1.0)
            return float(row["amount"] * rate)

        df["amount_eur"] = df.apply(_to_base_currency, axis=1)
        df["year"] = df["transaction_date"].dt.year
        df["month_idx"] = df["transaction_date"].dt.to_period("M")

        years = sorted(df["year"].unique())
        if len(years) < 2:
            return {
                "income_growth": None,
                "expense_growth": None,
                "data_years": len(years),
            }

        annual_avgs = self._calculate_annual_averages(df, years)
        income_rates, expense_rates = [], []

        for i in range(1, len(annual_avgs)):
            prev, curr = annual_avgs[i - 1], annual_avgs[i]
            if prev["avg_income"] > 0:
                income_rates.append((curr["avg_income"] / prev["avg_income"]) - 1)
            if prev["avg_expense"] > 0:
                expense_rates.append((curr["avg_expense"] / prev["avg_expense"]) - 1)

        def _safe_mean(rates: list[float]) -> float | None:
            return float(np.mean(rates)) if rates else None

        return {
            "income_growth": _safe_mean(income_rates),
            "expense_growth": _safe_mean(expense_rates),
            "data_years": len(years),
            "span": len(annual_avgs) - 1,
            "yearly_details": {
                "income_steps": [round(r * 100, 1) for r in income_rates],
                "expense_steps": [round(r * 100, 1) for r in expense_rates],
            },
        }

    def calculate_baseline_audit(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> dict[str, Any]:
        """Calculates avg monthly income/expense for a specific window."""
        df = self.transactions.copy()
        if start_date:
            df = df[df["transaction_date"] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df["transaction_date"] <= pd.to_datetime(end_date)]

        unique_months = df["month"].unique()
        month_count = max(len(unique_months), 1)

        income_total = df[df["amount"] > 0]["amount"].sum()
        expense_total = df[df["amount"] < 0]["amount"].sum()

        target_currency = self.scenario.get("currency", ExchangeRates.BASE_CURRENCY)
        # Simplified conversion for audit display (using base rates)
        rate_to_base = ExchangeRates.RATES.get(target_currency, 1.0)

        return {
            "avg_income": float(income_total / month_count / rate_to_base),
            "avg_expense": float(abs(expense_total) / month_count / rate_to_base),
            "month_count": month_count,
            "start_date": str(df["transaction_date"].min().date())
            if not df.empty
            else None,
            "end_date": str(df["transaction_date"].max().date())
            if not df.empty
            else None,
        }

    def set_taxable_income(self, categories: list[str]) -> None:
        """Defines which income categories are taxable."""
        self.taxable_income_categories = categories

    def set_tax_categories(self, categories: list[str]) -> None:
        """Defines which expense categories are tax payments."""
        self.tax_categories = categories

    def set_estimated_effective_tax_rate(self, rate: float | None) -> None:
        """Sets an AI-estimated effective tax rate for post-tax income scenarios."""
        self.scenario["estimated_effective_tax_rate"] = rate

    def set_tax_rules(self, rules: list[dict]) -> None:
        """Sets the tax rules for capital gains and investment income."""
        self.scenario["tax_rules"] = rules

    def set_market_assumptions(self, market_assumptions: dict) -> None:
        """Sets market assumptions (correlations, mean reversion)."""
        self.scenario["market_assumptions"] = market_assumptions

    def set_snapshot_name(self, name: str) -> None:
        """Links this scenario to a specific dataset snapshot."""
        self.scenario["snapshot_name"] = name

    def set_scenario_field(self, field: str, value: typing.Any) -> None:
        """Updates a generic field in the scenario metadata."""
        self.scenario[field] = value

    def write(self, output_dir: str) -> dict[str, str]:
        """Persists the configurations to the specified directory."""
        os.makedirs(output_dir, exist_ok=True)

        scenario_path = os.path.join(output_dir, "scenario.json")
        category_config_path = os.path.join(output_dir, "category_config.json")
        account_config_path = os.path.join(output_dir, "account_config.json")

        # Sync attributes to scenario dict
        self.scenario["taxable_income_categories"] = self.taxable_income_categories
        self.scenario["tax_categories"] = self.tax_categories

        with open(scenario_path, "w", encoding="utf-8") as f:
            json.dump(self.scenario, f, indent=4, ensure_ascii=False)

        with open(category_config_path, "w", encoding="utf-8") as f:
            json.dump(self._build_categories_config(), f, indent=4, ensure_ascii=False)

        with open(account_config_path, "w", encoding="utf-8") as f:
            json.dump(self._build_accounts_config(), f, indent=4, ensure_ascii=False)

        return {
            "scenario": scenario_path,
            "category_config": category_config_path,
            "account_config": account_config_path,
        }

    def _load_balances(self, balances_path: str) -> None:
        """Loads account balances and currencies from processed JSON."""
        if not os.path.exists(balances_path):
            return

        with open(balances_path, encoding="utf-8") as f:
            data = json.load(f)
            for acc in data:
                name = acc["account_name"]
                self.balances[name] = acc["balance"]
                self.currencies[name] = acc.get("currency", ExchangeRates.BASE_CURRENCY)

    def _detect_accounts(self) -> None:
        """Identifies unique accounts from both transactions and balance records."""
        txn_accounts = set(self.transactions["account_name"].unique())
        bal_accounts = set(self.balances.keys())
        self.detected_accounts = sorted(list(txn_accounts | bal_accounts))

    def _detect_categories(self) -> None:
        """Identifies unique primary and secondary categories."""
        self.detected_categories = (
            self.transactions["primary_category"].unique().tolist()
        )
        self.sub_categories_map = {}
        for cat in self.detected_categories:
            subs = (
                self.transactions[self.transactions["primary_category"] == cat][
                    "secondary_category"
                ]
                .unique()
                .tolist()
            )
            self.sub_categories_map[cat] = subs

    def _create_default_scenario(self) -> dict:
        """Generates a base scenario metadata dictionary."""
        return {
            "name": "my_scenario",
            "initial_capital": 0.0,
            "years": SimulationDefaults.YEARS,
            "iterations": SimulationDefaults.ITERATIONS,
            "currency": ExchangeRates.BASE_CURRENCY,
            "start_date": str(self.transactions["transaction_date"].min().date()),
            "end_date": str(self.transactions["transaction_date"].max().date()),
            "growth_policy": {
                "default_income_growth": SimulationDefaults.DEFAULT_INCOME_GROWTH,
                "default_expense_growth": SimulationDefaults.DEFAULT_EXPENSE_GROWTH,
                "inflation_rate": SimulationDefaults.DEFAULT_INFLATION_RATE,
            },
            "taxable_income_categories": [],
            "tax_categories": [],
            "snapshot_name": "default",
        }

    def _build_accounts_config(self) -> dict:
        """Generates accounts config with automatic allocation ratios."""
        accounts_config = {}
        total_worth_base = self._compute_net_worth_eur()

        for name in self.detected_accounts:
            balance = self.balances.get(name, 0.0)
            currency = self.currencies.get(name, ExchangeRates.BASE_CURRENCY)

            # Calculate base value for this account to determine its allocation share
            rate_from = ExchangeRates.RATES.get(currency, 1.0)
            account_value_base = balance * rate_from

            # Auto-calculate ratio (clamped to 4 decimals)
            auto_ratio = (
                round(account_value_base / total_worth_base, 4)
                if total_worth_base > 0
                else 0.0
            )

            # Heuristics
            inferred_type = self._infer_account_type(name)
            inferred_return = self._infer_account_return(name, inferred_type)

            # Safe defaults matching AccountConfigurationManager._get_safe_defaults
            if inferred_type == AccountType.INVESTMENT.value:
                std = SimulationDefaults.RETURN_STD_DEFAULT
                prio = SimulationDefaults.PRIORITY_STANDARD_INVESTMENT
            elif inferred_type == AccountType.CREDIT.value:
                std = 0.0
                prio = SimulationDefaults.PRIORITY_DEBT_REPAYMENT
            else:
                std = 0.0
                prio = SimulationDefaults.PRIORITY_SAVINGS_BUFFER

            entry = {
                "account_type": inferred_type,
                "annual_return": inferred_return,
                "annual_return_std": std,
                "allocation_ratio": auto_ratio,
                "deposit_priority": prio,
                "initial_balance": balance,
                "currency": currency,
            }

            # Apply overrides
            overrides = self.account_overrides.get(name, {})
            accounts_config[name] = {**entry, **overrides}

        return accounts_config

    def _build_categories_config(self) -> dict:
        """Generates the category configuration dictionary."""
        categories_config = {}
        for category_name in self.detected_categories:
            overrides = self.category_overrides.get(category_name, {})
            role = overrides.get("role", FinancialRole.EXPENSE.value)

            subcategories_data = {}
            for sub_name in self.sub_categories_map.get(category_name, []):
                sub_overrides = overrides.get("sub_categories", {}).get(sub_name, {})
                subcategories_data[sub_name] = {
                    "is_recurring": sub_overrides.get("is_recurring", False),
                    "flexibility_score": sub_overrides.get("flexibility_score", 3),
                    "necessity_level": sub_overrides.get(
                        "necessity_level", NecessityLevel.DISCRETIONARY.value
                    ),
                }
                if "annual_growth_rate" in sub_overrides:
                    subcategories_data[sub_name]["annual_growth_rate"] = sub_overrides[
                        "annual_growth_rate"
                    ]
                if "income_linked_rate" in sub_overrides:
                    subcategories_data[sub_name]["income_linked_rate"] = sub_overrides[
                        "income_linked_rate"
                    ]
                if "projected_values" in sub_overrides:
                    subcategories_data[sub_name]["projected_values"] = sub_overrides[
                        "projected_values"
                    ]

            category_entry = {
                "role": role,
                "is_recurring": overrides.get("is_recurring", False),
                "flexibility_score": overrides.get("flexibility_score", 3),
                "necessity_level": overrides.get(
                    "necessity_level", NecessityLevel.DISCRETIONARY.value
                ),
            }
            if "annual_growth_rate" in overrides:
                category_entry["annual_growth_rate"] = overrides["annual_growth_rate"]
            if "income_linked_rate" in overrides:
                category_entry["income_linked_rate"] = overrides["income_linked_rate"]
            if "projected_values" in overrides:
                category_entry["projected_values"] = overrides["projected_values"]
            if subcategories_data:
                category_entry["sub_categories"] = subcategories_data

            categories_config[category_name] = category_entry
        return categories_config
