import unittest

import numpy as np

from prospere.cli.i18n import _set_language
from prospere.cli.simulate import generate_insight_report_text
from prospere.core.constants import AccountType, NecessityLevel
from prospere.simulation.models import (
    AccountStats,
    CategoryStats,
    FinancialProfile,
    GrowthPolicy,
    ScenarioMetadata,
    SimulationParams,
    SimulationResult,
)


def _make_minimal_result(years: int = 5) -> SimulationResult:
    months = years * 12 + 1
    return SimulationResult(
        percentile_10=np.linspace(90000, 70000, months),
        percentile_50=np.linspace(100000, 150000, months),
        percentile_90=np.linspace(110000, 300000, months),
        success_rate=0.92,
        present_value_50=np.linspace(100000, 120000, months),
        passive_income_coverage_50=np.linspace(0.0, 0.6, months),
        final_wealth_distribution=np.random.default_rng(42).normal(150000, 30000, 100),
        account_histories_50={"Savings": np.linspace(50000, 120000, months)},
        net_cash_flow_50=np.full(months - 1, 2000.0),
        monthly_tax_history_50=np.full(months - 1, 500.0),
        cumulative_tax_paid_50=30000.0,
        effective_tax_rate=0.12,
        portfolio_mix_50={
            "savings": np.linspace(0.8, 0.3, months),
            "investment": np.linspace(0.2, 0.7, months),
        },
        liquidity_stress_months=2,
        account_saturation_months={"Savings": 0, "Investment": 0},
        account_roi_contribution={"Savings": 0.4, "Investment": 0.6},
        essential_expense_ratio=0.55,
        total_income_median=600000.0,
        total_expenses_median=420000.0,
        monthly_income_history_50=np.full(months - 1, 5000.0),
        monthly_expenses_history_50=np.full(months - 1, 3500.0),
        monthly_gains_history_50=np.full(months - 1, 300.0),
        shock_crash_months_median=1,
        shock_income_loss_months_median=2,
        shock_expense_spike_months_median=3,
        shock_crash_iter_pct=15.0,
        shock_income_loss_iter_pct=8.0,
        shock_expense_spike_iter_pct=12.0,
    )


class TestGenerateInsightReport(unittest.TestCase):
    def setUp(self) -> None:
        self.result = _make_minimal_result()
        self.profile = FinancialProfile(
            monthly_income_mean=5000.0,
            monthly_income_std=500.0,
            monthly_expense_mean=3000.0,
            monthly_expense_std=300.0,
            currency="EUR",
            categories=[
                CategoryStats(name="Salary", mean=5000.0, std=500.0, is_income=True),
                CategoryStats(
                    name="Rent",
                    mean=1500.0,
                    std=100.0,
                    is_income=False,
                    necessity_level=NecessityLevel.ESSENTIAL,
                    flexibility_score=1,
                ),
            ],
            accounts=[
                AccountStats(
                    name="Main",
                    account_type=AccountType.SAVINGS,
                    annual_return=0.02,
                    monthly_net_flow_mean=2000.0,
                    monthly_net_flow_std=100.0,
                    initial_balance=10000.0,
                    allocation_ratio=1.0,
                )
            ],
        )
        self.growth = GrowthPolicy(
            default_expense_growth=0.02, default_income_growth=0.04, inflation_rate=0.02
        )
        self.params = SimulationParams(
            initial_capital=10000.0,
            years=5,
            iterations=100,
            profile=self.profile,
            growth_policy=self.growth,
            scenario_metadata=ScenarioMetadata(
                name="TestRun", initial_capital=10000.0, years=5, iterations=100
            ),
        )
        self.meta = ScenarioMetadata(
            name="TestRun", initial_capital=10000.0, years=5, iterations=100
        )

    def test_report_returns_non_empty_string(self) -> None:
        _set_language("en")
        report = generate_insight_report_text(self.result, self.params, self.meta)
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 0)

    def test_report_contains_sections(self) -> None:
        _set_language("en")
        report = generate_insight_report_text(self.result, self.params, self.meta)
        self.assertIn("YOUR RESULTS AT A GLANCE", report)
        self.assertIn("DETAILED ANALYSIS", report)
        self.assertIn("WHERE YOUR MONEY LIVES", report)

    def test_report_zh(self) -> None:
        _set_language("zh")
        report = generate_insight_report_text(self.result, self.params, self.meta)
        self.assertIsInstance(report, str)
        self.assertGreater(len(report), 0)


if __name__ == "__main__":
    unittest.main()
