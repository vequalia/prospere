import os
from enum import Enum
from typing import Final


class FinancialRole(Enum):
    """Defines the primary role of a financial entry."""

    INCOME = "income"
    EXPENSE = "expense"
    IGNORE = "ignore"


class AccountType(Enum):
    """Types of financial accounts supported by the system."""

    CASH = "cash"
    SAVINGS = "savings"
    INVESTMENT = "investment"
    CREDIT = "credit"
    DEBT = "debt"
    LOCKED = "locked"
    IGNORE = "ignore"


class AssetClass(Enum):
    """Asset classes for portfolio simulation and correlation modeling."""

    EQUITY = "equity"
    BOND = "bond"
    MIXED = "mixed"
    SAVINGS = "savings"
    CASH = "cash"


class NecessityLevel(Enum):
    """Categorization of expenses based on life priority."""

    STRICT = "strict"
    ESSENTIAL = "essential"
    FLEXIBLE = "flexible"
    DISCRETIONARY = "discretionary"


class OptimizationBoundLevels:
    """Defined budget cut limits based on flexibility and necessity."""

    STRICT: Final = 0.0
    LOW: Final = 0.15
    MODERATE: Final = 0.30
    FLEXIBLE: Final = 0.50
    HIGH: Final = 0.80


class OptimizationDefaults:
    """Default labels and thresholds for the optimization engine."""

    STRATEGY_OPTIMAL: Final = "Optimal"
    STRATEGY_BALANCED: Final = "Balanced"
    STRATEGY_AGGRESSIVE: Final = "Aggressive"

    # Flexibility score cutoffs for bound selection
    FLEXIBILITY_LOW_MAX: Final = 3
    FLEXIBILITY_MODERATE_MAX: Final = 5
    FLEXIBILITY_FLEXIBLE_MAX: Final = 7

    # QoL Loss weights
    QOL_WEIGHT_BASE: Final = 11

    # Default bounds mapping
    DEFAULT_BOUNDS_RULES: Final = {
        "level_strict": OptimizationBoundLevels.STRICT,
        "level_low": OptimizationBoundLevels.LOW,
        "level_moderate": OptimizationBoundLevels.MODERATE,
        "level_flexible": OptimizationBoundLevels.FLEXIBLE,
        "level_high": OptimizationBoundLevels.HIGH,
    }


class WorkspaceConfig:
    """Settings for the multi-user workspace structure."""

    ROOT_DIR: Final = os.path.expanduser(
        os.getenv("PROSPERE_DATA_ROOT", "~/.prospere/workspaces")
    )
    IDENTITY_FILE: Final = "identity.json"
    RAW_DIR: Final = "raw"
    DATASETS_DIR: Final = "datasets"
    SCENARIOS_DIR: Final = "scenarios"
    SIMULATION_DIR: Final = "scenarios/simulation"
    OPTIMIZATION_DIR: Final = "scenarios/optimization"
    ARCHIVE_DIR: Final = "scenarios/archive"

    RAW_CSV_FILENAME: Final = "moneywiz.csv"
    PROCESSED_TX_FILENAME: Final = "processed_transactions.xlsx"
    PROCESSED_BAL_FILENAME: Final = "processed_balances.json"


class PathConfig:
    """Paths for data files and directories."""

    DATA_DIR: Final = os.path.expanduser(
        os.getenv("PROSPERE_DATA_ROOT", "~/.prospere/data")
    )
    BASE_SCENARIOS_DIR: Final = "scenarios"
    SIM_SCENARIOS_DIR: Final = "scenarios/simulation"
    OPT_SCENARIOS_DIR: Final = "scenarios/optimization"

    INPUT_DIR: Final = "data/moneywiz_input"

    DEFAULT_INPUT_FILE: Final = "data/moneywiz_input/mib_moneywiz_input.csv"
    PROCESSED_TRANSACTIONS: Final = "data/processed_transactions.xlsx"
    PROCESSED_BALANCES: Final = "data/processed_balances.json"

    CATEGORY_CONFIG: Final = "category_config.json"
    ACCOUNT_CONFIG: Final = "account_config.json"
    SCENARIO_METADATA: Final = "scenario.json"


