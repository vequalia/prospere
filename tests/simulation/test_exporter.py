import json
import os
import unittest
from tempfile import TemporaryDirectory

import numpy as np

from prospere.core.constants import AccountType, NecessityLevel
from prospere.simulation.exporter import HTMLExporter, JSONExporter
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


def _make_minimal_profile() -> FinancialProfile:
    return FinancialProfile(
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


class TestHTMLExporter(unittest.TestCase):
    def setUp(self) -> None:
        self.result = _make_minimal_result()
        self.profile = _make_minimal_profile()
        self.meta = ScenarioMetadata(
            name="TestScenario", initial_capital=10000.0, years=5, iterations=100
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
            scenario_metadata=self.meta,
        )
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_html_generation_smoke(self) -> None:
        exporter = HTMLExporter(template_lang="en")
        output_path = os.path.join(self.tmp_dir.name, "report.html")
        path = exporter.generate(self.result, self.meta, self.params, output_path)

        self.assertEqual(path, output_path)
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
            self.assertIn("<html", content)
            self.assertIn("PROSPERE", content)
            self.assertIn("TestScenario", content)

    def test_html_i18n_zh(self) -> None:
        exporter = HTMLExporter(template_lang="zh")
        output_path = os.path.join(self.tmp_dir.name, "report_zh.html")
        exporter.generate(self.result, self.meta, self.params, output_path)

        with open(output_path, encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Prospere 模擬報告", content)
            self.assertIn("你的財務快照", content)
            self.assertNotIn("EXECUTIVE SUMMARY", content)

    def test_format_currency(self) -> None:
        exporter = HTMLExporter()
        self.assertEqual(exporter._format_currency(1234567), "€1,234,567")
        self.assertEqual(exporter._format_currency(0, "$"), "$0")
        self.assertEqual(exporter._format_currency(5000000), "€5,000,000")

    def test_portfolio_table_html_with_data(self) -> None:
        exporter = HTMLExporter()
        html = exporter._generate_portfolio_table_html(self.result)
        self.assertIn("<table>", html)
        self.assertIn("savings", html.lower())
        self.assertIn("investment", html.lower())

    def test_portfolio_table_empty(self) -> None:
        empty_result = _make_minimal_result()
        empty_result = SimulationResult(
            **{**empty_result.__dict__, "portfolio_mix_50": {}}
        )
        exporter = HTMLExporter()
        html = exporter._generate_portfolio_table_html(empty_result)
        self.assertIn("No portfolio data", html)

    def test_html_contains_chart_data(self) -> None:
        exporter = HTMLExporter()
        output_path = os.path.join(self.tmp_dir.name, "chart_report.html")
        exporter.generate(self.result, self.meta, self.params, output_path)

        with open(output_path, encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Chart", content)
            self.assertIn("canvas", content)
            self.assertIn("wealthChart", content)


class TestJSONExporter(unittest.TestCase):
    def setUp(self) -> None:
        self.result = _make_minimal_result()
        self.profile = _make_minimal_profile()
        self.meta = ScenarioMetadata(
            name="OptScenario", initial_capital=10000.0, years=5, iterations=100
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
            scenario_metadata=self.meta,
        )
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_json_optimization_context_structure(self) -> None:
        output_path = os.path.join(self.tmp_dir.name, "opt_context.json")
        path = JSONExporter.export_optimization_context(
            self.result, self.params, output_path
        )

        self.assertEqual(path, output_path)
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn("metadata", data)
            self.assertIn("baseline_results", data)
            self.assertIn("financial_profile", data)
            self.assertIn("growth_policy", data)
            self.assertEqual(data["metadata"]["scenario_name"], "OptScenario")

    def test_json_category_serialization(self) -> None:
        output_path = os.path.join(self.tmp_dir.name, "opt_context2.json")
        JSONExporter.export_optimization_context(self.result, self.params, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
            categories = data["financial_profile"]["categories"]
            self.assertEqual(len(categories), 2)
            salary = next(c for c in categories if c["name"] == "Salary")
            self.assertTrue(salary["is_income"])
            self.assertEqual(salary["flexibility_score"], 3)
            self.assertEqual(
                salary["necessity_level"], NecessityLevel.DISCRETIONARY.value
            )

    def test_json_growth_policy_fields(self) -> None:
        output_path = os.path.join(self.tmp_dir.name, "opt_context3.json")
        JSONExporter.export_optimization_context(self.result, self.params, output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
            gp = data["growth_policy"]
            self.assertEqual(gp["default_expense_growth"], 0.02)
            self.assertEqual(gp["default_income_growth"], 0.04)
            self.assertEqual(gp["inflation_rate"], 0.02)


if __name__ == "__main__":
    unittest.main()
