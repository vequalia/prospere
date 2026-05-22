import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from prospere.optimization.engine import OptimizationEngine


class TestOptimizationEngine(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary directory structure for scenarios
        self.test_dir = tempfile.mkdtemp()
        self.sim_dir = os.path.join(self.test_dir, "simulation", "test_sim")
        self.opt_dir = os.path.join(self.test_dir, "optimization", "test_opt")
        self.export_dir = os.path.join(self.sim_dir, "exports", "optimization")

        os.makedirs(self.opt_dir)
        os.makedirs(self.export_dir)

        # 1. Create Simulation Context
        self.test_context = {
            "metadata": {
                "scenario_name": "test_sim",
                "years": 10,
                "iterations": 100,
                "base_currency": "EUR",
            },
            "baseline_results": {"final_wealth_p50": 320000.0, "success_rate": 0.8},
            "financial_profile": {
                "monthly_income_mean": 5000.0,
                "monthly_expense_mean": 3000.0,
                "categories": [
                    {
                        "name": "Salary",
                        "mean": 5000.0,
                        "is_income": True,
                        "flexibility_score": 1,
                        "necessity_level": "essential",
                    },
                    {
                        "name": "Rent",
                        "mean": 1500.0,
                        "is_income": False,
                        "flexibility_score": 1,
                        "necessity_level": "strict",
                    },
                    {
                        "name": "Entertainment",
                        "mean": 1000.0,
                        "is_income": False,
                        "flexibility_score": 5,
                        "necessity_level": "discretionary",
                    },
                    {
                        "name": "Groceries",
                        "mean": 500.0,
                        "is_income": False,
                        "flexibility_score": 2,
                        "necessity_level": "essential",
                    },
                ],
                "accounts": [
                    {
                        "name": "Bank",
                        "account_type": "savings",
                        "annual_return": 0.05,
                        "allocation_ratio": 1.0,
                        "initial_balance": 10000.0,
                        "currency": "EUR",
                    }
                ],
            },
            "growth_policy": {
                "default_expense_growth": 0.02,
                "default_income_growth": 0.03,
                "inflation_rate": 0.02,
            },
        }
        with open(os.path.join(self.export_dir, "opt_context_latest.json"), "w") as f:
            json.dump(self.test_context, f)

        # 2. Create Optimization Config
        self.test_opt_config = {
            "scenario_name": "Test Opt Plan",
            "source_simulation": "test_sim",
            "target_wealth": 400000.0,
            "bounds_rules": {"level_moderate": 0.5},
        }
        with open(os.path.join(self.opt_dir, "config.json"), "w") as f:
            json.dump(self.test_opt_config, f)

        # Patch PathConfig to use our temp directory
        self.path_patcher = patch("prospere.optimization.engine.PathConfig")
        self.mock_path_config = self.path_patcher.start()
        self.mock_path_config.OPT_SCENARIOS_DIR = os.path.join(
            self.test_dir, "optimization"
        )
        self.mock_path_config.SIM_SCENARIOS_DIR = os.path.join(
            self.test_dir, "simulation"
        )

    def tearDown(self) -> None:
        self.path_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_engine_initialization(self) -> None:
        engine = OptimizationEngine("test_opt")
        self.assertEqual(engine.opt_config["scenario_name"], "Test Opt Plan")
        self.assertEqual(engine.metadata["scenario_name"], "test_sim")
        self.assertEqual(len(engine.profile["categories"]), 4)

    def test_deterministic_projection(self) -> None:
        engine = OptimizationEngine("test_opt")
        # Projection with original means
        final_wealth = engine._deterministic_projection([1500.0, 1000.0, 500.0])
        self.assertGreater(final_wealth, 300000.0)

    def test_optimization_logic(self) -> None:
        engine = OptimizationEngine("test_opt")
        target = 400000.0
        frontier = engine.generate_efficient_frontier(target)

        self.assertTrue(len(frontier) > 0)

        # Verify first reachable strategy (if exists) or the max within bounds
        strat = frontier[0]
        self.assertEqual(
            strat.is_reachable, True
        )  # 400k should be reachable with 3k expenses

        # Verify Rent was NOT cut (it is strict)
        self.assertNotIn("Rent", strat.category_adjustments)

        # Verify Entertainment was adjusted
        self.assertIn("Entertainment", strat.category_adjustments)

    def test_what_if_logic(self) -> None:
        engine = OptimizationEngine("test_opt")
        # Reduce entertainment by 500
        result = engine.evaluate_what_if({"Entertainment": -500.0})
        self.assertGreater(result["wealth_delta"], 0)
        self.assertGreater(result["new_wealth"], result["baseline_wealth"])


if __name__ == "__main__":
    unittest.main()