class SimulationDefaults:
    """Default parameters for Monte Carlo simulations."""

    DEFAULT_SCENARIO_NAME: Final = "my_scenario"
    ITERATIONS: Final = 10000
    YEARS: Final = 10
    MONTHS_PER_YEAR: Final = 12

    # Default Growth Rates
    DEFAULT_INCOME_GROWTH: Final = 0.08
    DEFAULT_EXPENSE_GROWTH: Final = 0.03
    DEFAULT_INFLATION_RATE: Final = 0.02

    # Statistical Thresholds
    RECURRING_THRESHOLD: Final = 0.7  # Category presence in >70% of months
    MIN_MONTHS_FOR_ML: Final = 6

    # Return Rates
    RETURN_MEAN_DEFAULT: Final = 0.05
    RETURN_STD_DEFAULT: Final = 0.15
    SAVINGS_RETURN_RATE: Final = 0.01
    INVESTMENT_RETURN_RATE: Final = 0.07
    HIGH_INTEREST_SAVINGS_RATE: Final = 0.03

    DYNAMIC_GROWTH_DECAY: Final = -3.0
    MEAN_REVERSION_DECAY: Final = -3.0

    DEFAULT_ASSET_CORRELATIONS: Final = {
        AssetClass.EQUITY.value: {
            AssetClass.EQUITY.value: 0.85,
            AssetClass.BOND.value: 0.10,
            AssetClass.MIXED.value: 0.50,
            AssetClass.SAVINGS.value: 0.05,
        },
        AssetClass.BOND.value: {
            AssetClass.EQUITY.value: 0.10,
            AssetClass.BOND.value: 0.40,
            AssetClass.MIXED.value: 0.30,
            AssetClass.SAVINGS.value: 0.15,
        },
        AssetClass.MIXED.value: {
            AssetClass.EQUITY.value: 0.50,
            AssetClass.BOND.value: 0.30,
            AssetClass.MIXED.value: 0.60,
            AssetClass.SAVINGS.value: 0.10,
        },
        AssetClass.SAVINGS.value: {
            AssetClass.EQUITY.value: 0.05,
            AssetClass.BOND.value: 0.15,
            AssetClass.MIXED.value: 0.10,
            AssetClass.SAVINGS.value: 0.01,
        },
    }
    DEFAULT_LONG_TERM_RETURNS: Final = {
        AssetClass.EQUITY.value: 0.07,
        AssetClass.BOND.value: 0.03,
        AssetClass.MIXED.value: 0.05,
        AssetClass.SAVINGS.value: 0.01,
    }
    DEFAULT_SAVINGS_VOLATILITY: Final = 0.005
    CHOLESKY_STABILIZATION: Final = 1e-9

    PRIORITY_DEBT_REPAYMENT: Final = 10
    PRIORITY_SAVINGS_BUFFER: Final = 20
    PRIORITY_STANDARD_INVESTMENT: Final = 50
    PRIORITY_LOWEST_OVERFLOW: Final = 100

    T_DIST_DF: Final = 5
    T_DIST_DF_FIELD: Final = "t_dist_df"

    FX_VOLATILITY_ANNUAL: Final = 0.08
    FX_VOLATILITY_EXCLUDED: Final = frozenset({"ILS"})

    CREDIT_REVOLVING_SHARE: Final = 0.30

    SHOCK_MARKET_CRASH_MONTHLY_PROB: Final = 0.017
    SHOCK_MARKET_CRASH_RETURN_MEAN: Final = -0.06
    SHOCK_MARKET_CRASH_RETURN_STD: Final = 0.04
    SHOCK_MARKET_CRASH_VOL_MULTIPLIER: Final = 2.5
    SHOCK_MARKET_CRASH_EXIT_BASE: Final = 0.05
    SHOCK_MARKET_CRASH_EXIT_MAX: Final = 0.30
    SHOCK_MARKET_CRASH_EXIT_DECAY: Final = 0.15
    SHOCK_MARKET_CRASH_COOLDOWN_MONTHS: Final = 12
    SHOCK_MARKET_CRASH_COOLDOWN_MULTIPLIER: Final = 0.1

    SHOCK_INCOME_LOSS_MONTHLY_PROB: Final = 0.003
    SHOCK_INCOME_LOSS_EXIT_MONTHLY_PROB: Final = 0.167
    SHOCK_INCOME_LOSS_FRACTION: Final = 0.60
    SHOCK_INCOME_LOSS_COOLDOWN_MONTHS: Final = 24
    SHOCK_INCOME_LOSS_COOLDOWN_MULTIPLIER: Final = 0.1

    SHOCK_EXPENSE_SPIKE_MONTHLY_PROB: Final = 0.015
    SHOCK_EXPENSE_SPIKE_EXIT_MONTHLY_PROB: Final = 1.0
    SHOCK_EXPENSE_SPIKE_MULTIPLIER: Final = 3.0

    SHOCK_CRASH_CORRELATED_INCOME_MULTIPLIER: Final = 3.0

    SUBCATEGORY_DELIMITER: Final = "::"


class MLForecastingConfig:
    """Configuration for Prophet-based ML forecasting."""

    GROWTH_MODE: Final = "flat"
    SEASONALITY_MODE: Final = "multiplicative"
    FOURIER_ORDER_NORMAL: Final = 10
    FOURIER_ORDER_SPIKE: Final = 25
    SPIKE_SENSITIVE_KEYWORDS: Final = frozenset({"provision", "taxes", "tax"})
    RECURRENCE_CONFIDENCE_THRESHOLD: Final = 0.4
    OUTLIER_PERCENTILE: Final = 98
    OUTLIER_MAD_MULTIPLIER_NORMAL: Final = 3.0
    OUTLIER_MAD_MULTIPLIER_SPIKE: Final = 10.0


