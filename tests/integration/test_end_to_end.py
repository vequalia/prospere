import os
import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from prospere.core.constants import AccountType
from prospere.ingestion.engine import IngestionEngineFactory
from prospere.simulation.analyzer import HistoricalDataAnalyzer
from prospere.simulation.engine import MonteCarloSimulationEngine
from prospere.simulation.models import (
    AccountStats,
    GrowthPolicy,
    ScenarioMetadata,
    SimulationParams,
)


class TestEndToEndPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_csv = "tests/mock_data/baseline_moneywiz.csv"
        self.temp_dir = TemporaryDirectory()
        self.processed_xlsx = os.path.join(self.temp_dir.name, "processed.xlsx")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_complete_flow_with_growth_tax_and_shocks(self) -> None:
        # 1. Ingestion: Parse the mock CSV
        engine = IngestionEngineFactory.create_engine("moneywiz")
        transactions, balances = engine.parse_data(self.mock_csv)

        self.assertTrue(len(transactions) > 0, "Should have parsed transactions")
        self.assertEqual(len(balances), 2, "Should have parsed 2 account balances")

        # 2. Preparation: Convert to Excel for HistoricalDataAnalyzer
        df = pd.DataFrame(
            [
                {
                    "unique_id": t.unique_id,
                    "transaction_date": t.transaction_date,
                    "amount": t.amount,
                    "currency": t.currency,
                    "primary_category": t.primary_category,
                    "secondary_category": t.secondary_category,
                    "account_name": t.account_name,
                }
                for t in transactions
            ]
        )
        df.to_excel(self.processed_xlsx, index=False)

        # 3. Analysis: Build FinancialProfile
        from prospere.simulation.config import CategoryConfigurationManager

        cat_manager = CategoryConfigurationManager(
            "tests/mock_data/category_config.json"
        )
        cat_manager.load_from_disk()

        analyzer = HistoricalDataAnalyzer(self.processed_xlsx)
        profile = analyzer.construct_financial_profile(
            currency="EUR", category_config=cat_manager
        )

        # Verify baseline analysis
        self.assertAlmostEqual(profile.monthly_income_mean, 5000.0)
        # Expense: 1500 (Rent) + ~500 (Food) + 1000 (Tax) = 3000
        self.assertGreater(profile.monthly_expense_mean, 2900)

        # 4. Customization: Inject Advanced Features
        # 4.1. Account Setup (Allocation and Returns)
        accounts = [
            AccountStats(
                name="Checking",
                account_type=AccountType.CASH,
                annual_return=0.0,
                monthly_net_flow_mean=0.0,
                monthly_net_flow_std=0.0,
                initial_balance=10000.0,
                allocation_ratio=0.0,
            ),
            AccountStats(
                name="Savings",
                account_type=AccountType.SAVINGS,
                annual_return=0.04,  # 4% annual return
                monthly_net_flow_mean=0.0,
                monthly_net_flow_std=0.0,
                initial_balance=50000.0,
                allocation_ratio=1.0,  # All surplus goes to savings
            ),
        ]

        # 4.2. Inject a "Black Swan" Shock Event into Food category
        new_categories = []
        for cat in profile.categories:
            if cat.name == "Food":
                # Inject a massive periodic medical shock hidden in Food for testing
                cat = replace(
                    cat,
                    shock_events=[
                        {
                            "probability": 0.05,  # 5% monthly chance
                            "min_amount": 10000.0,
                            "max_amount": 20000.0,
                            "is_one_time": False,
                        }
                    ],
                )
            new_categories.append(cat)

        profile = replace(profile, accounts=accounts, categories=new_categories)

        # 5. Policy: Salary growth and Inflation
        growth_policy = GrowthPolicy(
            default_expense_growth=0.02,  # 2% inflation
            default_income_growth=0.05,  # 5% annual raise
            inflation_rate=0.02,
        )

        # 6. Metadata: Scenario configuration
        meta = ScenarioMetadata(
            name="E2E_Test_Scenario",
            initial_capital=60000.0,
            years=20,
            iterations=100,  # Sufficient for statistical significance in test
            taxable_income_categories=["Income"],
            tax_categories=["Community"],  # Target "Community ► Taxes"
        )

        params = SimulationParams(
            initial_capital=meta.initial_capital,
            years=meta.years,
            iterations=meta.iterations,
            profile=profile,
            growth_policy=growth_policy,
            scenario_metadata=meta,
        )

        # 7. Execution: Run Simulation
        sim_engine = MonteCarloSimulationEngine()
        np.random.seed(42)  # Reproducible results
        result = sim_engine.execute_projection(params)

        # 8. Assertions: Verify all features worked
        self.assertIsNotNone(result)

        # 8.1. Check Success Rate
        self.assertGreaterEqual(result.success_rate, 0.0)

        # 8.2. Verify Tax Logic: Cumulative tax should be significantly > 0
        self.assertGreater(
            result.cumulative_tax_paid_50,
            0.0,
            "Tax should be collected from Community category",
        )

        # 8.3. Verify Growth Logic: Final median wealth should reflect 20 years
        self.assertGreater(result.percentile_50[-1], 200000.0)

        # 8.4. Verify Shock Events: 10th percentile should be lower than 50th
        self.assertLess(result.percentile_10[-1], result.percentile_50[-1])

        # 8.5. Portfolio Mix: Check if savings account type was tracked
        self.assertIn(AccountType.SAVINGS.value, result.portfolio_mix_50)


if __name__ == "__main__":
    unittest.main()
