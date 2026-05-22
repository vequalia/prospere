import contextlib
import logging
import os
import readline
import sys
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import AliasChoices, BaseModel, Field
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text
from rich.theme import Theme

from prospere.ai.prompts.loader import PromptLoader
from prospere.core.constants import (
    AccountType,
    AIConfig,
    FinancialRole,
    NecessityLevel,
    SimulationDefaults,
    UITheme,
)
from prospere.core.settings import settings_manager

# ── Theme ──────────────────────────────────────────────────────────────
CHAT_THEME = Theme(UITheme.THEME_DICT)

# ── UI Constants ───────────────────────────────────────────────────────
# \001 / \002 mark non-printing ANSI sequences for readline so the
# prompt cannot be backspaced over.
_PROMPT = "\001\033[1;38;2;212;168;83m\002❯ \001\033[0m\002"

_USER_BORDER_STYLE = f"dim {UITheme.META}"
_USER_BORDER_CHAR = "▎ "
_SEPARATOR = "─"
_SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_HISTORY_FILE = os.path.expanduser("~/.prospere_chat_history")

load_dotenv()

logger = logging.getLogger(__name__)


class AccountPrediction(BaseModel):
    """AI prediction for a financial account."""

    name: str
    account_type: AccountType = Field(
        description="The classified type of the financial account."
    )
    annual_return: float = Field(
        description="Estimated annual return rate (e.g., 0.05 for 5%)"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="AI confidence from 0.0 to 1.0"
    )
    reasoning: str = Field(description="Brief explanation for the classification")


class AccountPredictionList(BaseModel):
    """Container for multiple account predictions."""

    predictions: list[AccountPrediction] = Field(
        validation_alias=AliasChoices("predictions", "accounts"), default_factory=list
    )


class SubCategoryPrediction(BaseModel):
    """AI prediction for a sub-category."""

    name: str
    necessity_level: NecessityLevel = Field(
        description="The priority level of this expense."
    )
    flexibility_score: int = Field(ge=1, le=10, description="Score from 1 to 10")
    reasoning: str = Field(description="Brief explanation for the classification")


class CategoryPrediction(BaseModel):
    """AI prediction for a transaction category."""

    name: str
    role: FinancialRole = Field(description="The financial role of this category.")
    necessity_level: NecessityLevel = Field(
        description="The priority level of this category."
    )
    flexibility_score: int = Field(ge=1, le=10, description="Score from 1 to 10")
    annual_growth_rate: float = Field(
        description="Expected annual growth rate of this category."
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="AI confidence from 0.0 to 1.0"
    )
    reasoning: str = Field(description="Brief explanation for the classification")
    sub_categories: list[SubCategoryPrediction] = Field(
        default_factory=list,
        description="Detailed predictions for individual sub-categories",
    )


class CategoryPredictionList(BaseModel):
    """Container for multiple category predictions."""

    predictions: list[CategoryPrediction] = Field(
        validation_alias=AliasChoices("predictions", "categories"), default_factory=list
    )


class DynamicGrowthPrediction(BaseModel):
    """AI prediction for dynamic growth parameters."""

    initial_rate: float = Field(
        description="Starting annual growth rate (e.g. 0.10 for 10%)"
    )
    terminal_rate: float = Field(
        description="Long-term stable annual growth rate (e.g. 0.03 for 3%)"
    )
    transition_years: int = Field(
        description="Years to transition from initial to terminal rate"
    )


class LifeStageModeling(BaseModel):
    """AI modeling of a user's life stage and corresponding growth curves."""

    life_stage: str = Field(
        description="Inferred life stage (e.g. 'Early Career', 'Stable Mid-Career')"
    )
    income_growth: DynamicGrowthPrediction
    expense_growth: DynamicGrowthPrediction
    reasoning: str = Field(
        description="Brief explanation for the inferred life stage and curves"
    )


class TaxRulePrediction(BaseModel):
    """AI prediction for a single tax rule."""

    name: str = Field(description="Rule name, e.g. 'capital_gains_tax'")
    base: str = Field(
        description="Tax base: capital_gains | interest_earned | salary_income"
    )
    rate: float = Field(ge=0.0, le=1.0, description="Flat tax rate")
    exempt_accounts: list[str] = Field(
        default_factory=list, description="Account names exempt from this tax"
    )
    deduct_from: str = Field(
        default="account",
        description="Where to deduct: 'account' or 'cash_flow'",
    )
    apply_only_to_positive: bool = Field(
        default=True, description="Only tax positive gains"
    )