class AIConfig:
    """Settings for the AI Assistant."""

    DEFAULT_MODEL: Final = "gpt-5-mini"
    DEFAULT_BASE_URL: Final = "https://api.openai.com/v1"

    # Environment Variable Keys
    API_KEY_ENV_VAR: Final = "PROSPERE_AI_API_KEY"
    BASE_URL_ENV_VAR: Final = "PROSPERE_AI_BASE_URL"
    MODEL_ENV_VAR: Final = "PROSPERE_AI_MODEL"


class ExchangeRates:
    """Currency exchange rates relative to EUR."""

    BASE_CURRENCY: Final = "EUR"
    RATES: Final = {
        "EUR": 1.0,
        "USD": 0.92,  # 1 USD = 0.92 EUR
        "CNY": 0.13,  # 1 CNY = 0.13 EUR
        "ILS": 0.004,
        "Unknown": 1.0,
    }


class CLIConfig:
    """Settings for the Command Line Interface."""

    TABLE_WIDTH: Final = 80
    MIN_WEALTH_DISPLAY: Final = 0.01
    INFINITY_SYMBOL: Final = "      ∞  "
    MAX_BALANCE_THRESHOLD: Final = 1e12
    TOP_CATEGORIES_COUNT: Final = 8
    HISTOGRAM_BINS: Final = 10

    # Numeric formatting thresholds
    MILLION: Final = 1_000_000
    THOUSAND: Final = 1_000


class BootstrapConstants:
    """Strings and labels for the bootstrap interactive flow."""

    SCOPE_PRIMARY_ONLY: Final = "Primary Categories Only"
    SCOPE_DETAILED_SUBS: Final = "Detailed Sub-categories"
    SCOPE_SKIP: Final = "Skip Category Filtering"

    DEPTH_CHOICES: Final = (
        SCOPE_PRIMARY_ONLY,
        SCOPE_DETAILED_SUBS,
        SCOPE_SKIP,
    )

    STABILITY_HIGH: Final = "High"
    STABILITY_MODERATE: Final = "Moderate"

    STEP_SCOPE: Final = "Step 1/7: Scope Selection"
    STEP_AUDIT: Final = "Step 2/7: Baseline Audit"
    STEP_PARAMS: Final = "Step 3/7: Basic Parameters"
    STEP_ACCOUNTS: Final = "Step 4/7: Account Setup"
    STEP_CATEGORIES: Final = "Step 5/7: Category Setup"
    STEP_GROWTH: Final = "Step 6/7: Growth & Inflation"
    STEP_TAX: Final = "Step 7/7: Tax Configuration"


class MoneyWizConstants:
    """Constants specific to MoneyWiz data ingestion."""

    SOURCE_NAME: Final = "moneywiz"
    ROW_SEPARATOR: Final = "sep="
    DATE_FORMAT: Final = "%Y/%m/%d"
    CATEGORY_DELIMITER: Final = " ► "
    UNKNOWN_CURRENCY: Final = "Unknown"
    DEFAULT_CATEGORY: Final = "Uncategorized"

    # CSV Column Names
    COL_NAME: Final = "Name"
    COL_TRANSFERS: Final = "Transfers"
    COL_ACCOUNT: Final = "Account"
    COL_DATE: Final = "Date"
    COL_TIME: Final = "Time"
    COL_AMOUNT: Final = "Amount"
    COL_CURRENCY: Final = "Currency"
    COL_CATEGORY: Final = "Category"
    COL_DESCRIPTION: Final = "Description"
    COL_CURRENT_BALANCE: Final = "Current balance"


class UITheme:
    """Shared warm-gold palette for CLI (chat & menu).

    Keep in sync with the ANSI prompt constant in assistant.py when changing accent.
    """

    ACCENT: Final = "#d4a853"
    META: Final = "#98989d"
    SUCCESS: Final = "#4a9d5a"
    WARNING: Final = "#c4953a"
    ERROR: Final = "#c95a5a"

    THEME_DICT: Final = {
        "accent": f"bold {ACCENT}",
        "meta": f"dim {META}",
        "success": f"bold {SUCCESS}",
        "warning": f"bold {WARNING}",
        "error": f"bold {ERROR}",
    }


class HealthThresholds:
    """Thresholds for color-coded health indicators in reports."""

    SUCCESS_STRONG: Final = 0.90
    SUCCESS_MODERATE: Final = 0.70
    COVERAGE_STRONG: Final = 100.0
    COVERAGE_MODERATE: Final = 50.0
    VOLATILITY_LOW: Final = 30.0
    VOLATILITY_HIGH: Final = 60.0
    INFLATION_DRAG_HIGH: Final = 30.0
    RIGIDITY_LOW: Final = 50.0
    RIGIDITY_HIGH: Final = 70.0
    STRESS_LOW: Final = 10.0
    STRESS_HIGH: Final = 25.0
    SAVINGS_STRONG: Final = 20.0
    SAVINGS_MODERATE: Final = 10.0
    CONVERSION_STRONG: Final = 0.50
    CONVERSION_MODERATE: Final = 0.30
