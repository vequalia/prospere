from dataclasses import dataclass, field

import numpy as np

from prospere.core.constants import AccountType, NecessityLevel


@dataclass(frozen=True)
class SubCategoryStats:
    """Historical statistics and behavioral metadata for a specific sub-category."""

    name: str
    mean: float
    std: float
    is_income: bool
    is_recurring: bool = False
    flexibility_score: int = 3
    necessity_level: NecessityLevel = NecessityLevel.DISCRETIONARY
    annual_growth_rate: float | None = None
    income_linked_rate: float | None = None
    shock_events: list[dict] = field(default_factory=list)
    projected_values: list[float] | None = None


@dataclass(frozen=True)
class CategoryStats:
    """Historical statistics and behavioral metadata for a high-level category."""

    name: str
    mean: float
    std: float
    is_income: bool
    sub_categories: list[SubCategoryStats] = field(default_factory=list)
    is_recurring: bool = False
    flexibility_score: int = 3
    necessity_level: NecessityLevel = NecessityLevel.DISCRETIONARY
    annual_growth_rate: float = 0.0
    income_linked_rate: float = 0.0
    shock_events: list[dict] = field(default_factory=list)
    projected_values: list[float] | None = None


@dataclass(frozen=True)
class AccountStats:
    """Statistical snapshot of a financial account's performance and strategy."""

    name: str
    account_type: AccountType
    annual_return: float
    monthly_net_flow_mean: float
    monthly_net_flow_std: float
    allocation_ratio: float = 0.0
    annual_return_std: float = 0.0
    max_balance: float = float("inf")
    deposit_priority: int = 100  # Lower is higher priority
    initial_balance: float = 0.0
    currency: str = "EUR"
    asset_class: str = ""


@dataclass(frozen=True)
class FinancialProfile:
    """A comprehensive financial baseline derived from historical behavior."""

    monthly_income_mean: float
    monthly_income_std: float
    monthly_expense_mean: float
    monthly_expense_std: float
    currency: str
    categories: list[CategoryStats]
    accounts: list[AccountStats]


@dataclass(frozen=True)
class DynamicGrowth:
    """Parametric growth model transitioning from initial to terminal rate."""

    initial_rate: float
    terminal_rate: float
    transition_years: int


@dataclass(frozen=True)
class TaxRule:
    """A single tax rule applied to a specific tax base."""

    name: str
    base: str
    rate: float
    exempt_accounts: list[str] = field(default_factory=list)
    deduct_from: str = "account"
    apply_only_to_positive: bool = True
    timing: str = "monthly"


@dataclass(frozen=True)
class MarketAssumptions:
    """Assumptions for market behavior: correlations and mean reversion."""

    mean_reversion_enabled: bool = False
    mean_reversion_decay: float = -3.0
    asset_correlations: dict[str, dict[str, float]] = field(default_factory=dict)
    long_term_returns: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class GrowthPolicy:
    """Policy for projected growth of income and expenses."""

    default_expense_growth: float
    default_income_growth: float
    inflation_rate: float = 0.02
    category_overrides: dict[str, float] = field(default_factory=dict)
    dynamic_income_growth: DynamicGrowth | None = None
    dynamic_expense_growth: DynamicGrowth | None = None


@dataclass(frozen=True)
class ScenarioMetadata:
    """Metadata and configuration for a specific simulation scenario."""

    name: str
    initial_capital: float
    years: int
    iterations: int
    currency: str = "EUR"
    start_date: str | None = None
    end_date: str | None = None
    growth_policy: GrowthPolicy | None = None
    taxable_income_categories: list[str] = field(default_factory=list)
    tax_categories: list[str] = field(default_factory=list)
    tax_rules: list[TaxRule] = field(default_factory=list)
    estimated_effective_tax_rate: float | None = None
    market_assumptions: MarketAssumptions | None = None
    snapshot_name: str = "default"


@dataclass(frozen=True)
class SimulationParams:
    """Parameters passed to the simulation engine."""

    initial_capital: float
    years: int
    iterations: int
    profile: FinancialProfile
    growth_policy: GrowthPolicy
    scenario_metadata: ScenarioMetadata


@dataclass(frozen=True)
class SimulationResult:
    """Comprehensive results of a multi-iteration Monte Carlo simulation."""

    percentile_10: np.ndarray
    percentile_50: np.ndarray
    percentile_90: np.ndarray
    success_rate: float
    present_value_50: np.ndarray
    passive_income_coverage_50: np.ndarray
    final_wealth_distribution: np.ndarray

    # Median path histories
    account_histories_50: dict[str, np.ndarray]
    net_cash_flow_50: np.ndarray
    monthly_tax_history_50: np.ndarray

    # Aggregate metrics
    cumulative_tax_paid_50: float
    effective_tax_rate: float
    earliest_failure_year: float | None = None

    # Portfolio composition (median path)
    portfolio_mix_50: dict[str, np.ndarray] = field(default_factory=dict)

    # Diagnostics & Strategic Insights
    liquidity_stress_months: int = 0
    account_saturation_months: dict[str, int] = field(default_factory=dict)
    account_roi_contribution: dict[str, float] = field(default_factory=dict)
    essential_expense_ratio: float = 0.0
    total_income_median: float = 0.0
    total_expenses_median: float = 0.0
    monthly_income_history_50: np.ndarray = field(default_factory=lambda: np.array([]))
    monthly_expenses_history_50: np.ndarray = field(
        default_factory=lambda: np.array([])
    )
    monthly_gains_history_50: np.ndarray = field(default_factory=lambda: np.array([]))
    shock_crash_months_median: int = 0
    shock_income_loss_months_median: int = 0
    shock_expense_spike_months_median: int = 0
    shock_crash_iter_pct: float = 0.0
    shock_income_loss_iter_pct: float = 0.0
    shock_expense_spike_iter_pct: float = 0.0
    shock_crash_avg_duration: float = 0.0
    shock_income_avg_duration: float = 0.0
    shock_spike_avg_duration: float = 0.0