class TaxRulesConfig(BaseModel):
    """Complete tax rules configuration for a country."""

    country: str = Field(description="Country the rules apply to")
    tax_regime_summary: str = Field(
        description="One-paragraph summary of the tax regime"
    )
    rules: list[TaxRulePrediction]
    reasoning: str = Field(description="Why these rules were chosen for this user")


class PayrollTaxEstimate(BaseModel):
    """AI-estimated effective payroll tax rate for a country + income level."""

    estimated_rate: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="How the rate was determined")


class BulkPredictionResponse(BaseModel):
    """Combined response for accounts and categories."""

    accounts: list[AccountPrediction]
    categories: list[CategoryPrediction]


class AIAssistant:
    """Financial assistant powered by LLM to classify accounts and categories."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize the AI assistant with API credentials."""
        self.api_key = api_key or settings_manager.ai_api_key
        self.base_url = (
            base_url or settings_manager.ai_base_url or AIConfig.DEFAULT_BASE_URL
        )
        self.model = model or settings_manager.ai_model or AIConfig.DEFAULT_MODEL

        if not self.api_key:
            self.client = None
        else:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    @property
    def _is_deepseek(self) -> bool:
        """Returns True if the current model is a DeepSeek model."""
        return "deepseek" in self.model.lower()

    def _get_completion_kwargs(self) -> dict[str, Any]:
        """Returns extra keyword arguments for the completion call."""
        kwargs: dict[str, Any] = {}
        if self._is_deepseek:
            # DeepSeek V4 Pro / Flash optimized settings
            kwargs["reasoning_effort"] = "high"
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        return kwargs

    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        response_format: type[BaseModel],
    ) -> Any | None:
        """Helper to call LLM and handle structured output parsing."""
        if not self.client:
            return None

        # Cast messages to satisfy type checker for OpenAI SDK
        typed_messages: Any = messages

        try:
            if self._is_deepseek:
                # DeepSeek doesn't support json_schema (Structured Outputs)
                # used by .parse(). Fall back to .create() with json_object mode.
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=typed_messages,
                    response_format={"type": "json_object"},
                    **self._get_completion_kwargs(),
                )
                content = response.choices[0].message.content
                if not content:
                    return None
                return response_format.model_validate_json(content)

            # OpenAI supports Structured Outputs via the .parse() helper
            response = self.client.beta.chat.completions.parse(
                model=self.model,
                messages=typed_messages,
                response_format=response_format,
                **self._get_completion_kwargs(),
            )
            return response.choices[0].message.parsed
        except Exception as e:
            logger.error(f"AI API Error ({self.model}): {e}")
            return None

    def is_available(self) -> bool:
        """Checks if AI service is configured and ready."""
        return self.client is not None

    def parse_structured(
        self,
        messages: list[dict[str, Any]],
        response_format: type[BaseModel],
    ) -> Any | None:
        """Parse an LLM response into a structured Pydantic model.

        Public wrapper around _call_llm for use by other components
        (e.g. OptimChatEngine).
        """
        return self._call_llm(messages, response_format)

    def stream_chat(
        self,
        console: Console,
        messages: list[dict[str, Any]],
        lang: dict[str, str],
    ) -> str | None:
        """Stream an LLM response with live Markdown rendering.

        Public wrapper around _stream_response for use by other components.
        """
        return self._stream_response(console, messages, lang)

    @contextlib.contextmanager
    def _tty_cbreak(self) -> Any:
        """Context manager to temporarily set TTY to cbreak mode."""
        import termios
        import tty

        fd = sys.stdin.fileno()
        is_tty = sys.stdin.isatty()
        old_settings = None
        if is_tty:
            try:
                old_settings = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            except Exception:
                is_tty = False

        try:
            yield is_tty
        finally:
            if is_tty and old_settings:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    def _stream_response(
        self,
        console: Console,
        messages: list[dict[str, Any]],
        lang: dict[str, str],
    ) -> str | None:
        """Stream an LLM response with live Markdown rendering."""
        try:
            stream = self.client.chat.completions.create(  # type: ignore[union-attr]
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
        except Exception as e:
            label = lang.get("chat_conn_error", "Connection error:")
            console.print(f"[error]{label}[/error] {e}")
            return None

        thinking = f" {lang.get('chat_thinking', 'Thinking...')}"
        full_response = ""
        interrupted = False
        interrupt_hint = lang.get("chat_interrupt_hint", "Press [Esc] to stop")

        def _build_status(spinner_idx: int) -> Text:
            spinner = _SPINNER_CHARS[spinner_idx % len(_SPINNER_CHARS)]
            return Text.assemble(
                (f"{spinner}{thinking}", "meta"),
                (f"  ({interrupt_hint})", "dim"),
            )

        with self._tty_cbreak() as is_tty:
            with Live(_build_status(0), refresh_per_second=10, console=console) as live:
                i = 0
                for chunk in stream:
                    if is_tty:
                        import select

                        rlist, _, _ = select.select([sys.stdin], [], [], 0)
                        if rlist and sys.stdin.read(1) == "\x1b":
                            interrupted = True
                            break

                    # mypy: ignore
                    chunk_any: Any = chunk
                    content = chunk_any.choices[0].delta.content or ""
                    full_response += content
                    i += 1
                    if full_response:
                        live.update(Markdown(full_response))
                    else:
                        live.update(_build_status(i))

                if interrupted:
                    label = lang.get("chat_interrupted", "Interrupted.")
                    interrupted_text = Text.assemble(
                        (full_response, ""),
                        ("\n\n", ""),
                        (f"{label}", "dim"),
                    )
                    live.update(interrupted_text)

        return full_response

    def _print_banner(
        self,
        console: Console,
        stats: dict[str, Any] | None,
        lang: dict[str, str],
    ) -> None:
        """Print the session header — called at start and on /clear."""
        console.print()
        header = Text.assemble(
            ("✦", "accent"),
            (f" {lang.get('chat_brand', 'PROSPERE ANALYST')}", "bold"),
        )
        console.print(header)
        if stats:
            metrics = Text.assemble(
                (" ", ""),
                (lang.get("chat_success", "success"), "meta"),
                ("  ", ""),
                (f"{stats.get('success_rate', 0):.1f}%", ""),
                ("   ·   ", ""),
                (lang.get("chat_wealth", "wealth"), "meta"),
                ("  ", ""),
                (f"{stats.get('final_wealth', '€0')}", ""),
                ("   ·   ", ""),
                (lang.get("chat_cagr", "cagr"), "meta"),
                ("  ", ""),
                (f"{stats.get('cagr', '0%')}", ""),
                ("   ·   ", ""),
                (lang.get("chat_fire", "Coast"), "meta"),
                ("  ", ""),
                (f"{stats.get('coast_fire', 'N/A')}", ""),
            )
            console.print(metrics)
            metrics2 = Text.assemble(
                (" ", ""),
                (lang.get("chat_rigidity", "rigid"), "meta"),
                ("  ", ""),
                (f"{stats.get('rigidity', '-')}", ""),
                ("   ·   ", ""),
                (lang.get("chat_shock", "crash"), "meta"),
                ("  ", ""),
                (f"{stats.get('shock_crash', '-')}", ""),
                ("   ·   ", ""),
                (lang.get("chat_stress", "stress"), "meta"),
                ("  ", ""),
                (f"{stats.get('stress_mo', '-')}", ""),
            )
            console.print(metrics2)
        line = _SEPARATOR * min(console.width, 60)
        console.print(Text(line, style="meta"))
        help_text = lang.get(
            "chat_help", "Ask questions about your simulation results."
        )
        console.print(f"[meta]{help_text}[/meta]\n")

    @staticmethod
    def _is_exit_command(text: str) -> bool:
        return text.lower() in ("exit", "quit", "/exit", "/quit", "退出")

    @staticmethod
    def _is_clear_command(text: str) -> bool:
        return text.lower() in ("clear", "/clear", "清除")

    def _process_turn(
        self,
        console: Console,
        messages: list[dict[str, Any]],
        chat_history: list[dict[str, str]],
        lang: dict[str, str],
        user_input: str,
    ) -> None:
        """Send a user message to the LLM and stream the response back."""
        messages.append({"role": "user", "content": user_input})
        chat_history.append({"role": "user", "content": user_input})

        console.print()
        full_response = self._stream_response(console, messages, lang)
        if full_response is None:
            messages.pop()
            chat_history.pop()
            return

        messages.append({"role": "assistant", "content": full_response})
        chat_history.append({"role": "assistant", "content": full_response})

    def _handle_chat_input(self, console: Console) -> str:
        """Prompts for and formats user input."""
        user_input = input(_PROMPT).strip()
        if user_input:
            sys.stdout.write("\033[A\r\033[K")
            prefix = Text(_USER_BORDER_CHAR, style=_USER_BORDER_STYLE)
            console.print(prefix + Text(user_input))
        return user_input

    def _handle_chat_cycle(
        self,
        console: Console,
        messages: list[dict[str, Any]],
        chat_history: list[dict[str, str]],
        lang: dict[str, str],
        stats: dict[str, Any] | None,
    ) -> bool:
        """Processes a single chat cycle. Returns False if the session should end."""
        try:
            console.print()
            user_input = self._handle_chat_input(console)
            if not user_input:
                return True
            if self._is_exit_command(user_input):
                return False
            if self._is_clear_command(user_input):
                console.clear()
                self._print_banner(console, stats, lang)
                return True

            self._process_turn(console, messages, chat_history, lang, user_input)

            try:
                readline.write_history_file(_HISTORY_FILE)
            except Exception:
                logger.debug("Could not write chat history", exc_info=True)
            return True

        except (KeyboardInterrupt, EOFError):
            console.print()
            return False
        except Exception as e:
            label = lang.get("chat_error", "Error:")
            console.print(f"\n[error]{label}[/error] {e}")
            return True

    def interactive_chat(
        self,
        system_prompt: str,
        stats: dict[str, Any] | None = None,
        lang_dict: dict[str, str] | None = None,
    ) -> None:
        """Start an interactive analyst chat session."""
        lang = lang_dict or {}
        if not self.client:
            msg = lang.get(
                "chat_no_api", "AI service not configured. Check your API key."
            )
            print(msg)
            return

        console = Console(theme=CHAT_THEME, highlight=False)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        chat_history: list[dict[str, str]] = []

        try:
            if os.path.exists(_HISTORY_FILE):
                readline.read_history_file(_HISTORY_FILE)
        except Exception:
            logger.debug("Could not read chat history", exc_info=True)

        self._print_banner(console, stats, lang)

        while self._handle_chat_cycle(console, messages, chat_history, lang, stats):
            pass

        console.print(f"\n[meta]{lang.get('chat_exit', 'Session ended.')}[/meta]")

    def classify_entities(
        self,
        accounts_metadata: list[dict[str, Any]],
        categories_metadata: list[dict[str, Any]],
    ) -> BulkPredictionResponse | None:
        """Fetches batch classifications for accounts and categories."""
        if not self.client:
            return None

        account_predictions: list[AccountPrediction] = []
        if accounts_metadata:
            account_predictions = self._fetch_account_classifications(accounts_metadata)

        category_predictions: list[CategoryPrediction] = []
        if categories_metadata:
            category_predictions = self._fetch_category_classifications(
                categories_metadata
            )

        return BulkPredictionResponse(
            accounts=account_predictions, categories=category_predictions
        )

    def model_life_stage(
        self,
        income_summary: dict[str, Any],
        expense_summary: dict[str, Any],
        profile_context: dict[str, str] | None = None,
    ) -> LifeStageModeling | None:
        """Infers life stage and dynamic growth curves from financial summaries."""
        prompt = self._build_life_stage_prompt(
            income_summary, expense_summary, profile_context
        )
        messages = [
            {
                "role": "system",
                "content": PromptLoader.load("system", "analyst"),
            },
            {"role": "user", "content": prompt},
        ]

        parsed = self._call_llm(messages, LifeStageModeling)
        if isinstance(parsed, LifeStageModeling):
            return parsed
        return None

    def build_tax_rules(
        self,
        country: str,
        accounts: list[dict[str, Any]],
        tax_expense_categories: list[str] | None = None,
    ) -> TaxRulesConfig | None:
        """Infers capital gains tax rules based on country and account types."""
        account_lines = []
        for acc in accounts:
            account_lines.append(
                f"    - {acc.get('name', acc.get('account', 'Unknown'))}: "
                f"type={acc.get('account_type', acc.get('type', 'unknown'))}"
            )

        prompt = PromptLoader.load("user", "tax_rules").format(
            country=country,
            accounts_summary="\n".join(account_lines),
            tax_expense_categories=", ".join(tax_expense_categories)
            if tax_expense_categories
            else "None detected",
        )

        messages = [
            {"role": "system", "content": PromptLoader.load("system", "planner")},
            {"role": "user", "content": prompt},
        ]

        parsed = self._call_llm(messages, TaxRulesConfig)
        if isinstance(parsed, TaxRulesConfig):
            return parsed
        return None

    def estimate_effective_payroll_tax(
        self,
        country: str,
        monthly_income: float,
    ) -> PayrollTaxEstimate | None:
        """Estimates effective payroll tax rate for a country + income level."""
        prompt = PromptLoader.load("user", "payroll_tax").format(
            country=country,
            monthly_income=f"{monthly_income:,.0f}",
        )

        messages = [
            {"role": "system", "content": PromptLoader.load("system", "planner")},
            {"role": "user", "content": prompt},
        ]

        parsed = self._call_llm(messages, PayrollTaxEstimate)
        if isinstance(parsed, PayrollTaxEstimate):
            return parsed
        return None

    def _fetch_account_classifications(
        self, accounts_metadata: list[dict[str, Any]]
    ) -> list[AccountPrediction]:
        """Performs API call for account classification."""
        prompt = self._build_account_prompt(accounts_metadata)
        messages = [
            {
                "role": "system",
                "content": PromptLoader.load("system", "analyst"),
            },
            {"role": "user", "content": prompt},
        ]

        parsed_data = self._call_llm(messages, AccountPredictionList)
        return parsed_data.predictions if parsed_data else []

    def _fetch_category_classifications(
        self, categories_metadata: list[dict[str, Any]]
    ) -> list[CategoryPrediction]:
        """Performs API call for category classification."""
        prompt = self._build_category_prompt(categories_metadata)
        messages = [
            {
                "role": "system",
                "content": PromptLoader.load("system", "planner"),
            },
            {"role": "user", "content": prompt},
        ]

        parsed_data = self._call_llm(messages, CategoryPredictionList)
        return parsed_data.predictions if parsed_data else []

    def _build_account_prompt(self, accounts_metadata: list[dict[str, Any]]) -> str:
        """Constructs the prompt for account classification."""
        types_desc = ", ".join([f"'{t.value}'" for t in AccountType])
        account_lines = []
        for acc in accounts_metadata:
            line = f"- {acc['name']} ({acc['balance']} {acc['currency']})"
            account_lines.append(line)

        template = PromptLoader.load("user", "classify_accounts")
        return template.format(
            types=types_desc,
            savings_min=SimulationDefaults.SAVINGS_RETURN_RATE,
            savings_max=SimulationDefaults.HIGH_INTEREST_SAVINGS_RATE,
            invest_min=SimulationDefaults.INVESTMENT_RETURN_RATE,
            accounts="\n".join(account_lines),
        )

    def _build_category_prompt(self, categories_metadata: list[dict[str, Any]]) -> str:
        """Constructs the prompt for category classification."""
        roles_desc = ", ".join([f"'{r.value}'" for r in FinancialRole])
        levels_desc = ", ".join([f"'{level.value}'" for level in NecessityLevel])

        category_lines = []
        for cat in categories_metadata:
            avg = cat["avg_monthly"]
            sign = "+" if avg > 0 else "-"
            rec_hint = (
                "Statistically Recurring" if cat.get("stat_recurring") else "Irregular"
            )
            line = f"- {cat['name']} ({sign}{abs(avg):.2f}/mo, {rec_hint})"
            category_lines.append(line)
            for sub in cat.get("sub_categories", []):
                category_lines.append(f"  └─ {sub}")

        template = PromptLoader.load("user", "classify_categories")
        return template.format(
            roles=roles_desc,
            levels=levels_desc,
            categories="\n".join(category_lines),
        )

    def _build_life_stage_prompt(
        self,
        income_summary: dict[str, Any],
        expense_summary: dict[str, Any],
        profile_context: dict[str, str] | None = None,
    ) -> str:
        """Constructs the prompt for life stage and growth modeling."""
        context_lines = []
        if profile_context:
            for key, value in profile_context.items():
                if value:
                    # Format key: 'family_status' -> 'Family Status'
                    label = key.replace("_", " ").title()
                    context_lines.append(f"- {label}: {value}")

        context_str = "\n".join(context_lines)
        if context_str:
            context_str = "\nUSER BACKGROUND:\n" + context_str

        template = PromptLoader.load("user", "life_stage_modeling")
        return template.format(
            income_avg=income_summary.get("avg_monthly", 0.0),
            income_stability=income_summary.get("stability", "Unknown"),
            expense_avg=expense_summary.get("avg_monthly", 0.0),
            expense_flexibility=expense_summary.get("flexibility_avg", 3.0),
            context=context_str,
        )
