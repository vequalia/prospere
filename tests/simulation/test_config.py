import unittest

from prospere.core.constants import AccountType, FinancialRole, SimulationDefaults
from prospere.simulation.config import (
    AccountConfigurationManager,
    CategoryConfigurationManager,
)


class TestAccountConfigurationManager(unittest.TestCase):
    # ... (existing tests remain)

    def setUp(self) -> None:
        self.manager = AccountConfigurationManager("mock_path.json")

    def test_get_account_metadata_default_savings(self) -> None:
        # Test that a non-existent account defaults to SAVINGS with correct traits
        metadata = self.manager.get_account_metadata("New Savings Account")

        self.assertEqual(metadata["account_type"], AccountType.SAVINGS)
        self.assertEqual(
            metadata["annual_return"], SimulationDefaults.SAVINGS_RETURN_RATE
        )
        self.assertEqual(
            metadata["deposit_priority"], SimulationDefaults.PRIORITY_SAVINGS_BUFFER
        )
        self.assertEqual(metadata["initial_balance"], 0.0)

    def test_get_account_metadata_credit_defaults(self) -> None:
        # Test that if user specifies account_type as CREDIT,
        # it gets correct debt-repayment priority
        self.manager.registry["My Card"] = {"account_type": AccountType.CREDIT.value}
        metadata = self.manager.get_account_metadata("My Card")

        self.assertEqual(metadata["account_type"], AccountType.CREDIT)
        self.assertEqual(
            metadata["deposit_priority"], SimulationDefaults.PRIORITY_DEBT_REPAYMENT
        )
        self.assertEqual(metadata["annual_return"], 0.0)

    def test_get_account_metadata_investment_defaults(self) -> None:
        # Test investment defaults (higher return, higher std, different priority)
        self.manager.registry["Stock Portfolio"] = {
            "account_type": AccountType.INVESTMENT.value
        }
        metadata = self.manager.get_account_metadata("Stock Portfolio")

        self.assertEqual(metadata["account_type"], AccountType.INVESTMENT)
        self.assertEqual(
            metadata["annual_return"], SimulationDefaults.INVESTMENT_RETURN_RATE
        )
        self.assertEqual(
            metadata["annual_return_std"], SimulationDefaults.RETURN_STD_DEFAULT
        )
        self.assertEqual(
            metadata["deposit_priority"],
            SimulationDefaults.PRIORITY_STANDARD_INVESTMENT,
        )

    def test_user_override(self) -> None:
        # Test that user specified values override defaults correctly
        self.manager.registry["Special Savings"] = {
            "account_type": AccountType.SAVINGS.value,
            "annual_return": 0.15,  # Extremely high interest savings
            "deposit_priority": 1,  # Top priority
        }
        metadata = self.manager.get_account_metadata("Special Savings")

        self.assertEqual(metadata["annual_return"], 0.15)
        self.assertEqual(metadata["deposit_priority"], 1)
        # But other traits should still be defaulted
        self.assertEqual(metadata["max_balance"], float("inf"))

    def test_bootstrap_logic(self) -> None:
        # Minimal test for bootstrapping
        import pandas as pd

        df = pd.DataFrame({"account_name": ["Acc1", "Acc2"]})
        balances = {"Acc1": 1000.0, "Acc2": 4000.0}

        self.manager.bootstrap_from_dataset(df, initial_balances=balances)

        self.assertIn("Acc1", self.manager.registry)
        self.assertEqual(self.manager.registry["Acc1"]["initial_balance"], 1000.0)
        self.assertEqual(
            self.manager.registry["Acc1"]["allocation_ratio"], 0.2
        )  # 1000 / 5000
        self.assertEqual(
            self.manager.registry["Acc2"]["allocation_ratio"], 0.8
        )  # 4000 / 5000
        # Should NOT have inferred card types anymore, just defaults
        self.assertEqual(
            self.manager.registry["Acc1"]["account_type"], AccountType.SAVINGS.value
        )


class TestCategoryConfigurationManager(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = CategoryConfigurationManager("mock_cat_path.json")

    def test_get_metadata_defaults(self) -> None:
        # Test that non-existent category gets safe defaults (IGNORE)
        metadata = self.manager.get_metadata("Unknown Category")
        self.assertEqual(metadata["role"], FinancialRole.IGNORE.value)
        self.assertEqual(metadata["annual_growth_rate"], 0.0)
        self.assertTrue(metadata["is_recurring"])

    def test_get_metadata_override(self) -> None:
        # Test user override for category
        self.manager.registry["Salary"] = {
            "role": FinancialRole.INCOME.value,
            "annual_growth_rate": 0.05,
        }
        metadata = self.manager.get_metadata("Salary")
        self.assertEqual(metadata["role"], FinancialRole.INCOME.value)
        self.assertEqual(metadata["annual_growth_rate"], 0.05)
        # Defaults should still apply for other fields
        self.assertEqual(metadata["flexibility_score"], 3)


if __name__ == "__main__":
    unittest.main()
