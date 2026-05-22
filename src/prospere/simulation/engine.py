import logging
from typing import Any

import numpy as np
from scipy import stats  # type: ignore

from prospere.core.constants import (
    AccountType,
    AssetClass,
    NecessityLevel,
    SimulationDefaults,
)
from prospere.simulation.models import (
    AccountStats,
    DynamicGrowth,
    SimulationParams,
    SimulationResult,
    TaxRule,
)

logger = logging.getLogger(__name__)


class MonteCarloSimulationEngine:
    """
    Transparent stochastic engine for financial forecasting.
    Focuses on clear growth assumptions and rigid liquidity management.
    """

    @staticmethod
    def _account_type_eq(account_type: AccountType | str, target: AccountType) -> bool:
        if isinstance(account_type, AccountType):
            return account_type == target
        return account_type == target.value

    def _classify_accounts_for_returns(
        self, accounts: list[AccountStats], corr_config: dict
    ) -> tuple[dict[str, list[int]], list[int]]:
        """Separates accounts into asset classes for sampling."""
        class_indices: dict[str, list[int]] = {}
        uncorrelated_indices: list[int] = []
        for i, acc in enumerate(accounts):
            if acc.account_type == AccountType.IGNORE:
                continue
            cls = acc.asset_class
            if cls and corr_config and cls in corr_config:
                class_indices.setdefault(cls, []).append(i)
            else:
                uncorrelated_indices.append(i)
        return class_indices, uncorrelated_indices

    def _apply_market_performance(
        self,
        wealth_matrix: np.ndarray,
        month: int,
        params: SimulationParams,
        crash_return_shift: np.ndarray | None = None,
        crash_vol_mult: np.ndarray | None = None,
    ) -> np.ndarray:
        """Calculates and applies compounding returns to all accounts."""
        mp = SimulationDefaults.MONTHS_PER_YEAR
        n_iter = params.iterations
        gains = np.zeros((n_iter, len(params.profile.accounts)))
        base_currency = params.profile.currency
        fx_vol_monthly = SimulationDefaults.FX_VOLATILITY_ANNUAL / np.sqrt(mp)

        market_assumptions = params.scenario_metadata.market_assumptions
        corr_config = (
            market_assumptions.asset_correlations if market_assumptions else {}
        )
        current_returns = getattr(self, "_current_returns", {})

        class_indices, uncorrelated_indices = self._classify_accounts_for_returns(
            params.profile.accounts, corr_config
        )

        if class_indices and len(class_indices) >= 2:
            market_shock = {
                "crash_return_shift": crash_return_shift,
                "crash_vol_mult": crash_vol_mult,
                "fx_vol_monthly": fx_vol_monthly,
                "base_currency": base_currency,
            }
            self._apply_correlated_returns(
                wealth_matrix,
                month,
                params,
                gains,
                corr_config,
                current_returns,
                class_indices,
                market_shock,
            )

        for acc_idx in uncorrelated_indices:
            acc = params.profile.accounts[acc_idx]
            ann_return = current_returns.get(acc.name, acc.annual_return)
            monthly_mean = (1 + ann_return) ** (1 / mp) - 1
            monthly_std = acc.annual_return_std / np.sqrt(mp)

            actual_returns = stats.t.rvs(
                SimulationDefaults.T_DIST_DF,
                loc=monthly_mean,
                scale=monthly_std,
                size=n_iter,
            )

            self._apply_crash_and_fx(
                wealth_matrix,
                month,
                acc_idx,
                acc,
                actual_returns,
                crash_return_shift,
                crash_vol_mult,
                fx_vol_monthly,
                base_currency,
            )

            gains[:, acc_idx] = (
                wealth_matrix[:, month, acc_idx]
                - wealth_matrix[:, month - 1, acc_idx].copy()
            )

        return gains

    def _calculate_class_stats(
        self,
        class_order: list[str],
        class_indices: dict[str, list[int]],
        accounts: list[AccountStats],
        current_returns: dict[str, float],
    ) -> tuple[np.ndarray, np.ndarray]:
        """Calculates monthly mean and std per asset class."""
        mp = SimulationDefaults.MONTHS_PER_YEAR
        n_classes = len(class_order)
        class_means = np.zeros(n_classes)
        class_stds = np.zeros(n_classes)

        for j, cls in enumerate(class_order):
            indices = class_indices[cls]
            cls_rets = [
                current_returns.get(accounts[idx].name, accounts[idx].annual_return)
                for idx in indices
            ]
            class_means[j] = (1 + float(np.mean(cls_rets))) ** (1 / mp) - 1

            cls_stds_list = [accounts[idx].annual_return_std for idx in indices]
            non_zero = [s for s in cls_stds_list if s > 0]
            if non_zero:
                class_stds[j] = np.mean(non_zero) / np.sqrt(mp)
            elif cls == AssetClass.SAVINGS.value:
                class_stds[j] = SimulationDefaults.DEFAULT_SAVINGS_VOLATILITY / np.sqrt(
                    mp
                )
            else:
                class_stds[j] = SimulationDefaults.RETURN_STD_DEFAULT / np.sqrt(mp)

        return class_means, class_stds

    def _build_correlation_matrix(
        self, class_order: list[str], corr_config: dict
    ) -> np.ndarray:
        """Constructs a symmetric correlation matrix for asset classes."""
        n_classes = len(class_order)
        corr_matrix = np.eye(n_classes)
        for j, cls_j in enumerate(class_order):
            for k, cls_k in enumerate(class_order):
                if j != k:
                    corr_matrix[j, k] = corr_config.get(cls_j, {}).get(cls_k, 0.0)
                    corr_matrix[k, j] = corr_matrix[j, k]
        return corr_matrix

    def _apply_correlated_returns(
        self,
        wealth_matrix: np.ndarray,
        month: int,
        params: SimulationParams,
        gains: np.ndarray,
        corr_config: dict,
        current_returns: dict[str, float],
        class_indices: dict[str, list[int]],
        market_shock: dict,
    ) -> None:
        """Generates correlated returns via Cholesky decomposition per asset class."""
        n_iter = params.iterations
        accounts = params.profile.accounts
        class_order = sorted(class_indices.keys())
        n_classes = len(class_order)

        class_means, class_stds = self._calculate_class_stats(
            class_order, class_indices, accounts, current_returns
        )
        corr_matrix = self._build_correlation_matrix(class_order, corr_config)

        try:
            cholesky_l = np.linalg.cholesky(
                corr_matrix
                + np.eye(n_classes) * SimulationDefaults.CHOLESKY_STABILIZATION
            )
        except np.linalg.LinAlgError:
            cholesky_l = np.eye(n_classes)

        independent = np.zeros((n_iter, n_classes))
        for j in range(n_classes):
            independent[:, j] = stats.t.rvs(
                SimulationDefaults.T_DIST_DF,
                loc=class_means[j],
                scale=max(class_stds[j], SimulationDefaults.CHOLESKY_STABILIZATION),
                size=n_iter,
            )

        correlated = (independent @ cholesky_l.T) + (
            class_means - (independent @ cholesky_l.T).mean(axis=0)
        )

        for j, cls in enumerate(class_order):
            base_return = correlated[:, j]
            for acc_idx in class_indices[cls]:
                self._apply_crash_and_fx(
                    wealth_matrix,
                    month,
                    acc_idx,
                    accounts[acc_idx],
                    base_return.copy(),
                    market_shock.get("crash_return_shift"),
                    market_shock.get("crash_vol_mult"),
                    market_shock.get("fx_vol_monthly", 0.0),
                    market_shock.get("base_currency", ""),
                )
                gains[:, acc_idx] = (
                    wealth_matrix[:, month, acc_idx]
                    - wealth_matrix[:, month - 1, acc_idx].copy()
                )

    @staticmethod
    def _apply_crash_and_fx(
        wealth_matrix: np.ndarray,
        month: int,
        acc_idx: int,
        acc: AccountStats,
        actual_returns: np.ndarray,
        crash_return_shift: np.ndarray | None,
        crash_vol_mult: np.ndarray | None,
        fx_vol_monthly: float,
        base_currency: str,
    ) -> None:
        """Applies crash shift/vol multiplier and FX volatility to one account."""
        if (
            crash_return_shift is not None
            and crash_vol_mult is not None
            and acc.account_type in (AccountType.INVESTMENT, AccountType.SAVINGS)
        ):
            actual_returns = actual_returns * crash_vol_mult + crash_return_shift

        wealth_matrix[:, month, acc_idx] *= 1 + actual_returns

        if (
            acc.currency != base_currency
            and acc.currency not in SimulationDefaults.FX_VOLATILITY_EXCLUDED
        ):
            fx_returns = stats.t.rvs(
                SimulationDefaults.T_DIST_DF,
                loc=0.0,
                scale=fx_vol_monthly,
                size=len(actual_returns),
            )
            wealth_matrix[:, month, acc_idx] *= 1 + fx_returns

    def _distribute_surplus(
        self,
        current_wealth: np.ndarray,
        params: SimulationParams,
        surplus: np.ndarray,
    ) -> None:
        """Allocates positive net flow according to debt priority and then ratios."""
        remaining = surplus.copy()

        # 1. Immediate Debt Repayment
        sorted_indices = sorted(
            range(len(params.profile.accounts)),
            key=lambda i: params.profile.accounts[i].deposit_priority,
        )

        for idx in sorted_indices:
            debt_mask = current_wealth[:, idx] < 0
            if np.any(debt_mask & (remaining > 0)):
                debt_amount = -current_wealth[debt_mask, idx]
                payment = np.minimum(remaining[debt_mask], debt_amount)
                current_wealth[debt_mask, idx] += payment
                remaining[debt_mask] -= payment

        # 2. Proportional Savings/Investment
        if np.any(remaining > 0):
            alloc_indices = [
                i
                for i, acc in enumerate(params.profile.accounts)
                if acc.allocation_ratio > 0
            ]

            if alloc_indices:
                ratios = np.array(
                    [params.profile.accounts[i].allocation_ratio for i in alloc_indices]
                )
                total_ratio = ratios.sum()
                for i, idx in enumerate(alloc_indices):
                    share = (ratios[i] / total_ratio) * remaining

                    limit = params.profile.accounts[idx].max_balance
                    current = current_wealth[:, idx]
                    space = np.maximum(0, limit - current)

                    actual_deposit = np.minimum(share, space)
                    current_wealth[:, idx] += actual_deposit
            else:
                # Fallback: Put everything into the first CASH account found
                for i, acc in enumerate(params.profile.accounts):
                    if acc.account_type == AccountType.CASH:
                        current_wealth[:, i] += remaining
                        break

    def _execute_withdrawal(
        self,
        current_wealth: np.ndarray,
        params: SimulationParams,
        deficit: np.ndarray,
    ) -> None:
        """Handles negative net flow using a rigid 'Liquidity Ladder'."""
        remaining_deficit = deficit.copy()

        ladder = [
            AccountType.CASH,
            AccountType.SAVINGS,
            AccountType.INVESTMENT,
            AccountType.CREDIT,
        ]

        for a_type in ladder:
            indices = [
                i
                for i, a in enumerate(params.profile.accounts)
                if self._account_type_eq(a.account_type, a_type)
            ]
            for idx in indices:
                if a_type == AccountType.CREDIT:
                    available = remaining_deficit
                else:
                    available = np.maximum(0, current_wealth[:, idx])

                withdrawal = np.minimum(available, remaining_deficit)
                current_wealth[:, idx] -= withdrawal
                remaining_deficit -= withdrawal

                if np.all(remaining_deficit <= 0):
                    return

    def _route_expenses_to_credit(
        self,
        wealth: np.ndarray,
        month: int,
        monthly_expense: float,
        params: SimulationParams,
    ) -> float:
        """Routes a share of expenses to credit accounts each month.

        Returns the total credit charge, which must be added to net_flow
        to reflect reduced immediate cash outlay.
        """
        credit_indices = [
            i
            for i, acc in enumerate(params.profile.accounts)
            if self._account_type_eq(acc.account_type, AccountType.CREDIT)
            and acc.allocation_ratio < 0
        ]
        if not credit_indices:
            return 0.0

        total_neg_ratio = sum(
            abs(params.profile.accounts[i].allocation_ratio) for i in credit_indices
        )
        if total_neg_ratio <= 0:
            return 0.0

        total_credit_charge = (
            monthly_expense * SimulationDefaults.CREDIT_REVOLVING_SHARE
        )

        for ci in credit_indices:
            share = abs(params.profile.accounts[ci].allocation_ratio) / total_neg_ratio
            charge = total_credit_charge * share
            wealth[:, month, ci] -= charge

        return total_credit_charge

    def _calculate_growth_multiplier(
        self, growth: float | DynamicGrowth, year: int
    ) -> float:
        """Calculates growth factor with career-stage decay support."""
        if not isinstance(growth, DynamicGrowth):
            return (1 + float(growth)) ** year

        initial = growth.initial_rate
        terminal = growth.terminal_rate
        t_years = max(1, growth.transition_years)

        cumulative = 1.0
        for y in range(year):
            rate = terminal + (initial - terminal) * np.exp(
                SimulationDefaults.DYNAMIC_GROWTH_DECAY * y / t_years
            )
            cumulative *= 1 + rate
        return cumulative

    def _apply_mean_reversion(self, params: SimulationParams, year: int) -> None:
        """Decay account annual returns toward long-term market means."""
        market_assumptions = params.scenario_metadata.market_assumptions
        if not market_assumptions or not market_assumptions.mean_reversion_enabled:
            return

        if not hasattr(self, "_current_returns"):
            self._current_returns: dict[str, float] = {}

        decay = market_assumptions.mean_reversion_decay
        ltr = (
            market_assumptions.long_term_returns
            or SimulationDefaults.DEFAULT_LONG_TERM_RETURNS
        )

        for acc in params.profile.accounts:
            cls = acc.asset_class
            if not cls or acc.account_type not in (
                AccountType.INVESTMENT,
                AccountType.SAVINGS,
            ):
                continue

            long_term = ltr.get(cls, SimulationDefaults.RETURN_MEAN_DEFAULT)
            self._current_returns[acc.name] = long_term + (
                acc.annual_return - long_term
            ) * np.exp(decay * year)

    def _apply_single_tax_rule(
        self,
        rule: TaxRule,
        wealth: np.ndarray,
        month: int,
        gains: np.ndarray,
        params: SimulationParams,
    ) -> float:
        """Applies a single tax rule to gains and returns total tax collected."""
        if rule.base not in ("capital_gains", "interest_earned"):
            return 0.0

        exempt_indices = {
            i
            for i, acc in enumerate(params.profile.accounts)
            if acc.name in rule.exempt_accounts
        }

        taxable_base = np.zeros(params.iterations)
        account_taxable = {}
        for i, acc in enumerate(params.profile.accounts):
            if i in exempt_indices or acc.account_type == AccountType.IGNORE:
                continue

            account_gains = gains[:, i]
            if rule.apply_only_to_positive:
                account_gains = np.maximum(0, account_gains)

            account_taxable[i] = account_gains
            taxable_base += account_gains

        tax_due = taxable_base * rule.rate
        if not np.any(tax_due > 0):
            return 0.0

        if rule.deduct_from == "account":
            for i, acc_taxable_base in account_taxable.items():
                share = np.divide(
                    acc_taxable_base,
                    taxable_base,
                    out=np.zeros_like(taxable_base),
                    where=taxable_base > 0,
                )
                wealth[:, month, i] -= tax_due * share

        return float(tax_due.sum())

    def _apply_tax_rules(
        self,
        wealth: np.ndarray,
        month: int,
        gains: np.ndarray,
        params: SimulationParams,
    ) -> float:
        """Applies tax rules to market gains, deducting from accounts."""
        tax_rules: list[TaxRule] = params.scenario_metadata.tax_rules
        if not tax_rules:
            return 0.0

        return sum(
            self._apply_single_tax_rule(rule, wealth, month, gains, params)
            for rule in tax_rules
        )

    def _update_shock_regimes(
        self,
        rng: np.random.Generator | None,
        in_crash: np.ndarray,
        in_income_shock: np.ndarray,
        in_expense_spike: np.ndarray,
        crash_months: np.ndarray,
        income_shock_months: np.ndarray,
        expense_spike_months: np.ndarray,
        crash_duration: np.ndarray,
        crash_cooldown: np.ndarray,
        income_cooldown: np.ndarray,
    ) -> None:
        n = len(in_crash)
        gen = rng.random if rng is not None else np.random.random

        # Decrement cooldowns
        crash_cooldown[crash_cooldown > 0] -= 1
        income_cooldown[income_cooldown > 0] -= 1

        # Market crash: cooldown-aware entry probability
        crash_entry_prob = np.where(
            crash_cooldown > 0,
            SimulationDefaults.SHOCK_MARKET_CRASH_MONTHLY_PROB
            * SimulationDefaults.SHOCK_MARKET_CRASH_COOLDOWN_MULTIPLIER,
            SimulationDefaults.SHOCK_MARKET_CRASH_MONTHLY_PROB,
        )
        entering_crash = ~in_crash & (gen(n) < crash_entry_prob)

        # Market crash: hazard-rate exit probability (ramps up with duration)
        crash_exit_prob = SimulationDefaults.SHOCK_MARKET_CRASH_EXIT_BASE + (
            SimulationDefaults.SHOCK_MARKET_CRASH_EXIT_MAX
            - SimulationDefaults.SHOCK_MARKET_CRASH_EXIT_BASE
        ) * (
            1
            - np.exp(-SimulationDefaults.SHOCK_MARKET_CRASH_EXIT_DECAY * crash_duration)
        )
        exiting_crash = in_crash & (gen(n) < crash_exit_prob)

        in_crash[entering_crash] = True
        in_crash[exiting_crash] = False
        crash_months[in_crash] += 1
        crash_duration[entering_crash] = 1
        crash_duration[exiting_crash] = 0
        crash_duration[in_crash] += 1
        crash_cooldown[exiting_crash] = (
            SimulationDefaults.SHOCK_MARKET_CRASH_COOLDOWN_MONTHS
        )

        # Income shock: cooldown-aware entry, static exit
        base_income_prob = SimulationDefaults.SHOCK_INCOME_LOSS_MONTHLY_PROB
        income_probs = np.where(
            in_crash,
            base_income_prob
            * SimulationDefaults.SHOCK_CRASH_CORRELATED_INCOME_MULTIPLIER,
            base_income_prob,
        )
        income_probs = np.where(
            income_cooldown > 0,
            income_probs * SimulationDefaults.SHOCK_INCOME_LOSS_COOLDOWN_MULTIPLIER,
            income_probs,
        )
        entering_income = ~in_income_shock & (gen(n) < income_probs)
        exiting_income = in_income_shock & (
            gen(n) < SimulationDefaults.SHOCK_INCOME_LOSS_EXIT_MONTHLY_PROB
        )
        in_income_shock[entering_income] = True
        in_income_shock[exiting_income] = False
        income_shock_months[in_income_shock] += 1
        income_cooldown[exiting_income] = (
            SimulationDefaults.SHOCK_INCOME_LOSS_COOLDOWN_MONTHS
        )

        entering_spike = ~in_expense_spike & (
            gen(n) < SimulationDefaults.SHOCK_EXPENSE_SPIKE_MONTHLY_PROB
        )
        exiting_spike = in_expense_spike & (
            gen(n) < SimulationDefaults.SHOCK_EXPENSE_SPIKE_EXIT_MONTHLY_PROB
        )
        in_expense_spike[entering_spike] = True
        in_expense_spike[exiting_spike] = False
        expense_spike_months[in_expense_spike] += 1

    def _resolve_target_mean(
        self, target: str, params: SimulationParams, parents_with_subs: set[str]
    ) -> float:
        """Resolves a single target name to its mean value."""
        delim = SimulationDefaults.SUBCATEGORY_DELIMITER
        if delim not in target and target in parents_with_subs:
            return 0.0

        if delim in target:
            parent, sub = target.split(delim, 1)
            for cat in params.profile.categories:
                if cat.name == parent:
                    for scat in cat.sub_categories:
                        if scat.name == sub:
                            return scat.mean
        else:
            for cat in params.profile.categories:
                if cat.name == target:
                    return cat.mean
        return 0.0

    def _get_targeted_mean(self, targets: list[str], params: SimulationParams) -> float:
        """Resolves target categories to an aggregate mean."""
        parents_with_subs = set()
        delim = SimulationDefaults.SUBCATEGORY_DELIMITER
        for target in targets:
            if delim in target:
                parents_with_subs.add(target.split(delim, 1)[0])

        return sum(
            self._resolve_target_mean(t, params, parents_with_subs) for t in targets
        )

    def _prepare_adjusted_categories(
        self,
        params: SimulationParams,
        taxable_cats: list[str],
        tax_payment_cats: list[str],
        eff_tax_rate: float,
        use_estimated_rate: bool,
    ) -> list[tuple[Any, float]]:
        """Pre-calculates category means adjusted for tax logic."""
        adjusted_categories = []
        for cat in params.profile.categories:
            if cat.is_income:
                mean = cat.mean
                if use_estimated_rate and cat.name in taxable_cats:
                    mean = mean / (1.0 - eff_tax_rate)
                adjusted_categories.append((cat, mean))
                continue

            adj_mean = cat.mean
            if cat.name in tax_payment_cats:
                adj_mean = 0.0
            else:
                for scat in cat.sub_categories:
                    delim = SimulationDefaults.SUBCATEGORY_DELIMITER
                    full_name = f"{cat.name}{delim}{scat.name}"
                    if full_name in tax_payment_cats:
                        adj_mean -= scat.mean
            adjusted_categories.append((cat, max(0.0, adj_mean)))
        return adjusted_categories

    def _calculate_monthly_shocks(
        self,
        params: SimulationParams,
        in_crash: np.ndarray,
        in_income_shock: np.ndarray,
        in_expense_spike: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Calculates market crash returns and income/expense shock factors."""
        crash_shift = np.where(
            in_crash,
            stats.t.rvs(
                SimulationDefaults.T_DIST_DF,
                loc=SimulationDefaults.SHOCK_MARKET_CRASH_RETURN_MEAN,
                scale=SimulationDefaults.SHOCK_MARKET_CRASH_RETURN_STD,
                size=params.iterations,
            ),
            0.0,
        )
        crash_vol = np.where(
            in_crash,
            SimulationDefaults.SHOCK_MARKET_CRASH_VOL_MULTIPLIER,
            1.0,
        )
        income_shock_factor = np.where(
            in_income_shock,
            1.0 - SimulationDefaults.SHOCK_INCOME_LOSS_FRACTION,
            1.0,
        )
        expense_spike_factor = np.where(
            in_expense_spike,
            SimulationDefaults.SHOCK_EXPENSE_SPIKE_MULTIPLIER,
            1.0,
        )
        return crash_shift, crash_vol, income_shock_factor, expense_spike_factor

    def _apply_monthly_cashflow(
        self,
        wealth: np.ndarray,
        month: int,
        params: SimulationParams,
        net_flow: np.ndarray,
    ) -> None:
        """Applies net cash flow surplus or deficit to accounts."""
        neg_mask = net_flow < 0
        pos_mask = net_flow > 0

        if np.any(pos_mask):
            surplus_wealth = wealth[pos_mask, month, :].copy()
            self._distribute_surplus(surplus_wealth, params, net_flow[pos_mask])
            wealth[pos_mask, month, :] = surplus_wealth

        if np.any(neg_mask):
            deficit_wealth = wealth[neg_mask, month, :].copy()
            self._execute_withdrawal(deficit_wealth, params, -net_flow[neg_mask])
            wealth[neg_mask, month, :] = deficit_wealth

    def execute_projection(
        self, params: SimulationParams, seed: int | None = None
    ) -> SimulationResult:
        """The 'Clean Simulation' Loop."""
        if seed is not None:
            np.random.seed(seed)

        months = params.years * SimulationDefaults.MONTHS_PER_YEAR
        num_acc = len(params.profile.accounts)
        wealth = np.zeros((params.iterations, months + 1, num_acc))

        for i, acc in enumerate(params.profile.accounts):
            if acc.account_type != AccountType.IGNORE:
                wealth[:, 0, i] = acc.initial_balance

        taxable_cats = params.scenario_metadata.taxable_income_categories
        tax_payment_cats = params.scenario_metadata.tax_categories

        tax_inc_base = self._get_targeted_mean(taxable_cats, params)
        tax_exp_base = self._get_targeted_mean(tax_payment_cats, params)
        eff_tax_rate = (tax_exp_base / tax_inc_base) if tax_inc_base > 0 else 0.0

        use_estimated_rate = False
        if (
            eff_tax_rate == 0.0
            and params.scenario_metadata.estimated_effective_tax_rate
            and params.scenario_metadata.estimated_effective_tax_rate < 1.0
            and tax_inc_base > 0
        ):
            eff_tax_rate = params.scenario_metadata.estimated_effective_tax_rate
            use_estimated_rate = True
            tax_inc_base = tax_inc_base / (1.0 - eff_tax_rate)

        adjusted_categories = self._prepare_adjusted_categories(
            params,
            taxable_cats,
            tax_payment_cats,
            eff_tax_rate,
            use_estimated_rate,
        )

        monthly_tax = []
        monthly_net_flow_median = []
        monthly_gains_median = []
        monthly_expenses_median = []
        monthly_living_expenses_median = []
        monthly_income_history = []
        total_market_gains = np.zeros((params.iterations, num_acc))
        deficit_months = np.zeros(params.iterations, dtype=int)

        rng = np.random.default_rng(seed) if seed is not None else None
        in_crash = np.zeros(params.iterations, dtype=bool)
        in_income_shock = np.zeros(params.iterations, dtype=bool)
        in_expense_spike = np.zeros(params.iterations, dtype=bool)
        crash_months = np.zeros(params.iterations, dtype=int)
        income_shock_months = np.zeros(params.iterations, dtype=int)
        expense_spike_months = np.zeros(params.iterations, dtype=int)
        crash_duration = np.zeros(params.iterations, dtype=int)
        crash_cooldown = np.zeros(params.iterations, dtype=int)
        income_cooldown = np.zeros(params.iterations, dtype=int)

        income_policy = (
            params.growth_policy.dynamic_income_growth
            or params.growth_policy.default_income_growth
        )
        expense_policy = (
            params.growth_policy.dynamic_expense_growth
            or params.growth_policy.default_expense_growth
        )

        for m in range(1, months + 1):
            year = (m - 1) // 12
            wealth[:, m, :] = wealth[:, m - 1, :].copy()

            self._apply_mean_reversion(params, year)

            self._update_shock_regimes(
                rng,
                in_crash,
                in_income_shock,
                in_expense_spike,
                crash_months,
                income_shock_months,
                expense_spike_months,
                crash_duration,
                crash_cooldown,
                income_cooldown,
            )

            crash_shift, crash_vol, inc_shock_f, exp_spike_f = (
                self._calculate_monthly_shocks(
                    params, in_crash, in_income_shock, in_expense_spike
                )
            )

            gains = self._apply_market_performance(
                wealth, m, params, crash_shift, crash_vol
            )
            total_market_gains += gains
            monthly_gains_median.append(float(np.median(gains.sum(axis=1))))

            self._apply_tax_rules(wealth, m, gains, params)

            inc_mult = self._calculate_growth_multiplier(income_policy, year)
            exp_mult = self._calculate_growth_multiplier(expense_policy, year)

            m_income_base = 0.0
            m_expense_base = 0.0

            for cat, adj_mean in adjusted_categories:
                if cat.is_income:
                    m_income_base += adj_mean * inc_mult
                else:
                    linked = cat.income_linked_rate or 0.0
                    m_expense_base += adj_mean * (
                        linked * inc_mult + (1 - linked) * exp_mult
                    )

            m_income = m_income_base * inc_shock_f
            m_expense = m_expense_base * exp_spike_f

            cur_tax = (tax_inc_base * inc_mult) * eff_tax_rate
            total_std = (
                params.profile.monthly_income_std + params.profile.monthly_expense_std
            )
            net_flow = np.random.normal(m_income - m_expense - cur_tax, total_std)

            monthly_tax.append(float(cur_tax))
            monthly_income_history.append(float(np.median(m_income)))
            monthly_expenses_median.append(float(np.median(m_expense) + cur_tax))
            monthly_living_expenses_median.append(float(np.median(m_expense)))
            monthly_net_flow_median.append(float(np.median(net_flow)))

            credit_charge = self._route_expenses_to_credit(
                wealth, m, float(np.median(m_expense)), params
            )
            net_flow = net_flow + credit_charge

            neg_mask = net_flow < 0
            if np.any(neg_mask):
                deficit_months[neg_mask] += 1

            self._apply_monthly_cashflow(wealth, m, params, net_flow)

        withdrawal_months_count = int(np.median(deficit_months))
        shock_crash_mo = int(np.median(crash_months))
        shock_income_mo = int(np.median(income_shock_months))
        shock_spike_mo = int(np.median(expense_spike_months))
        shock_crash_pct = float(np.mean(crash_months > 0) * 100)
        shock_income_pct = float(np.mean(income_shock_months > 0) * 100)
        shock_spike_pct = float(np.mean(expense_spike_months > 0) * 100)
        shock_crash_dur = (
            float(np.mean(crash_months[crash_months > 0]))
            if crash_months.any()
            else 0.0
        )
        shock_income_dur = (
            float(np.mean(income_shock_months[income_shock_months > 0]))
            if income_shock_months.any()
            else 0.0
        )
        shock_spike_dur = (
            float(np.mean(expense_spike_months[expense_spike_months > 0]))
            if expense_spike_months.any()
            else 0.0
        )

        return self._calculate_post_simulation_metrics(
            wealth,
            params,
            monthly_gains_median,
            monthly_expenses_median,
            monthly_living_expenses_median,
            monthly_tax,
            total_market_gains,
            sum(monthly_income_history),
            sum(monthly_expenses_median),
            withdrawal_months_count,
            eff_tax_rate,
            monthly_net_flow_median,
            shock_crash_mo,
            shock_income_mo,
            shock_spike_mo,
            shock_crash_pct,
            shock_income_pct,
            shock_spike_pct,
            shock_crash_dur,
            shock_income_dur,
            shock_spike_dur,
            monthly_income_history,
            monthly_expenses_median,
            monthly_gains_median,
        )

    def _calculate_post_simulation_metrics(
        self,
        wealth_matrix: np.ndarray,
        params: SimulationParams,
        monthly_market_gains_median: list[float],
        monthly_expenses_median: list[float],
        monthly_living_expenses_median: list[float],
        monthly_tax_history: list[float],
        account_market_gains: np.ndarray,
        total_income_median: float,
        total_expenses_median: float,
        withdrawal_months_count: int,
        effective_tax_rate: float,
        monthly_net_cash_flow_median: list[float],
        shock_crash_months: int = 0,
        shock_income_loss_months: int = 0,
        shock_expense_spike_months: int = 0,
        shock_crash_iter_pct: float = 0.0,
        shock_income_loss_iter_pct: float = 0.0,
        shock_expense_spike_iter_pct: float = 0.0,
        shock_crash_avg_duration: float = 0.0,
        shock_income_avg_duration: float = 0.0,
        shock_spike_avg_duration: float = 0.0,
        monthly_income_history: list[float] | None = None,
        monthly_expenses_history: list[float] | None = None,
        monthly_gains_history: list[float] | None = None,
    ) -> SimulationResult:
        """Clean implementation of summary stats."""
        total_wealth = wealth_matrix.sum(axis=2)
        p10, p50, p90 = np.percentile(total_wealth, [10, 50, 90], axis=0)

        success_rate = np.mean(total_wealth[:, -1] > 0)

        failure_mask = total_wealth < 0
        earliest_failure_year: float | None = None
        if failure_mask.any():
            failure_months = np.argmax(failure_mask, axis=1)
            valid = failure_months > 0
            if valid.any():
                earliest_failure_year = float(np.min(failure_months[valid])) / 12

        infl = params.growth_policy.inflation_rate
        pv_factor = (1 + infl) ** (np.arange(len(p50)) / 12)
        pv_50 = p50 / pv_factor

        mix = {}
        months_total = wealth_matrix.shape[1]
        pv_discount = (1 + infl) ** (np.arange(months_total) / 12)
        for t in set(a.account_type for a in params.profile.accounts):
            indices = [
                i for i, a in enumerate(params.profile.accounts) if a.account_type == t
            ]
            key = t.value if hasattr(t, "value") else str(t)
            pv_type_wealth = wealth_matrix[:, :, indices].sum(axis=2) / pv_discount
            mix[key] = np.median(pv_type_wealth, axis=0)

        total_gain = np.median(account_market_gains.sum(axis=1))
        roi_map = {}
        if total_gain > 0:
            for i, acc in enumerate(params.profile.accounts):
                roi_map[acc.name] = np.median(account_market_gains[:, i]) / total_gain

        essential_expense_ratio = self._compute_budget_rigidity(params)

        return SimulationResult(
            percentile_10=p10,
            percentile_50=p50,
            percentile_90=p90,
            success_rate=success_rate,
            present_value_50=pv_50,
            passive_income_coverage_50=np.array(monthly_market_gains_median)
            / np.array(monthly_living_expenses_median),
            final_wealth_distribution=total_wealth[:, -1],
            account_histories_50={
                a.name: np.median(wealth_matrix[:, :, i], axis=0)
                for i, a in enumerate(params.profile.accounts)
            },
            net_cash_flow_50=np.array(monthly_net_cash_flow_median),
            cumulative_tax_paid_50=sum(monthly_tax_history),
            effective_tax_rate=effective_tax_rate,
            monthly_tax_history_50=np.array(monthly_tax_history),
            portfolio_mix_50=mix,
            account_roi_contribution=roi_map,
            total_income_median=total_income_median,
            total_expenses_median=total_expenses_median,
            liquidity_stress_months=withdrawal_months_count,
            essential_expense_ratio=essential_expense_ratio,
            shock_crash_months_median=shock_crash_months,
            shock_income_loss_months_median=shock_income_loss_months,
            shock_expense_spike_months_median=shock_expense_spike_months,
            shock_crash_iter_pct=shock_crash_iter_pct,
            shock_income_loss_iter_pct=shock_income_loss_iter_pct,
            shock_expense_spike_iter_pct=shock_expense_spike_iter_pct,
            shock_crash_avg_duration=shock_crash_avg_duration,
            shock_income_avg_duration=shock_income_avg_duration,
            shock_spike_avg_duration=shock_spike_avg_duration,
            earliest_failure_year=earliest_failure_year,
            monthly_income_history_50=(
                np.array(monthly_income_history)
                if monthly_income_history
                else np.array([])
            ),
            monthly_expenses_history_50=(
                np.array(monthly_expenses_history)
                if monthly_expenses_history
                else np.array([])
            ),
            monthly_gains_history_50=(
                np.array(monthly_gains_history)
                if monthly_gains_history
                else np.array([])
            ),
        )

    def _compute_budget_rigidity(self, params: SimulationParams) -> float:
        tax_payment_cats = params.scenario_metadata.tax_categories
        total = 0.0
        rigid = 0.0

        for cat in params.profile.categories:
            if cat.is_income:
                continue
            if not cat.sub_categories:
                total += cat.mean
                if cat.necessity_level in {
                    NecessityLevel.STRICT,
                    NecessityLevel.ESSENTIAL,
                }:
                    rigid += cat.mean
                continue
            for scat in cat.sub_categories:
                full_name = (
                    f"{cat.name}{SimulationDefaults.SUBCATEGORY_DELIMITER}{scat.name}"
                )
                if full_name in tax_payment_cats:
                    continue
                total += scat.mean
                if scat.necessity_level in {
                    NecessityLevel.STRICT,
                    NecessityLevel.ESSENTIAL,
                }:
                    rigid += scat.mean

        return rigid / total if total > 0 else 0.0
