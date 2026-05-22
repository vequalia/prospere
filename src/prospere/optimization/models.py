from typing import Literal

from pydantic import BaseModel, Field


class CategoryAdjustment(BaseModel):
    """A single category adjustment parsed from natural language.

    Supports top-level categories (e.g. "Dining") and subcategories
    via ``::`` delimiter (e.g. "Dining::Restaurants"). If only
    ``matched_category`` is set, the adjustment applies to the whole
    category.  If ``subcategory_name`` is also set, the adjustment
    targets only that subcategory.
    """

    user_category_name: str = Field(
        description="Category name as mentioned by the user"
    )
    matched_category: str = Field(
        description="Exact parent category name found in the financial profile"
    )
    subcategory_name: str | None = Field(
        default=None,
        description="Subcategory name (e.g. 'Restaurants'), None = whole category",
    )
    adjustment_type: Literal["percentage", "absolute"] = Field(
        description="'percentage' for -20%, 'absolute' for -200"
    )
    adjustment_value: float = Field(description="Negative = cut, positive = increase")
    duration: str | None = Field(
        default=None,
        description="Optional time frame (e.g. 'one year', 'six months')",
    )


class OptimIntent(BaseModel):
    """Parsed optimization intent from natural language.

    Designed for extensibility: new intent types can be added by extending
    the ``intent_type`` literal and adding corresponding optional fields.
    """

    intent_type: Literal["what_if", "efficient_frontier", "general_question"] = Field(
        description="The type of optimization request"
    )
    reasoning: str = Field(
        default="",
        description="Brief reasoning about how the intent was understood",
    )
    language: str = Field(
        default="en",
        description="Detected language: 'en' or 'zh'",
    )

    # What-if specific
    adjustments: list[CategoryAdjustment] = Field(
        default_factory=list,
        description="Budget adjustments (what_if only)",
    )

    # Efficient frontier specific
    target_wealth: float | None = Field(
        default=None,
        description="Target wealth goal (efficient_frontier only)",
    )
    max_qol_loss: float | None = Field(
        default=None,
        description="Maximum acceptable QoL loss % for reverse frontier",
    )
    strategy_preference: str | None = Field(
        default=None,
        description="'optimal', 'balanced', 'aggressive', or None for all",
    )
    time_extension: int | None = Field(
        default=None,
        description="Years to extend beyond current scenario",
    )

    # General question
    question_text: str = Field(
        default="",
        description="User's question for general chat",
    )
