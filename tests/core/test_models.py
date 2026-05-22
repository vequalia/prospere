import unittest
from datetime import date

from prospere.core.models import (
    AccountBalance,
    Identity,
    Transaction,
    WorkspaceContext,
)


class TestTransaction(unittest.TestCase):
    def test_transaction_creation(self) -> None:
        txn = Transaction(
            unique_id="abc123",
            transaction_date=date(2024, 1, 15),
            amount=-1500.0,
            currency="EUR",
            primary_category="Housing",
            secondary_category="Rent",
            account_name="Checking",
        )
        self.assertEqual(txn.unique_id, "abc123")
        self.assertEqual(txn.amount, -1500.0)
        self.assertEqual(txn.primary_category, "Housing")
        self.assertEqual(txn.secondary_category, "Rent")
        self.assertEqual(txn.account_name, "Checking")
        self.assertEqual(txn.currency, "EUR")


class TestAccountBalance(unittest.TestCase):
    def test_balance_creation(self) -> None:
        bal = AccountBalance(account_name="Savings", balance=50000.0, currency="EUR")
        self.assertEqual(bal.account_name, "Savings")
        self.assertEqual(bal.balance, 50000.0)
        self.assertEqual(bal.currency, "EUR")


class TestIdentity(unittest.TestCase):
    def test_identity_defaults(self) -> None:
        ident = Identity(name="Alice")
        self.assertEqual(ident.name, "Alice")
        self.assertEqual(ident.age, "")
        self.assertEqual(ident.industry, "")
        self.assertEqual(ident.location, "")
        self.assertEqual(ident.family_status, "")
        self.assertEqual(ident.financial_goal, "")

    def test_identity_full(self) -> None:
        ident = Identity(
            name="Bob",
            age="35",
            industry="Finance",
            location="London",
            family_status="Married",
            financial_goal="Retirement",
        )
        self.assertEqual(ident.name, "Bob")
        self.assertEqual(ident.age, "35")
        self.assertEqual(ident.industry, "Finance")
        self.assertEqual(ident.location, "London")
        self.assertEqual(ident.family_status, "Married")
        self.assertEqual(ident.financial_goal, "Retirement")

    def test_identity_to_dict(self) -> None:
        ident = Identity(name="Carol", age="28", industry="Tech")
        d = ident.to_dict()
        self.assertEqual(d["age"], "28")
        self.assertEqual(d["industry"], "Tech")
        self.assertIn("location", d)
        self.assertIn("family_status", d)
        self.assertIn("financial_goal", d)


class TestWorkspaceContext(unittest.TestCase):
    def test_context_creation(self) -> None:
        ctx = WorkspaceContext(
            user="alice",
            snapshot="baseline_2024",
            scenario="early_retirement",
        )
        self.assertEqual(ctx.user, "alice")
        self.assertEqual(ctx.snapshot, "baseline_2024")
        self.assertEqual(ctx.scenario, "early_retirement")

    def test_context_defaults(self) -> None:
        ctx = WorkspaceContext(user="bob")
        self.assertEqual(ctx.user, "bob")
        self.assertIsNone(ctx.snapshot)
        self.assertIsNone(ctx.scenario)


if __name__ == "__main__":
    unittest.main()
