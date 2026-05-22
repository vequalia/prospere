import json
import os
import unittest
from tempfile import TemporaryDirectory

from prospere.core.models import WorkspaceContext
from prospere.core.workspace import WorkspaceManager
from prospere.simulation.models import (
    DynamicGrowth,
    GrowthPolicy,
    ScenarioMetadata,
    SimulationParams,
    SimulationResult,
)
from prospere.simulation.scenario import ScenarioRepository


def _make_minimal_result(years: int = 5) -> SimulationResult:
    import numpy as np

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
        monthly_income_history_50=np.full(months - 1, 5000.0),
        monthly_expenses_history_50=np.full(months - 1, 3500.0),
        monthly_gains_history_50=np.full(months - 1, 300.0),
    )


class TestScenarioRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _create_repo_with_ws(self) -> tuple[ScenarioRepository, str]:
        context = WorkspaceContext(user="testuser")
        ws_manager = WorkspaceManager(context)
        ws_manager.user_root = os.path.join(self.tmp_dir.name, "testuser")
        repo = ScenarioRepository(ws_manager=ws_manager)
        scenario_id = "test_scenario_v1"
        return repo, scenario_id

    def test_resolve_directory_without_ws(self) -> None:
        repo = ScenarioRepository(ws_manager=None)
        result = repo.resolve_scenario_directory("my_scenario")
        self.assertIn("scenarios/simulation", result)
        self.assertIn("my_scenario", result)

    def test_resolve_directory_with_ws(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        result = repo.resolve_scenario_directory(scenario_id)
        self.assertIn("testuser", result)
        self.assertIn(scenario_id, result)

    def test_config_file_paths(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        paths = repo.get_configuration_file_paths(scenario_id)
        self.assertIn("metadata", paths)
        self.assertIn("category_config", paths)
        self.assertIn("account_config", paths)
        self.assertTrue(paths["metadata"].endswith("scenario.json"))
        self.assertTrue(paths["category_config"].endswith("category_config.json"))
        self.assertTrue(paths["account_config"].endswith("account_config.json"))

    def test_list_empty_scenarios(self) -> None:
        context = WorkspaceContext(user="newuser")
        ws_manager = WorkspaceManager(context)
        ws_manager.user_root = os.path.join(self.tmp_dir.name, "newuser")
        ws_manager.ensure_structure()
        repo = ScenarioRepository(ws_manager=ws_manager)
        scenarios = repo.list_available_scenarios()
        self.assertEqual(scenarios, [])

    def test_persist_and_retrieve_metadata_basic(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        scenario_dir = os.path.join(
            self.tmp_dir.name, "testuser", "scenarios", scenario_id
        )
        os.makedirs(scenario_dir, exist_ok=True)

        meta = ScenarioMetadata(
            name=scenario_id,
            initial_capital=50000.0,
            currency="EUR",
            years=10,
            iterations=500,
            start_date="2020-01-01",
            end_date="2025-12-31",
            taxable_income_categories=["Salary"],
            tax_categories=["Taxes"],
            snapshot_name="baseline",
        )

        repo.persist_scenario_metadata(meta)

        retrieved = repo.retrieve_scenario_metadata(scenario_id)
        self.assertEqual(retrieved.name, scenario_id)
        self.assertEqual(retrieved.initial_capital, 50000.0)
        self.assertEqual(retrieved.years, 10)
        self.assertEqual(retrieved.iterations, 500)
        self.assertEqual(retrieved.taxable_income_categories, ["Salary"])
        self.assertEqual(retrieved.tax_categories, ["Taxes"])
        self.assertIsNone(retrieved.estimated_effective_tax_rate)
        self.assertEqual(retrieved.snapshot_name, "baseline")

    def test_persist_and_retrieve_estimated_tax_rate(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        scenario_dir = os.path.join(
            self.tmp_dir.name, "testuser", "scenarios", scenario_id
        )
        os.makedirs(scenario_dir, exist_ok=True)

        meta = ScenarioMetadata(
            name=scenario_id,
            initial_capital=50000.0,
            years=10,
            iterations=500,
            taxable_income_categories=["Salary"],
            tax_categories=[],
            estimated_effective_tax_rate=0.15,
        )

        repo.persist_scenario_metadata(meta)
        retrieved = repo.retrieve_scenario_metadata(scenario_id)

        self.assertEqual(retrieved.estimated_effective_tax_rate, 0.15)
        self.assertEqual(retrieved.taxable_income_categories, ["Salary"])
        self.assertEqual(retrieved.tax_categories, [])

    def test_persist_and_retrieve_with_dynamic_growth(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        scenario_dir = os.path.join(
            self.tmp_dir.name, "testuser", "scenarios", scenario_id
        )
        os.makedirs(scenario_dir, exist_ok=True)

        dg = DynamicGrowth(initial_rate=0.10, terminal_rate=0.03, transition_years=5)
        gp = GrowthPolicy(
            default_expense_growth=0.02,
            default_income_growth=0.05,
            inflation_rate=0.025,
            category_overrides={"Rent": 0.03},
            dynamic_income_growth=dg,
        )
        meta = ScenarioMetadata(
            name=scenario_id,
            initial_capital=80000.0,
            years=20,
            iterations=1000,
            growth_policy=gp,
        )

        repo.persist_scenario_metadata(meta)
        retrieved = repo.retrieve_scenario_metadata(scenario_id)

        self.assertIsNotNone(retrieved.growth_policy)
        gp_ret = retrieved.growth_policy
        if gp_ret is not None:
            self.assertEqual(gp_ret.default_expense_growth, 0.02)
            self.assertEqual(gp_ret.default_income_growth, 0.05)
            self.assertEqual(gp_ret.inflation_rate, 0.025)
            self.assertEqual(gp_ret.category_overrides, {"Rent": 0.03})
            self.assertIsNotNone(gp_ret.dynamic_income_growth)
            if gp_ret.dynamic_income_growth is not None:
                self.assertEqual(gp_ret.dynamic_income_growth.initial_rate, 0.10)
                self.assertEqual(gp_ret.dynamic_income_growth.terminal_rate, 0.03)
                self.assertEqual(gp_ret.dynamic_income_growth.transition_years, 5)
            else:
                self.fail("Dynamic income growth is None")
        else:
            self.fail("Growth policy is None")

    def test_retrieve_missing_raises(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        with self.assertRaises(FileNotFoundError):
            repo.retrieve_scenario_metadata("nonexistent_scenario")

    def test_export_simulation_result_json(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        scenario_dir = os.path.join(
            self.tmp_dir.name, "testuser", "scenarios", scenario_id
        )
        os.makedirs(scenario_dir, exist_ok=True)

        meta = ScenarioMetadata(
            name=scenario_id, initial_capital=50000.0, years=10, iterations=500
        )
        repo.persist_scenario_metadata(meta)

        result = _make_minimal_result(5)
        output_path = repo.export_simulation_result(scenario_id, result)

        self.assertTrue(os.path.exists(output_path))
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn("summary", data)
            self.assertIn("trajectories", data)
            self.assertIn("distribution", data)
            self.assertIn("median_final_assets", data["summary"])
            self.assertIn("p50", data["trajectories"])

    def test_export_html_report_delegates(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        scenario_dir = os.path.join(
            self.tmp_dir.name, "testuser", "scenarios", scenario_id
        )
        os.makedirs(scenario_dir, exist_ok=True)

        from prospere.core.constants import AccountType
        from prospere.simulation.models import (
            AccountStats,
            CategoryStats,
            FinancialProfile,
        )

        meta = ScenarioMetadata(
            name=scenario_id, initial_capital=50000.0, years=10, iterations=500
        )
        repo.persist_scenario_metadata(meta)

        profile = FinancialProfile(
            monthly_income_mean=5000.0,
            monthly_income_std=500.0,
            monthly_expense_mean=3000.0,
            monthly_expense_std=300.0,
            currency="EUR",
            categories=[
                CategoryStats(name="Salary", mean=5000.0, std=500.0, is_income=True)
            ],
            accounts=[
                AccountStats(
                    name="Main",
                    account_type=AccountType.SAVINGS,
                    annual_return=0.02,
                    monthly_net_flow_mean=2000.0,
                    monthly_net_flow_std=100.0,
                    initial_balance=10000.0,
                )
            ],
        )
        params = SimulationParams(
            initial_capital=50000.0,
            years=10,
            iterations=500,
            profile=profile,
            growth_policy=GrowthPolicy(0.02, 0.04),
            scenario_metadata=meta,
        )

        result = _make_minimal_result(5)
        output_path = repo.export_html_report(
            scenario_id, result, params, template_lang="en"
        )

        self.assertTrue(os.path.exists(output_path))
        self.assertTrue(output_path.endswith(".html"))
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
            self.assertIn(scenario_id.upper(), content)

    def test_list_available_scenarios_with_data(self) -> None:
        repo, scenario_id = self._create_repo_with_ws()
        scenario_dir = os.path.join(
            self.tmp_dir.name, "testuser", "scenarios", scenario_id
        )
        os.makedirs(scenario_dir, exist_ok=True)

        meta = ScenarioMetadata(
            name=scenario_id, initial_capital=50000.0, years=10, iterations=500
        )
        repo.persist_scenario_metadata(meta)

        scenarios = repo.list_available_scenarios()
        self.assertIn(scenario_id, scenarios)


if __name__ == "__main__":
    unittest.main()
