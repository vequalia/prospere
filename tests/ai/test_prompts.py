import os
import unittest
from unittest.mock import patch

from prospere.ai.prompts.loader import PromptLoader


class TestPromptLoader(unittest.TestCase):
    def setUp(self) -> None:
        PromptLoader.clear_cache()

    def tearDown(self) -> None:
        PromptLoader.clear_cache()

    # ── Basic Loading ──────────────────────────────────────────────────

    def test_load_classify_accounts(self) -> None:
        template = PromptLoader.load("user", "classify_accounts")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_classify_categories(self) -> None:
        template = PromptLoader.load("user", "classify_categories")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_life_stage(self) -> None:
        template = PromptLoader.load("user", "life_stage_modeling")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_tax_rules(self) -> None:
        template = PromptLoader.load("user", "tax_rules")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_parse_intent(self) -> None:
        template = PromptLoader.load("user", "parse_optim_intent")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_system_analyst(self) -> None:
        template = PromptLoader.load("system", "analyst")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_system_planner(self) -> None:
        template = PromptLoader.load("system", "planner")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_load_system_optim_chat(self) -> None:
        template = PromptLoader.load("system", "optim_chat")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    # ── Caching ────────────────────────────────────────────────────────

    def test_caching_returns_same_instance(self) -> None:
        PromptLoader.clear_cache()
        first = PromptLoader.load("user", "classify_accounts")
        second = PromptLoader.load("user", "classify_accounts")
        self.assertIs(first, second)

    def test_clear_cache_empties_store(self) -> None:
        PromptLoader.load("user", "classify_accounts")
        self.assertGreater(len(PromptLoader._cache), 0)
        PromptLoader.clear_cache()
        self.assertEqual(len(PromptLoader._cache), 0)

    def test_load_nonexistent_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            PromptLoader.load("user", "nonexistent_prompt_name")

    # ── Semantic Style Loading ─────────────────────────────────────────

    @patch.dict(
        os.environ,
        {"PROSPERE_PROMPT_VERSION": "heuristic"},
        clear=True,
    )
    def test_load_heuristic_variant(self) -> None:
        template = PromptLoader.load("user", "classify_accounts")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)
        self.assertIn("HEURISTIC FRAMEWORK", template.upper())

    @patch.dict(
        os.environ,
        {"PROSPERE_PROMPT_VERSION": "first_principles"},
        clear=True,
    )
    def test_load_first_principles_variant(self) -> None:
        template = PromptLoader.load("user", "classify_accounts")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)
        self.assertIn("FIRST PRINCIPLES", template.upper())

    @patch.dict(
        os.environ,
        {"PROSPERE_PROMPT_VERSION": "systematic"},
        clear=True,
    )
    def test_load_systematic_variant_falls_back(self) -> None:
        # systematic is the default for classify_accounts, so the variant
        # file was deleted — loading with "systematic" falls back to default.
        template = PromptLoader.load("user", "classify_accounts")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    @patch.dict(
        os.environ,
        {"PROSPERE_PROMPT_VERSION": "systematic"},
        clear=True,
    )
    def test_load_parse_intent_systematic(self) -> None:
        template = PromptLoader.load("user", "parse_optim_intent")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)
        self.assertIn("SYSTEMATIC PARSING", template.upper())

    @patch.dict(
        os.environ,
        {"PROSPERE_PROMPT_VERSION": "first_principles"},
        clear=True,
    )
    def test_load_parse_intent_first_principles(self) -> None:
        # first_principles is the default for parse_optim_intent.
        # Loading with "first_principles" falls back to default.
        template = PromptLoader.load("user", "parse_optim_intent")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    def test_heuristic_differs_from_default(self) -> None:
        PromptLoader.clear_cache()
        default = PromptLoader.load("user", "classify_accounts")
        PromptLoader.clear_cache()
        with patch.dict(
            os.environ, {"PROSPERE_PROMPT_VERSION": "heuristic"}, clear=True
        ):
            heuristic = PromptLoader.load("user", "classify_accounts")
        self.assertNotEqual(default, heuristic)

    @patch.dict(
        os.environ,
        {"PROSPERE_PROMPT_VERSION": "unknown_style"},
        clear=True,
    )
    def test_unknown_style_falls_back_to_default(self) -> None:
        template = PromptLoader.load("user", "classify_accounts")
        self.assertIsInstance(template, str)
        self.assertGreater(len(template), 0)

    # ── Schema Injection ───────────────────────────────────────────────

    def test_classify_accounts_has_schema_injected(self) -> None:
        template = PromptLoader.load("user", "classify_accounts")
        self.assertNotIn("{output_schema}", template)
        self.assertIn('"predictions"', template)

    def test_schema_injected_in_all_styles(self) -> None:
        styles = ["heuristic", "first_principles"]
        for style in styles:
            PromptLoader.clear_cache()
            with patch.dict(os.environ, {"PROSPERE_PROMPT_VERSION": style}, clear=True):
                template = PromptLoader.load("user", "classify_accounts")
            self.assertNotIn(
                "{output_schema}",
                template,
                f"Schema not injected for style '{style}'",
            )

    # ── Content Verification ───────────────────────────────────────────

    def test_default_classify_accounts_is_systematic(self) -> None:
        template = PromptLoader.load("user", "classify_accounts")
        self.assertIn("SYSTEMATIC REASONING", template.upper())

    def test_default_parse_intent_is_first_principles(self) -> None:
        template = PromptLoader.load("user", "parse_optim_intent")
        self.assertIn("FIRST PRINCIPLES", template.upper())


if __name__ == "__main__":
    unittest.main()
