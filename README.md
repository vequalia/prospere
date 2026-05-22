<p align="center">
  <h1 align="center">Prospere</h1>
</p>

<p align="center">An open-source, AI-powered financial forecasting engine for stochastic wealth simulation and budget optimization.</p>

<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square" /></a>
  <img alt="Python version" src="https://img.shields.io/badge/python-3.11+-blue.svg?style=flat-square" />
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh.md">繁體中文</a> |
  <a href="README.zh-CN.md">简体中文</a>
</p>

---

Prospere builds high-fidelity models of your financial future by analyzing historical transaction data. It transitions your finances from tracking the past to forecasting the future.

### Answers you can act on:

*   **Trajectory**: Where will my net worth be in 10, 20, or 30 years?
*   **Optimization**: How can I maximize wealth without sacrificing my current lifestyle?
*   **Resilience**: How does my plan perform under a 20% market crash or persistent inflation?
*   **Freedom**: When does work become an option rather than a necessity?

---

## Core Capabilities

### 1. Monte Carlo Simulation
Prospere uses **t-distributed Monte Carlo simulations** to account for market volatility and economic shocks, providing a probabilistic range (P10/P50/P90) of your financial future.

### 2. Behavior-Aware Optimization
Powered by **SLSQP (Sequential Least Squares Programming)**, the optimization engine identifies the most flexible categories in your budget to maximize final wealth while minimizing the impact on your quality of life.

### 3. AI Financial Analyst
The AI core is essential for classification and analysis. It is **model-agnostic** and supports any OpenAI-compatible API endpoint, allowing you to use **GPT-5**, **DeepSeek**, or local models.

---

## Installation

### One-Click Install (macOS / Linux)
The easiest way to install Prospere is using our one-click installer. Open your terminal and paste:
```bash
curl -sSL https://raw.githubusercontent.com/vequalia/prospere/main/scripts/install.sh | bash
```

### One-Click Install (Windows)
Open PowerShell and paste:
```powershell
irm https://raw.githubusercontent.com/vequalia/prospere/main/scripts/install.ps1 | iex
```

Once installed, simply type `prospere` in a **new** terminal window to start.

### Developer Setup (Using uv)
If you prefer to manage dependencies manually or want to contribute to the code:
```bash
git clone https://github.com/vequalia/prospere.git
cd prospere
uv sync
uv run prospere
```

---

## Prerequisites

### Transaction Data

Prospere natively supports MoneyWiz CSV exports. If you use a different accounting tool (YNAB, Mint, Quicken, bank exports, custom spreadsheets), use our **AI-powered data cleaner skill** to automatically convert your data:

```bash
# 1. Install the skill for Claude Code
cp skills/data-cleaner.md ~/.claude/skills/

# 2. Run it with your file
/data-cleaner path/to/your/export.csv
```

The skill analyzes your file, maps columns to Prospere's format, and produces the standard output. You can also prepare the data yourself in the format Prospere expects. You need two files:

**1. Processed Transactions (`.xlsx`)**

An Excel file with one row per transaction:

| Column | Example | Notes |
|--------|---------|-------|
| `unique_id` | `a1b2c3d4...` | Any unique string per row |
| `transaction_date` | `2025-04-03` | `YYYY-MM-DD` format |
| `amount` | `5800.00` | Positive = income, negative = expense |
| `currency` | `USD` | EUR, USD, CNY, ILS |
| `primary_category` | `Salary` | Top-level category |
| `secondary_category` | `Base Pay` | Sub-category (can be empty) |
| `account_name` | `Chase Checking` | Which account this belongs to |

**2. Account Balances (`.json`)**

A JSON array with each account's current balance:

```json
[
    { "account_name": "Chase Checking",    "balance": 8500.00,  "currency": "USD" },
    { "account_name": "Vanguard IRA",      "balance": 43200.00, "currency": "USD" },
    { "account_name": "Amex Platinum",     "balance": -1200.00, "currency": "USD" },
    { "account_name": "Fidelity Brokerage","balance": 28500.00, "currency": "USD" }
]
```

On first launch, select **Import Data** from the main menu to import your MoneyWiz CSV. If your data comes from another tool, use the `/data-cleaner` Claude Code skill (see above) to convert it, then choose **Import Pre-processed Data** to load the cleaned output. You can also provide pre-processed files directly — see the format examples above.

### AI Configuration (Required)

An AI API Key is required for core features, including automatic classification and the interactive chat with Prospere. Prospere supports any OpenAI-compatible API endpoint.

When you first launch the `prospere` CLI, you will be automatically prompted to configure your AI provider (e.g., OpenAI, DeepSeek, or a Custom endpoint) and enter your API key. These settings are securely saved globally in `~/.prospere_settings.json` and can be changed later via the **Settings** menu.

---

## Usage
One command. Everything else happens inside the interactive menu:

```bash
uv sync
prospere
```

### Automatic Updates
By default, Prospere checks for updates on startup and automatically upgrades itself using `pip` inside your active environment when a new version is detected on GitHub.

