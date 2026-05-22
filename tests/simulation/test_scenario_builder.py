import json
import os
import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from prospere.core.constants import AccountType, FinancialRole
from prospere.simulation.scenario_builder import ScenarioBuilder


def _make_test_transactions(years: int = 2) -> pd.DataFrame:
    data = []
    month_counter = 0
    for yr_offset in range(years):
        for m in range(12):
            month_counter += 1
            ts = pd.Timestamp(f"{2020 + yr_offset}-{m + 1:02d}-15")
            data.append(
                {
                    "unique_id": f"txn_{month_counter}",
                    "transaction_date": ts,
                    "amount": 5000.0,
                    "currency": "EUR",
                    "primary_category": "Salary",
                    "secondary_category": "",
                    "account_name": "Checking",
                }
            )
            data.append(
                {
                    "unique_id": f"txn_r_{month_counter}",
                    "transaction_date": ts,
                    "amount": -1500.0,
                    "currency": "EUR",
                    "primary_category": "Rent",
                    "secondary_category": "",
                    "account_name": "Checking",
                }
            )
            data.append(
                {
                    "unique_id": f"txn_f_{month_counter}",
                    "transaction_date": ts,
                    "amount": -300.0,
                    "currency": "EUR",
                    "primary_category": "Food",
                    "secondary_category": "Groceries",
                    "account_name": "Checking",
                }
            )
    return pd.DataFrame(data)


class TestScenarioBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()
        self.txn_path = os.path.join(self.tmp_dir.name, "transactions.xlsx")
        self.bal_path = os.path.join(self.tmp_dir.name, "balances.json")

        df = _make_test_transactions()
        df.to_excel(self.txn_path, index=False)

        balances = [{"account_name": "Checking", "balance": 15000.0, "currency": "EUR"}]
        with open(self.bal_path, "w", encoding="utf-8") as f:
            json.dump(balances, f)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _make_builder(self) -> ScenarioBuilder:
        return ScenarioBuilder(
            transactions_path=self.txn_path,
            balances_path=self.bal_path,
        )

    def test_init_loads_transactions_and_balances(self) -> None:
        builder = self._make_builder()
        self.assertIn("Checking", builder.detected_accounts)
        self.assertIn("Salary", builder.detected_categories)
        self.assertIn("Rent", builder.detected_categories)
        self.assertIn("Food", builder.detected_categories)
        self.assertEqual(builder.balances["Checking"], 15000.0)

    def test_get_category_metadata(self) -> None:
        builder = self._make_builder()
        metadata = builder.get_category_metadata()

        salary = next(m for m in metadata if m["name"] == "Salary")
        self.assertGreater(salary["net_flow"], 0)
        self.assertGreater(salary["avg_monthly"], 0)
        self.assertTrue(salary["stat_recurring"])

    def test_calculate_baseline_audit(self) -> None:
        builder = self._make_builder()
        audit = builder.calculate_baseline_audit()

        self.assertAlmostEqual(audit["avg_income"], 5000.0, delta=100)
        self.assertAlmostEqual(audit["avg_expense"], 1800.0, delta=100)
        self.assertEqual(audit["month_count"], 24)

    def test_calculate_historical_growth_metrics(self) -> None:
        builder = self._make_builder()
        metrics = builder.calculate_historical_growth_metrics()

        self.assertIsNotNone(metrics["income_growth"])
        self.assertIsNotNone(metrics["expense_growth"])
        self.assertEqual(metrics["data_years"], 2)
        self.assertEqual(metrics["span"], 1)
        self.assertIn("yearly_details", metrics)

    def test_calculate_historical_growth_insufficient_data(self) -> None:
        df = _make_test_transactions(years=1)
        df.to_excel(self.txn_path, index=False)
        builder = self._make_builder()

        metrics = builder.calculate_historical_growth_metrics()
        self.assertIsNone(metrics["income_growth"])
        self.assertIsNone(metrics["expense_growth"])
        self.assertEqual(metrics["data_years"], 1)

    def test_apply_scope_filter_accounts(self) -> None:
        # Add a second account
        df = _make_test_transactions()
        df.loc[0, "account_name"] = "CreditCard"
        df["account_name"] = df["account_name"].replace("Checking", "Checking")

        txn_path2 = os.path.join(self.tmp_dir.name, "transactions2.xlsx")
        df.to_excel(txn_path2, index=False)

        balances = [
            {"account_name": "Checking", "balance": 15000.0, "currency": "EUR"},
            {"account_name": "CreditCard", "balance": -2000.0, "currency": "EUR"},
        ]
        with open(self.bal_path, "w", encoding="utf-8") as f:
            json.dump(balances, f)

        builder = ScenarioBuilder(
            transactions_path=txn_path2, balances_path=self.bal_path
        )
        self.assertIn("CreditCard", builder.detected_accounts)

        builder.apply_scope_filter(exclude_accounts=["CreditCard"])
        self.assertNotIn("CreditCard", builder.detected_accounts)
        self.assertNotIn("CreditCard", builder.balances)
        self.assertIn("Checking", builder.detected_accounts)

    def test_apply_scope_filter_categories(self) -> None:
        builder = self._make_builder()
        builder.apply_scope_filter(exclude_categories=["Food"])
        self.assertNotIn("Food", builder.detected_categories)
        self.assertIn("Salary", builder.detected_categories)
        self.assertIn("Rent", builder.detected_categories)

    def test_configure_account(self) -> None:
        builder = self._make_builder()
        builder.configure_account(
            "Checking", annual_return=0.05, account_type=AccountType.SAVINGS.value
        )

        config = builder._build_accounts_config()
        self.assertIn("Checking", config)
        self.assertEqual(config["Checking"]["annual_return"], 0.05)
        self.assertEqual(config["Checking"]["account_type"], AccountType.SAVINGS.value)

    def test_configure_category(self) -> None:
        builder = self._make_builder()
        builder.configure_category(
            "Rent", role=FinancialRole.EXPENSE.value, flexibility_score=1
        )

        config = builder._build_categories_config()
        self.assertIn("Rent", config)
        self.assertEqual(config["Rent"]["role"], FinancialRole.EXPENSE.value)
        self.assertEqual(config["Rent"]["flexibility_score"], 1)

    def test_update_initial_capital(self) -> None:
        builder = self._make_builder()
        builder.scenario["initial_capital"] = 0.0
        builder.update_initial_capital()
        self.assertGreater(builder.scenario["initial_capital"], 0)

    def test_write_outputs_all_configs(self) -> None:
        builder = self._make_builder()
        output_dir = os.path.join(self.tmp_dir.name, "scenario_output")
        paths = builder.write(output_dir)

        self.assertTrue(os.path.exists(paths["scenario"]))
        self.assertTrue(os.path.exists(paths["category_config"]))
        self.assertTrue(os.path.exists(paths["account_config"]))

        with open(paths["scenario"], encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["currency"], "EUR")

    def test_infer_account_type_credit(self) -> None:
        builder = self._make_builder()
        builder.balances["CreditCard"] = -500.0
        result = builder._infer_account_type("CreditCard")
        self.assertEqual(result, AccountType.CREDIT.value)

    def test_infer_account_type_investment(self) -> None:
        builder = self._make_builder()
        result = builder._infer_account_type("My Investment Portfolio")
        self.assertEqual(result, AccountType.INVESTMENT.value)

    def test_infer_account_type_default_savings(self) -> None:
        builder = self._make_builder()
        result = builder._infer_account_type("Random Account")
        self.assertEqual(result, AccountType.SAVINGS.value)

    def test_set_tax_config(self) -> None:
        builder = self._make_builder()
        builder.set_taxable_income(["Salary"])
        builder.set_tax_categories(["Community"])
        builder.set_snapshot_name("tax_test")

        output_dir = os.path.join(self.tmp_dir.name, "tax_scenario")
        paths = builder.write(output_dir)

        with open(paths["scenario"], encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["taxable_income_categories"], ["Salary"])
            self.assertEqual(data["tax_categories"], ["Community"])
            self.assertEqual(data["snapshot_name"], "tax_test")

    def test_set_estimated_effective_tax_rate(self) -> None:
        builder = self._make_builder()
        builder.set_taxable_income(["Salary"])
        builder.set_tax_categories([])
        builder.set_estimated_effective_tax_rate(0.18)
        builder.set_snapshot_name("est_tax_test")

        output_dir = os.path.join(self.tmp_dir.name, "est_tax_scenario")
        paths = builder.write(output_dir)

        with open(paths["scenario"], encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(data["estimated_effective_tax_rate"], 0.18)
            self.assertEqual(data["tax_categories"], [])

    def test_set_estimated_effective_tax_rate_none(self) -> None:
        builder = self._make_builder()
        builder.set_estimated_effective_tax_rate(None)

        output_dir = os.path.join(self.tmp_dir.name, "est_tax_none")
        paths = builder.write(output_dir)

        with open(paths["scenario"], encoding="utf-8") as f:
            data = json.load(f)
            self.assertIsNone(data["estimated_effective_tax_rate"])

    def test_build_accounts_config_includes_allocation_ratio(self) -> None:
        builder = self._make_builder()
        builder.balances["Savings"] = 5000.0
        builder._detect_accounts()
        builder.update_initial_capital()

        config = builder._build_accounts_config()
        self.assertIn("Checking", config)
        self.assertIn("Savings", config)
        self.assertGreater(config["Checking"]["allocation_ratio"], 0)
        self.assertGreater(config["Savings"]["allocation_ratio"], 0)

    def test_sub_categories_in_config(self) -> None:
        builder = self._make_builder()
        builder.configure_sub_category(
            "Food", "Groceries", flexibility_score=1, is_recurring=True
        )

        config = builder._build_categories_config()
        self.assertIn("Food", config)
        self.assertIn("sub_categories", config["Food"])
        subs = config["Food"]["sub_categories"]
        self.assertIn("Groceries", subs)
        self.assertEqual(subs["Groceries"]["flexibility_score"], 1)
        self.assertTrue(subs["Groceries"]["is_recurring"])


if __name__ == "__main__":
    unittest.main()
