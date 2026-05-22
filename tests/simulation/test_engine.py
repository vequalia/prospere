import unittest

import numpy as np

from prospere.core.constants import AccountType
from prospere.simulation.engine import MonteCarloSimulationEngine
from prospere.simulation.models import (
    AccountStats,
    CategoryStats,
    FinancialProfile,
    GrowthPolicy,
    ScenarioMetadata,
    SimulationParams,
)


class TestMonteCarloSimulationEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = MonteCarloSimulationEngine()
        self.default_account = AccountStats(
            name="Main",
            account_type=AccountType.SAVINGS,
            annual_return=0.0,
            monthly_net_flow_mean=0.0,
            monthly_net_flow_std=0.0,
            allocation_ratio=1.0,
            initial_balance=10000.0,
        )
        self.profile = FinancialProfile(
            monthly_income_mean=5000.0,
            monthly_income_std=0.0,
            monthly_expense_mean=3000.0,
            monthly_expense_std=0.0,
            currency="EUR",
            categories=[],
            accounts=[self.default_account],
        )
        self.growth_policy = GrowthPolicy(0.0, 0.0)
        self.meta = ScenarioMetadata(
            name="test",
            initial_capital=10000.0,
            years=1,
            iterations=100,
        )
        self.params = SimulationParams(
            initial_capital=10000.0,
            years=1,
            iterations=100,
            profile=self.profile,
            growth_policy=self.growth_policy,
            scenario_metadata=self.meta,
        )

    def test_run_reproducibility(self) -> None:
        # With seed, results should be identical.
        np.random.seed(42)
        res1 = self.engine.execute_projection(self.params)
        np.random.seed(42)
        res2 = self.engine.execute_projection(self.params)

        self.assertEqual(res1.success_rate, res2.success_rate)
        self.assertEqual(res1.percentile_50[-1], res2.percentile_50[-1])

    def test_wealth_accumulation(self) -> None:
        # With zero volatility and income > expense, wealth should grow
        account = AccountStats(
            name="Main",
            account_type=AccountType.SAVINGS,
            annual_return=0.0,
            monthly_net_flow_mean=0.0,
            monthly_net_flow_std=0.0,
            allocation_ratio=1.0,
            initial_balance=10000.0,
        )
        # Add categories for income and expense
        income_cat = CategoryStats(name="Salary", mean=5000.0, std=0.0, is_income=True)
        expense_cat = CategoryStats(name="Rent", mean=3000.0, std=0.0, is_income=False)
        profile = FinancialProfile(
            5000.0, 0.0, 3000.0, 0.0, "EUR", [income_cat, expense_cat], [account]
        )
        meta = ScenarioMetadata(
            name="acc",
            initial_capital=10000.0,
            years=1,
            iterations=10,
        )
        params = SimulationParams(
            initial_capital=10000.0,
            years=1,
            iterations=10,
            profile=profile,
            growth_policy=GrowthPolicy(0.0, 0.0),
            scenario_metadata=meta,
        )
        res = self.engine.execute_projection(params)

        # Expected final capital: 10000 + (5000 - 3000) * 12 = 34000
        self.assertAlmostEqual(res.percentile_50[-1], 34000.0)
        self.assertEqual(res.success_rate, 1.0)

    def test_estimated_tax_rate_fallback(self) -> None:
        income_cat = CategoryStats(name="Salary", mean=5000.0, std=0.0, is_income=True)
        expense_cat = CategoryStats(name="Rent", mean=3000.0, std=0.0, is_income=False)
        account = AccountStats(
            name="Main",
            account_type=AccountType.SAVINGS,
            annual_return=0.0,
            monthly_net_flow_mean=0.0,
            monthly_net_flow_std=0.0,
            allocation_ratio=1.0,
            initial_balance=10000.0,
        )
        profile = FinancialProfile(
            5000.0, 0.0, 3000.0, 0.0, "EUR", [income_cat, expense_cat], [account]
        )
        meta = ScenarioMetadata(
            name="est_tax",
            initial_capital=10000.0,
            years=1,
            iterations=10,
            taxable_income_categories=["Salary"],
            tax_categories=[],
            estimated_effective_tax_rate=0.20,
        )
        params = SimulationParams(
            initial_capital=10000.0,
            years=1,
            iterations=10,
            profile=profile,
            growth_policy=GrowthPolicy(0.0, 0.0),
            scenario_metadata=meta,
        )
        res = self.engine.execute_projection(params)

        self.assertEqual(res.effective_tax_rate, 0.20)
        self.assertGreater(res.cumulative_tax_paid_50, 0.0)

    def test_estimated_tax_rate_gross_up_preserves_net(self) -> None:
        income_cat = CategoryStats(name="Salary", mean=5000.0, std=0.0, is_income=True)
        expense_cat = CategoryStats(name="Rent", mean=2000.0, std=0.0, is_income=False)
        account = AccountStats(
            name="Main",
            account_type=AccountType.SAVINGS,
            annual_return=0.0,
            monthly_net_flow_mean=0.0,
            monthly_net_flow_std=0.0,
            allocation_ratio=1.0,
            initial_balance=0.0,
        )
        profile = FinancialProfile(
            5000.0, 0.0, 2000.0, 0.0, "EUR", [income_cat, expense_cat], [account]
        )
        meta = ScenarioMetadata(
            name="gross_up",
            initial_capital=0.0,
            years=1,
            iterations=10,
            taxable_income_categories=["Salary"],
            tax_categories=[],
            estimated_effective_tax_rate=0.20,
        )
        params = SimulationParams(
            initial_capital=0.0,
            years=1,
            iterations=10,
            profile=profile,
            growth_policy=GrowthPolicy(0.0, 0.0),
            scenario_metadata=meta,
        )
        res = self.engine.execute_projection(params)

        expected_net_monthly = 5000.0 - 2000.0
        expected_final = expected_net_monthly * 12
        self.assertAlmostEqual(res.percentile_50[-1], expected_final)
        self.assertEqual(res.success_rate, 1.0)

    def test_estimated_tax_rate_no_fallback_with_historical_data(self) -> None:
        income_cat = CategoryStats(name="Salary", mean=6000.0, std=0.0, is_income=True)
        tax_cat = CategoryStats(name="Taxes", mean=1200.0, std=0.0, is_income=False)
        rent_cat = CategoryStats(name="Rent", mean=2000.0, std=0.0, is_income=False)
        account = AccountStats(
            name="Main",
            account_type=AccountType.SAVINGS,
            annual_return=0.0,
            monthly_net_flow_mean=0.0,
            monthly_net_flow_std=0.0,
            allocation_ratio=1.0,
            initial_balance=0.0,
        )
        profile = FinancialProfile(
            6000.0,
            0.0,
            3200.0,
            0.0,
            "EUR",
            [income_cat, tax_cat, rent_cat],
            [account],
        )
        meta = ScenarioMetadata(
            name="hist_data",
            initial_capital=0.0,
            years=1,
            iterations=10,
            taxable_income_categories=["Salary"],
            tax_categories=["Taxes"],
            estimated_effective_tax_rate=0.20,
        )
        params = SimulationParams(
            initial_capital=0.0,
            years=1,
            iterations=10,
            profile=profile,
            growth_policy=GrowthPolicy(0.0, 0.0),
            scenario_metadata=meta,
        )
        res = self.engine.execute_projection(params)

        self.assertAlmostEqual(res.effective_tax_rate, 0.20)
        expected_net_monthly = 6000.0 - 2000.0 - 1200.0
        expected_final = expected_net_monthly * 12
        self.assertAlmostEqual(res.percentile_50[-1], expected_final)


if __name__ == "__main__":
    unittest.main()
