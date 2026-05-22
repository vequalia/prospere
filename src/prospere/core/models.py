from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Transaction:
    """
    Standardized record of a financial transaction.
    """

    unique_id: str
    transaction_date: date
    amount: float
    currency: str
    primary_category: str
    secondary_category: str
    account_name: str


@dataclass(frozen=True)
class AccountBalance:
    """
    Represents the current balance of a specific account at the time of export.
    """

    account_name: str
    balance: float
    currency: str


@dataclass(frozen=True)
class Identity:
    """Global user profile for cross-scenario consistency."""

    name: str = "Default User"
    age: str = ""
    industry: str = ""
    location: str = ""
    family_status: str = ""
    financial_goal: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "age": self.age,
            "industry": self.industry,
            "location": self.location,
            "family_status": self.family_status,
            "financial_goal": self.financial_goal,
        }


@dataclass(frozen=True)
class WorkspaceContext:
    """Current active user and dataset context."""

    user: str = "default_user"
    snapshot: str | None = None
    scenario: str | None = None