To bypass the automatic update checks, set the environment variable:
```bash
export PROSPERE_NO_UPDATE=1
```


```
  ✦ Prospere  ›  alex
  ──────────────────────────────────────────────────────────────
    1. Chat with Prospere      Analyze your simulation results
    2. Scenarios               View, edit, or create scenarios
    3. Settings                Switch user or language
    4. Exit                    Quit Prospere
  ──────────────────────────────────────────────────────────────
  ↑/↓ navigate  ·  enter select  ·  q quit
```

### Step-by-Step Walkthrough

#### Import Your Data

```
  ✦ Prospere  ›  alex  ›  Import Data
  ──────────────────────────────────────────────────────────────
  ▶ MoneyWiz CSV export
    Pre-processed files (XLSX + JSON)
  ──────────────────────────────────────────────────────────────
  ↑/↓ navigate  ·  Enter select  ·  q back

  Enter path to your MoneyWiz CSV export
  [data/workspaces/alex/raw/moneywiz.csv]:

  Enter dataset name (snapshot) [default]:

  ⠧ Processing data...
  ✓ Imported 1,247 transactions, 5 balances
```

#### Build a Scenario

Once data is imported, select **New Scenario** from the Scenarios menu. You'll be offered two creation modes:

**Quick Setup** — Fully automated. Just specify the number of simulation years; AI handles everything (classification, growth modeling, account/category configuration, tax rules). At the end, you get a comprehensive recap to review before saving.

**Guided Setup** — Step-by-step wizard with AI suggestions. The AI auto-classifies accounts and categories, models income/expense growth curves based on your life stage, and builds country-specific tax rules. Review and override each setting, or skip AI entirely with `--manual`.

```
  ✦ Prospere  ›  alex  ›  Bootstrap  ›  Setup Mode
  ──────────────────────────────────────────────────────────────
  ▶ Guided Setup  (step-by-step with AI suggestions)
    Quick Setup   (AI handles everything — just set years)

  ↑/↓ navigate  ·  Enter select  ·  q back
```

Quick Setup recap example:
```
  ✦ Prospere  ›  alex  ›  Bootstrap  ›  Quick Setup — Recap
  ──────────────────────────────────────────────────────────────
  Scenario: scenario_20260508_091001
  Snapshot: 2025-04-01
  Simulation: 15 years  ·  10,000 iterations  ·  USD
  Net Worth: $85,000

  Growth Policy:
    Dynamic Life-Stage Model:
      Income:  +8.0% → +3.5% over 15 years
      Expense: +4.5% → +2.5% over 15 years
    Inflation:  2.5%

  Tax Configuration:
    Taxable Income: Salary > Base Pay
    Tax Categories: IRS Withholding
    Effective Tax Rate: 22.0%
    Capital Gains Rules: 1 rule(s)
      - Long-Term Gains: 15% on capital_gains (exempt: 401k, IRA)

  Market Assumptions:
    Mean Reversion: enabled (decay: -3.0)
    Long-Term Returns: bond: 3.0%, equity: 7.0%, mixed: 5.0%, savings: 1.0%

  Accounts: 8 total
    Types: investment: 3, savings: 5
    Vanguard 401k                equity      +7.0%  $32,500
    Chase Checking               savings     +1.0%  $18,200
    Robinhood                    equity      +7.0%  $15,800
    ... and 5 more

  Categories: 14 total
    Income (4): Salary, Freelance, Dividends, ...
    Expense (10): Rent, Groceries, Dining, ...

  ▶ Save Scenario  — Save and create the scenario
    Go Back  — Return to adjust settings
    Discard  — Discard all changes and exit
```

Guided Setup step-by-step:
```
  ✦ Prospere  ›  alex  ›  Bootstrap  ›  Step 3/7: Basic Parameters
  ──────────────────────────────────────────────────────────────
  Scenario name [baseline]:
  Simulation years [10]: 15
  Iterations [10000]: 10000
```

#### Run a Simulation

