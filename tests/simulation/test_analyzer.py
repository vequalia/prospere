import os
import unittest

import pandas as pd

from prospere.simulation.analyzer import HistoricalDataAnalyzer


class TestHistoricalDataAnalyzer(unittest.TestCase):
    def setUp(self) -> None:
        self.test_file = "tests/test_transactions.xlsx"
        # Create a dummy dataframe
        data = {
            "unique_id": ["1", "2", "3", "4"],
            "transaction_date": [
                "2023-01-01",
                "2023-01-15",
                "2023-02-01",
                "2023-02-15",
            ],
            "amount": [5000, -2000, 6000, -3000],
            "currency": ["EUR", "EUR", "EUR", "EUR"],
            "primary_category": ["Salary", "Food", "Salary", "Rent"],
            "secondary_category": ["", "", "", ""],
            "account_name": ["Acc1", "Acc1", "Acc1", "Acc1"],
        }
        df = pd.DataFrame(data)
        df.to_excel(self.test_file, index=False)
        self.analyzer = HistoricalDataAnalyzer(self.test_file)

    def tearDown(self) -> None:
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_analyze(self) -> None:
        # Mock CategoryConfigurationManager to return INCOME for Salary and
        # EXPENSE for Food/Rent
        from typing import Any
        from unittest.mock import MagicMock

        from prospere.core.constants import FinancialRole

        mock_config = MagicMock()

        def side_effect(name: str) -> dict[str, Any]:
            role = (
                FinancialRole.INCOME.value
                if name == "Salary"
                else FinancialRole.EXPENSE.value
            )
            return {
                "role": role,
                "is_recurring": True,
                "flexibility_score": 3,
                "necessity_level": "discretionary",
                "annual_growth_rate": 0.0,
                "income_linked_rate": 0.0,
            }

        mock_config.get_metadata.side_effect = side_effect

        profile = self.analyzer.construct_financial_profile(
            currency="EUR", category_config=mock_config
        )

        # Monthly Income: Jan=5000, Feb=6000 -> Mean=5500
        # Monthly Expense: Jan=2000, Feb=3000 -> Mean=2500
        self.assertEqual(profile.monthly_income_mean, 5500.0)
        self.assertEqual(profile.monthly_expense_mean, 2500.0)
        self.assertEqual(profile.currency, "EUR")

    def test_invalid_currency(self) -> None:
        # The analyzer should raise ValueError if the requested base currency is
        # not in RATES
        with self.assertRaises(ValueError):
            self.analyzer.construct_financial_profile(currency="INVALID")


if __name__ == "__main__":
    unittest.main()
