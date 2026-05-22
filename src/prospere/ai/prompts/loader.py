import os
from typing import Final

import yaml  # type: ignore


class PromptLoader:
    """Utility to load and cache AI prompt templates from YAML files."""

    BASE_DIR: Final = os.path.dirname(__file__)

    _cache: dict[str, str] = {}

    _SCHEMA_TO_PROMPT: Final = {
        "classify_accounts": "classify_accounts",
        "classify_categories": "classify_categories",
        "life_stage_modeling": "life_stage_modeling",
        "tax_rules": "tax_rules",
        "parse_optim_intent": "parse_optim_intent",
        "payroll_tax": "payroll_tax",
    }

    @classmethod
    def load(cls, category: str, name: str) -> str:
        """
        Load a prompt template from ``{category}/{name}.yaml``.

        Set ``PROSPERE_PROMPT_VERSION`` to a semantic style name (e.g.
        ``"heuristic"``, ``"first_principles"``, ``"systematic"``) to load
        ``{name}_{version}.yaml`` instead. Falls back to ``{name}.yaml``
        if the versioned file is not found.
        """
        version = os.environ.get("PROSPERE_PROMPT_VERSION")
        cache_key = f"{category}/{name}_{version}" if version else f"{category}/{name}"

        if cache_key in cls._cache:
            return cls._cache[cache_key]

        base_path = os.path.join(cls.BASE_DIR, category)
        file_path = os.path.join(base_path, f"{name}.yaml")

        if version:
            versioned_path = os.path.join(base_path, f"{name}_{version}.yaml")
            if os.path.exists(versioned_path):
                file_path = versioned_path

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Prompt template not found: {file_path}")

        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            template = str(data.get("template", ""))

        # Auto-inject output schema via {output_schema} placeholder
        schema_name = cls._SCHEMA_TO_PROMPT.get(name)
        if schema_name and "{output_schema}" in template:
            schema_content = cls._load_schema(schema_name)
            if schema_content:
                template = template.replace("{output_schema}", schema_content)

        cls._cache[cache_key] = template
        return template

    @classmethod
    def _load_schema(cls, schema_name: str) -> str | None:
        schema_path = os.path.join(cls.BASE_DIR, "schemas", f"{schema_name}.yaml")
        if not os.path.exists(schema_path):
            return None
        with open(schema_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return str(data.get("template", ""))

    @classmethod
    def clear_cache(cls) -> None:
        """Clears the internal template cache."""
        cls._cache.clear()