```
  ✦ Prospere  ·  alex  ·  baseline
  ──────────────────────────────────────────────────────────────────────────────────────────
  Period: 10y  │  Ref: 2023-01-01 ➜ 2025-12-31  │  Iterations: 10,000

  ──────────────────────────────────── BASELINE PROFILE ────────────────────────────────────

  Monthly Cashflow    $6,500 - $4,200 = $2,300 (35.4%)
  Initial Capital     $52,000
    Assumptions: Inflation 2.5%  |  Dynamic Salary Growth 5.0% ➜ 2.5%
                       Dynamic Exp. Growth 3.0% ➜ 2.0%

  ──────────────────────────────── Your Results at a Glance ────────────────────────────────

      Projected Final Wealth       $412,500
                                   How fast your wealth grows each year (like interest
                                   on savings)
      Success Rate                 97.8%
                                   Out of all possible futures, how many ended with
                                   money left
      Financial Independence       108.3%
      Progress
                                   Years until investments cover all your living
                                   expenses
      Worst - Best Case Range      $298,700  →  $521,400
                                   How much your outcome could vary across different
                                   markets

    Annual Growth Rate  6.8%  │  Total Taxes Paid $72,100  (Eff. Rate: 18.5%)

  ──────────────────────────── WEALTH TRAJECTORY (MEDIAN PATH) ─────────────────────────────

    $52,000 | ▂▃▅▅▆▆▇▇███ | $412,500

    Year    Total Wealth    Spending Power (after inflation)    Growth This Year
    Y0            52,000                              52,000                   -
    Y5           178,300                             165,800           +$126,300
    Y10          412,500                             358,200           +$234,200

  ─────────────────────────────────── Detailed Analysis ────────────────────────────────────

  How Your Wealth Grows

     Annual Growth Rate       6.8%  (x7.93)
                              How fast your wealth grows each year (like interest on
                              savings)
     Growth Source            58.1% Passive  |  41.9% Active

  Cash Flow

     Income                   $6,500  →  $8,200 /mo
     Expenses                 $4,200  →  $5,100 /mo
     Savings Rate             35.4%  →  37.8%
     Passive Income           $1,500  →  $5,523 /mo
                              How much of your expenses are covered by investment returns

  Goal Progress

     Financial Independence   108.3%
                              Years until investments cover all your living expenses
     Coast FIRE Horizon       4.2 Year
                              Years until investments cover all your living expenses
     Survival Runway          7.1 Year
                              If income stopped today, how many years your savings would
                              last

  What Could Go Wrong

     Inflation Drag           -$54,300  (13.2%)
                              How much purchasing power inflation erodes over time
     Market Volatility        18.5%
                              How much your outcome could vary across different markets
     Shock Exposure           Crash 14% | Spike 21%
                              How often unexpected events (crash, job loss) occurred in
                              simulations

  Spending & Efficiency

     Top ROI Engines          401k (62.0%), Brokerage (28.0%), Savings (10.0%)
                              Which accounts are generating the most growth for you
     Fixed vs Flexible        65.0% fixed
                              Share of expenses that are fixed costs vs flexible spending
     Capital Conversion       0.82
                              How much of each euro earned becomes lasting wealth
     Liquidity Stress         4 mo  (3.3%)
                              Months where expenses exceeded income, requiring use of
                              savings

  ───────────────────────────────── Where Your Money Lives ─────────────────────────────────

    Asset Class    Start %    End %       Shift
    Cash              4.2%     2.1%     ↘ -2.1%
    Savings          18.5%    12.4%     ↘ -6.1%
    Investment       77.3%    85.5%     ↗ +8.2%

  ─────────────────────────────── Range of Possible Outcomes ───────────────────────────────

    Each bar shows how many simulations ended in that wealth range

      298K | ██████████████████████
      320K | ████████████████████████████████
      345K | ██████████████████████████████████████████
      365K | █████████████████████████████████████████████████████
      385K | █████████████████████████████████████████████████████████████
      405K | █████████████████████████████████████████████████████████████████
      430K | ██████████████████████████████████████████████████████████
      460K | ████████████████████████████████████████████████████
      490K | ██████████████████████████████████████████
      521K | ████████████████████████████████
  ──────────────────────────────────────────────────────────────────────────────────────────
```

### High-Fidelity HTML Reports

Prospere generates professional HTML reports designed for deep financial review. You can easily generate and open these reports directly from the Chat interface by typing the `/export` command. These reports synchronize perfectly with the CLI output while providing interactive visualizations and expanded insights.

*   **Executive Dashboard**: Key metrics and success probabilities presented clearly for decision-making.
*   **Interactive Visualizations**: Dynamic charts for wealth trajectories and probability distributions.
*   **Strategic Deep Dives**: Comprehensive analysis of cash flow, efficiency, and risk exposure.
*   **Localized Experience**: Full support for English, Traditional Chinese, and Simplified Chinese.


#### Chat with AI

```
  ✦ Prospere  ›  alex  ›  Chat  ›  baseline
  ──────────────────────────────────────────────────────────────
  ▎ Years 10  ·  P50 Wealth $412,500  ·  CAGR 6.8%
  /help · help  /clear · clear  /result · report  /exit · exit

  ❯ reduce dining out by 30%
  ──────────────────────────────────────────────────────────────
  Cutting Dining::Restaurants by 30% (~$180/mo) increases your
  P50 wealth at Y10 from $412,500 to $448,300 (+$35,800). Your
  savings rate goes from 35.4% to 39.1%. Minimal lifestyle impact
  — Restaurants has flexibility score 8/10.

  ❯ can I reach 1M in 8 years?
  ──────────────────────────────────────────────────────────────
  To reach $1M in 8 years, you'd need to cut expenses by ~14%.
  The optimal plan targets discretionary categories:
    • Dining::Restaurants: -$210/mo (35% cut)
    • Shopping::Clothing: -$95/mo (40% cut)
    • Entertainment::Streaming: -$35/mo (50% cut)
  Quality-of-life loss score: 5.8%. Would you like a less
  aggressive plan, or should I run this simulation?
```

---

## License

[GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html) — you may use, modify, and distribute this software freely, provided that any derivative work is also distributed under the same license.
