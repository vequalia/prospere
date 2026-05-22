import unittest
from unittest.mock import MagicMock, patch

from prospere.ai.assistant import (
    AccountPrediction,
    AccountPredictionList,
    AIAssistant,
    CategoryPrediction,
    CategoryPredictionList,
)
from prospere.core.constants import AccountType, FinancialRole, NecessityLevel


class TestAIAssistant(unittest.TestCase):
    def setUp(self) -> None:
        self.assistant = AIAssistant()

    @patch("prospere.ai.prompts.loader.PromptLoader.load")
    def test_account_prompt_building(self, mock_load: MagicMock) -> None:
        mock_load.return_value = "Template: {accounts}"
        account_metadata = [
            {"name": "Visa", "balance": -500.0, "currency": "EUR"},
        ]

        prompt = self.assistant._build_account_prompt(account_metadata)

        self.assertIn("Visa", prompt)
        self.assertIn("-500.0 EUR", prompt)
        mock_load.assert_called_with("user", "classify_accounts")

    @patch("prospere.ai.prompts.loader.PromptLoader.load")
    def test_category_prompt_building(self, mock_load: MagicMock) -> None:
        mock_load.return_value = "Template: {categories}"
        category_metadata = [
            {"name": "Salary", "avg_monthly": 5000.0, "stat_recurring": True},
        ]

        prompt = self.assistant._build_category_prompt(category_metadata)

        self.assertIn("Salary", prompt)
        self.assertIn("(+5000.00/mo, Statistically Recurring)", prompt)
        mock_load.assert_called_with("user", "classify_categories")

    @patch("prospere.ai.assistant.OpenAI")
    def test_classify_entities_success(self, mock_openai_class: MagicMock) -> None:
        # Use non-DeepSeek model so OpenAI Structured Outputs .parse() is used
        self.assistant = AIAssistant(model="gpt-4o-mini")
        # Setup mock client
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        self.assistant.client = mock_client

        # Mock Account Response
        mock_acc_response = MagicMock()
        mock_acc_prediction = AccountPredictionList(
            predictions=[
                AccountPrediction(
                    name="Visa",
                    account_type=AccountType.CREDIT,
                    annual_return=0.0,
                    confidence_score=0.9,
                    reasoning="Negative balance.",
                )
            ]
        )
        mock_acc_response.choices[0].message.parsed = mock_acc_prediction

        # Mock Category Response
        mock_cat_response = MagicMock()
        mock_cat_prediction = CategoryPredictionList(
            predictions=[
                CategoryPrediction(
                    name="Groceries",
                    role=FinancialRole.EXPENSE,
                    necessity_level=NecessityLevel.ESSENTIAL,
                    flexibility_score=2,
                    annual_growth_rate=0.03,
                    confidence_score=0.8,
                    reasoning="Standard living expense.",
                )
            ]
        )
        mock_cat_response.choices[0].message.parsed = mock_cat_prediction

        # Set side effect to return account response then category response
        mock_client.beta.chat.completions.parse.side_effect = [
            mock_acc_response,
            mock_cat_response,
        ]

        # Execute
        result = self.assistant.classify_entities(
            [{"name": "Visa", "balance": -50.0, "currency": "EUR"}],
            [{"name": "Groceries", "avg_monthly": -500.0, "stat_recurring": True}],
        )

        # Assert
        self.assertIsNotNone(result)
        if result:
            self.assertEqual(len(result.accounts), 1)
            self.assertEqual(result.accounts[0].account_type.value, "credit")
            self.assertEqual(len(result.categories), 1)
            self.assertEqual(result.categories[0].necessity_level.value, "essential")

    @patch("prospere.ai.assistant.OpenAI")
    def test_deepseek_special_params(self, mock_openai_class: MagicMock) -> None:
        """Verifies that DeepSeek models trigger special parameters."""
        # Setup assistant with deepseek model
        assistant = AIAssistant(model="deepseek-v4-pro", api_key="test-key")
        mock_client = MagicMock()
        assistant.client = mock_client

        # Mock the response for .create()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"predictions": []}'
        mock_client.chat.completions.create.return_value = mock_response

        # Execute a call
        assistant._fetch_account_classifications([])

        # Check that .create() was called (not .parse())
        self.assertTrue(mock_client.chat.completions.create.called)
        self.assertFalse(mock_client.beta.chat.completions.parse.called)

        # Check parameters
        args, kwargs = mock_client.chat.completions.create.call_args
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})


class TestPayrollTaxEstimate(unittest.TestCase):
    def test_valid_estimate(self) -> None:
        from prospere.ai.assistant import PayrollTaxEstimate

        p = PayrollTaxEstimate(estimated_rate=0.25, reasoning="25% effective rate")
        self.assertEqual(p.estimated_rate, 0.25)
        self.assertEqual(p.reasoning, "25% effective rate")

    def test_rate_zero(self) -> None:
        from prospere.ai.assistant import PayrollTaxEstimate

        p = PayrollTaxEstimate(estimated_rate=0.0, reasoning="No income tax")
        self.assertEqual(p.estimated_rate, 0.0)

    def test_rate_one(self) -> None:
        from prospere.ai.assistant import PayrollTaxEstimate

        p = PayrollTaxEstimate(estimated_rate=1.0, reasoning="100% tax")
        self.assertEqual(p.estimated_rate, 1.0)

    def test_rate_out_of_range_raises(self) -> None:
        from pydantic import ValidationError

        from prospere.ai.assistant import PayrollTaxEstimate

        with self.assertRaises(ValidationError):
            PayrollTaxEstimate(estimated_rate=1.5, reasoning="too high")
        with self.assertRaises(ValidationError):
            PayrollTaxEstimate(estimated_rate=-0.1, reasoning="negative")


if __name__ == "__main__":
    unittest.main()
