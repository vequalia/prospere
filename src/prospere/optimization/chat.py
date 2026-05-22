import glob
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from prospere.ai.assistant import AIAssistant
from prospere.ai.prompts.loader import PromptLoader
from prospere.core.constants import SimulationDefaults
from prospere.core.workspace import WorkspaceManager
from prospere.optimization.engine import OptimizationEngine
from prospere.optimization.models import CategoryAdjustment, OptimIntent
from prospere.simulation.engine import MonteCarloSimulationEngine
from prospere.simulation.models import (
    CategoryStats,
    FinancialProfile,
    GrowthPolicy,
    ScenarioMetadata,
    SimulationParams,
    SimulationResult,
    SubCategoryStats,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatIfOutcome:
    baseline_p50_wealth: float
    new_p50_wealth: float
    wealth_delta: float
    baseline_success_rate: float
    new_success_rate: float
    baseline_cagr: float
    new_cagr: float
    adjustments_applied: list[dict[str, Any]] = field(default_factory=list)
    unmatched_names: list[str] = field(default_factory=list)
    session_label: str = ""


@dataclass(frozen=True)
class FrontierOutcome:
    target_wealth: float
    baseline_p50_wealth: float
    baseline_deterministic: float
    baseline_success_rate: float = 1.0
    mc_validated_wealth: float | None = None
    is_reachable: bool = False
    points: list[dict[str, Any]] = field(default_factory=list)
    max_possible_wealth: float = 0.0


def _export_context(
    profile: FinancialProfile,
    result: SimulationResult,
    scenario_meta: dict[str, Any],
    growth: dict[str, Any],
    export_dir: str,
) -> str:
    """Export simulation context for OptimizationEngine to consume."""
    categories_data = []
    for cat in profile.categories:
        sub_data = []
        for sub in cat.sub_categories:
            sub_data.append(
                {
                    "name": sub.name,
                    "mean": float(sub.mean),
                    "std": float(sub.std),
                    "is_income": sub.is_income,
                    "flexibility_score": sub.flexibility_score,
                    "necessity_level": sub.necessity_level.value,
                    "annual_growth_rate": sub.annual_growth_rate
                    if sub.annual_growth_rate is not None
                    else cat.annual_growth_rate,
                }
            )
        categories_data.append(
            {
                "name": cat.name,
                "mean": float(cat.mean),
                "std": float(cat.std),
                "is_income": cat.is_income,
                "flexibility_score": cat.flexibility_score,
                "necessity_level": cat.necessity_level.value,
                "annual_growth_rate": cat.annual_growth_rate,
                "sub_categories": sub_data,
            }
        )

    accounts_data = []
    for acc in profile.accounts:
        accounts_data.append(
            {
                "name": acc.name,
                "account_type": acc.account_type.value,
                "annual_return": float(acc.annual_return),
                "annual_return_std": float(acc.annual_return_std),
                "allocation_ratio": float(acc.allocation_ratio),
                "initial_balance": float(acc.initial_balance),
                "currency": acc.currency,
            }
        )

    context = {
        "metadata": {
            "scenario_name": scenario_meta.get("name", "default"),
            "years": scenario_meta["years"],
            "iterations": scenario_meta.get("iterations", 1000),
            "base_currency": profile.currency,
            "timestamp": datetime.now().isoformat(),
        },
        "baseline_results": {
            "success_rate": float(result.success_rate),
            "final_wealth_p50": float(result.percentile_50[-1]),
            "final_wealth_pv_p50": float(result.present_value_50[-1]),
            "total_income_median": float(result.total_income_median),
            "total_expenses_median": float(result.total_expenses_median),
            "effective_tax_rate": float(result.effective_tax_rate),
        },
        "financial_profile": {
            "monthly_income_mean": float(profile.monthly_income_mean),
            "monthly_expense_mean": float(profile.monthly_expense_mean),
            "categories": categories_data,
            "accounts": accounts_data,
        },
        "growth_policy": {
            "default_expense_growth": float(growth.get("default_expense_growth", 0.0)),
            "default_income_growth": float(growth.get("default_income_growth", 0.0)),
            "inflation_rate": float(growth.get("inflation_rate", 0.02)),
        },
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(export_dir, f"opt_context_{timestamp}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(context, f, indent=4)

    return output_path


class OptimChatEngine:
    def __init__(
        self,
        scenario_id: str = "",
        ws_manager: WorkspaceManager | None = None,
        lang_dict: dict[str, str] | None = None,
        sim_scenario: str | None = None,
    ):
        self.scenario_id = sim_scenario or scenario_id
        self.ws_manager = ws_manager
        self.user_id = ws_manager.context.user if ws_manager else "User"
        self.lang = lang_dict or {}
        self._ai = AIAssistant()
        self._sim_engine = MonteCarloSimulationEngine()
        self._sim_export_dir: str | None = None
        self._sim_optim_name: str = ""
        self._opt_engine_ref: OptimizationEngine | None = None

        if sim_scenario and ws_manager:
            self._init_from_simulation(sim_scenario, ws_manager)
        else:
            self._opt_engine = OptimizationEngine(
                scenario_id,
                ws_manager=ws_manager,  # type: ignore[arg-type]
            )
            self.scenario_meta = self._opt_engine.metadata
            self.profile = self._build_financial_profile()
            self.growth = self._opt_engine.growth
            self.baseline = self._opt_engine.baseline
            self._opt_engine_ref = self._opt_engine

        self.baseline_params = self._build_sim_params(self.profile)
        self.baseline_result = self._sim_engine.execute_projection(self.baseline_params)

        # Now that baseline is available, export context for OptimizationEngine
        if sim_scenario and ws_manager and self._sim_export_dir:
            os.makedirs(self._sim_export_dir, exist_ok=True)
            existing = glob.glob(
                os.path.join(self._sim_export_dir, "opt_context_*.json")
            )
            if not existing:
                _export_context(
                    self.profile,
                    self.baseline_result,
                    self.scenario_meta,
                    self.growth,
                    self._sim_export_dir,
                )

            # Now create optimization engine (needs the export above)
            try:
                self._opt_engine_ref = OptimizationEngine(
                    self._sim_optim_name,
                    ws_manager=ws_manager,  # type: ignore[arg-type]
                )
            except Exception:
                logger.warning(
                    "Failed to create OptimizationEngine for sim scenario",
                    exc_info=True,
                )
                self._opt_engine_ref = None

        self._financial_context = self._build_financial_context_string()
        self._system_template = PromptLoader.load("system", "optim_chat")
        self._parsed_intent: OptimIntent | None = None

    def _init_from_simulation(
        self, sim_scenario: str, ws_manager: WorkspaceManager
    ) -> None:
        from prospere.core.constants import OptimizationDefaults
        from prospere.simulation.scenario import ScenarioRepository

        repo = ScenarioRepository(ws_manager=ws_manager)
        meta = repo.retrieve_scenario_metadata(sim_scenario)

        self.scenario_meta = {
            "name": meta.name,
            "years": meta.years,
            "iterations": meta.iterations,
            "currency": meta.currency,
            "start_date": meta.start_date,
            "end_date": meta.end_date,
            "snapshot_name": meta.snapshot_name,
        }
        gp = meta.growth_policy
        self.growth = {
            "default_expense_growth": (gp.default_expense_growth if gp else 0.0),
            "default_income_growth": (gp.default_income_growth if gp else 0.0),
            "inflation_rate": gp.inflation_rate if gp else 0.02,
        }

        self.profile = self._build_financial_profile_for_sim(
            sim_scenario, ws_manager, meta
        )

        # Store export dir for later use (after baseline is available)
        sim_dir = ws_manager.get_scenario_dir(sim_scenario)
        self._sim_export_dir = os.path.join(sim_dir, "exports", "optimization")

        # Create default optimization scenario on-the-fly
        optim_name = f"{sim_scenario}_chat_optim"
        optim_dir = ws_manager.get_optimizations_dir(optim_name)
        os.makedirs(optim_dir, exist_ok=True)
        config_path = os.path.join(optim_dir, "config.json")
        if not os.path.exists(config_path):
            default_config = {
                "scenario_name": f"Optim Chat — {sim_scenario}",
                "source_simulation": sim_scenario,
                "target_wealth": None,
                "description": "Created via Optim Chat from menu",
                "bounds_rules": OptimizationDefaults.DEFAULT_BOUNDS_RULES,
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)

        b_initial = sum(a.initial_balance for a in self.profile.accounts)
        b_final = b_initial * (1.05**meta.years)
        self.baseline = {"final_wealth_p50": b_final}
        self._sim_optim_name = optim_name

    def _build_financial_profile_for_sim(
        self, sim_scenario: str, ws_manager: WorkspaceManager, meta: Any
    ) -> FinancialProfile:
        from prospere.core.models import WorkspaceContext
        from prospere.simulation.analyzer import HistoricalDataAnalyzer
        from prospere.simulation.config import (
            AccountConfigurationManager,
            CategoryConfigurationManager,
        )
        from prospere.simulation.models import AccountStats
        from prospere.simulation.scenario import ScenarioRepository

        repo = ScenarioRepository(ws_manager=ws_manager)
        config_paths = repo.get_configuration_file_paths(sim_scenario)

        cat_mgr = CategoryConfigurationManager(config_paths["category_config"])
        acc_mgr = AccountConfigurationManager(config_paths["account_config"])
        cat_mgr.load_from_disk()
        acc_mgr.load_from_disk()

        context = WorkspaceContext(
            user=ws_manager.context.user,
            snapshot=meta.snapshot_name,
            scenario=sim_scenario,
        )
        ws_mgr = WorkspaceManager(context)
        data_path = ws_mgr.get_dataset_path("processed_transactions.xlsx")
        analyzer = HistoricalDataAnalyzer(data_path)

        profile = analyzer.construct_financial_profile(
            currency=meta.currency,
            start_date=meta.start_date,
            end_date=meta.end_date,
            category_config=cat_mgr,
            account_config=acc_mgr,
        )

        initial_cap_sum = sum(a.initial_balance for a in profile.accounts)
        capital_mismatch = (
            abs(initial_cap_sum - meta.initial_capital) > 1.0
            and meta.initial_capital > 0
        )
        if capital_mismatch:
            factor = meta.initial_capital / initial_cap_sum
            profile = FinancialProfile(
                profile.monthly_income_mean,
                profile.monthly_income_std,
                profile.monthly_expense_mean,
                profile.monthly_expense_std,
                profile.currency,
                profile.categories,
                [
                    AccountStats(
                        a.name,
                        a.account_type,
                        a.annual_return,
                        a.monthly_net_flow_mean,
                        a.monthly_net_flow_std,
                        a.allocation_ratio,
                        a.annual_return_std,
                        a.max_balance,
                        a.deposit_priority,
                        a.initial_balance * factor,
                    )
                    for a in profile.accounts
                ],
            )

        return profile

    def _build_financial_profile(self) -> FinancialProfile:
        if self.ws_manager is None:
            raise RuntimeError("WorkspaceManager is required")

        from prospere.core.models import WorkspaceContext
        from prospere.simulation.analyzer import HistoricalDataAnalyzer
        from prospere.simulation.config import (
            AccountConfigurationManager,
            CategoryConfigurationManager,
        )
        from prospere.simulation.scenario import ScenarioRepository

        repo = ScenarioRepository(ws_manager=self.ws_manager)
        scenario_dir = self.ws_manager.get_scenario_dir(self.scenario_id)
        scenario_name = self.scenario_id

        import os

        if not os.path.isdir(scenario_dir):
            for s in repo.list_available_scenarios():
                if s == self.scenario_id:
                    scenario_dir = self.ws_manager.get_scenario_dir(s)
                    scenario_name = s
                    break

        meta = repo.retrieve_scenario_metadata(scenario_name)
        config_paths = repo.get_configuration_file_paths(meta.name)

        cat_mgr = CategoryConfigurationManager(config_paths["category_config"])
        acc_mgr = AccountConfigurationManager(config_paths["account_config"])
        cat_mgr.load_from_disk()
        acc_mgr.load_from_disk()

        context = WorkspaceContext(
            user=self.ws_manager.context.user,
            snapshot=meta.snapshot_name,
            scenario=scenario_name,
        )
        ws_mgr = WorkspaceManager(context)
        data_path = ws_mgr.get_dataset_path("processed_transactions.xlsx")
        analyzer = HistoricalDataAnalyzer(data_path)

        profile = analyzer.construct_financial_profile(
            currency=meta.currency,
            start_date=meta.start_date,
            end_date=meta.end_date,
            category_config=cat_mgr,
            account_config=acc_mgr,
        )

        from prospere.simulation.models import AccountStats

        initial_cap_sum = sum(a.initial_balance for a in profile.accounts)
        capital_mismatch = (
            abs(initial_cap_sum - meta.initial_capital) > 1.0
            and meta.initial_capital > 0
        )
        if capital_mismatch:
            factor = meta.initial_capital / initial_cap_sum
            profile = FinancialProfile(
                profile.monthly_income_mean,
                profile.monthly_income_std,
                profile.monthly_expense_mean,
                profile.monthly_expense_std,
                profile.currency,
                profile.categories,
                [
                    AccountStats(
                        a.name,
                        a.account_type,
                        a.annual_return,
                        a.monthly_net_flow_mean,
                        a.monthly_net_flow_std,
                        a.allocation_ratio,
                        a.annual_return_std,
                        a.max_balance,
                        a.deposit_priority,
                        a.initial_balance * factor,
                    )
                    for a in profile.accounts
                ],
            )

        return profile

    def _build_sim_params(self, profile: FinancialProfile) -> SimulationParams:
        meta = self.scenario_meta
        growth = self.growth
        return SimulationParams(
            initial_capital=sum(a.initial_balance for a in profile.accounts),
            years=meta["years"],
            iterations=meta.get("iterations", 1000),
            profile=profile,
            growth_policy=GrowthPolicy(
                default_expense_growth=growth.get("default_expense_growth", 0.0),
                default_income_growth=growth.get("default_income_growth", 0.0),
                inflation_rate=growth.get("inflation_rate", 0.02),
            ),
            scenario_metadata=ScenarioMetadata(
                name=meta.get("name", self.scenario_id),
                initial_capital=sum(a.initial_balance for a in profile.accounts),
                years=meta["years"],
                iterations=meta.get("iterations", 1000),
                currency=meta.get("currency", "EUR"),
                start_date=meta.get("start_date"),
                end_date=meta.get("end_date"),
                snapshot_name=meta.get("snapshot_name", "default"),
            ),
        )

    def _build_financial_context_string(self) -> str:
        lines: list[str] = []
        profile = self.profile
        meta = self.scenario_meta
        result = self.baseline_result
        years = meta["years"]

        lines.append(f"## Currency: {profile.currency}")
        lines.append(f"## Projection Period: {years} years")

        lines.append("\n### Income Categories")
        for cat in profile.categories:
            if cat.is_income:
                lines.append(
                    f"- {cat.name}: €{cat.mean:,.0f}/mo (std: €{cat.std:,.0f})"
                )

        header = (
            f"  {'Category':<25} | {'Monthly':>10} | {'Flex':>5} | "
            f"{'Necessity':>14} | Max Cut"
        )
        lines.append("\n### Expense Categories (with flexibility data)")
        lines.append(header)
        lines.append("  " + "-" * 72)
        sorted_cats = sorted(
            profile.categories,
            key=lambda c: c.mean if not c.is_income else 0,
            reverse=True,
        )
        for cat in sorted_cats:
            if cat.is_income:
                continue
            oe = self._opt_engine_ref
            max_cut = (
                oe._get_max_cut_ratio(cat.flexibility_score, cat.necessity_level.value)
                if oe
                else 1.0
            )
            lines.append(
                f"  {cat.name:<25} | €{cat.mean:>9,.0f} | "
                f"{cat.flexibility_score:>4}/10 | "
                f"{cat.necessity_level.value:>14} | {max_cut:.0%}"
            )
            for sub in cat.sub_categories:
                sub_max_cut = (
                    oe._get_max_cut_ratio(
                        sub.flexibility_score,
                        sub.necessity_level.value,
                    )
                    if oe
                    else 1.0
                )
                full_name = f"{cat.name}::{sub.name}"
                lines.append(
                    f"  {full_name:<25} | €{sub.mean:>9,.0f} | "
                    f"{sub.flexibility_score:>4}/10 | "
                    f"{sub.necessity_level.value:>14} | {sub_max_cut:.0%}"
                )

        lines.append(f"\n### Total Monthly Income: €{profile.monthly_income_mean:,.0f}")
        lines.append(f"### Total Monthly Expense: €{profile.monthly_expense_mean:,.0f}")
        net = profile.monthly_income_mean - profile.monthly_expense_mean
        lines.append(f"### Monthly Net: €{net:,.0f}")

        initial = result.percentile_50[0]
        final = result.percentile_50[-1]
        multiplier = final / initial if initial > 0 else 0
        cagr = (
            (multiplier ** (1 / years) - 1) * 100 if years > 0 and multiplier > 0 else 0
        )

        lines.append("\n### Baseline Simulation Results (WITHOUT adjustments)")
        lines.append(f"- P10 Final Wealth: €{result.percentile_10[-1]:,.0f}")
        lines.append(f"- P50 Final Wealth: €{final:,.0f}")
        lines.append(f"- P90 Final Wealth: €{result.percentile_90[-1]:,.0f}")
        lines.append(f"- Success Rate: {result.success_rate * 100:.1f}%")
        lines.append(f"- CAGR: {cagr:.1f}%")
        lines.append(
            f"- Essential Expense Ratio: {result.essential_expense_ratio * 100:.0f}%"
        )

        # Coast FIRE
        annual_expenses_end = (
            profile.monthly_expense_mean
            * 12
            * ((1 + self.growth.get("default_expense_growth", 0.0)) ** years)
        )
        fire_target = annual_expenses_end * 25
        avg_roi = cagr / 100 if cagr > 0 else 0.01
        coast_years = (
            np.log(fire_target / final) / np.log(1 + avg_roi)
            if avg_roi > 0 and final < fire_target
            else 0
        )
        lines.append(
            f"- Coast FIRE: {coast_years:.1f} years until portfolio covers expenses"
        )

        lines.append("\n### Risk & Shock Analysis")
        lines.append(f"- Liquidity Stress Months: {result.liquidity_stress_months}")
        lines.append(
            f"- Market Crash: {result.shock_crash_iter_pct:.0f}%"
            f" of iterations, avg duration"
            f" {result.shock_crash_avg_duration:.1f} months"
        )
        lines.append(
            f"- Income Loss: {result.shock_income_loss_iter_pct:.0f}% of iterations"
        )
        lines.append(
            f"- Expense Spikes: {result.shock_expense_spike_iter_pct:.0f}%"
            f" of iterations"
        )

        # Passive income coverage
        if result.passive_income_coverage_50.size > 0:
            final_coverage = result.passive_income_coverage_50[-1]
            lines.append(
                f"- Passive Income Coverage (end): {final_coverage * 100:.1f}%"
            )

        return "\n".join(lines)

    def _build_system_message(self) -> dict[str, Any]:
        content = self._system_template.format(
            financial_context=self._financial_context,
        )
        return {"role": "system", "content": content}

    def parse_user_intent(
        self, history: list[dict[str, Any]], user_text: str
    ) -> OptimIntent | None:
        template = PromptLoader.load("user", "parse_optim_intent")
        user_prompt = template.format(user_query=user_text)

        messages: list[dict[str, Any]] = [self._build_system_message()]
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": user_prompt})

        result = self._ai.parse_structured(messages, OptimIntent)
        if isinstance(result, OptimIntent):
            self._parsed_intent = result
            return result
        return None

    def _correct_adjustment(
        self, adj: CategoryAdjustment, valid_names: set[str], cat_lower: dict[str, str]
    ) -> tuple[CategoryAdjustment, bool]:
        """Fuzzy-corrects an AI adjustment and returns (corrected_adj, is_matched)."""
        full_name = (
            f"{adj.matched_category}::{adj.subcategory_name}"
            if adj.subcategory_name
            else adj.matched_category
        )
        if full_name in valid_names:
            return adj, True
        lower = full_name.lower()
        if lower not in cat_lower:
            return adj, False
        actual = cat_lower[lower]
        delim = SimulationDefaults.SUBCATEGORY_DELIMITER
        if delim in actual:
            cat_part, sub_part = actual.split(delim, 1)
            return CategoryAdjustment(
                user_category_name=adj.user_category_name,
                matched_category=cat_part,
                subcategory_name=sub_part,
                adjustment_type=adj.adjustment_type,
                adjustment_value=adj.adjustment_value,
                duration=adj.duration,
            ), True
        return CategoryAdjustment(
            user_category_name=adj.user_category_name,
            matched_category=actual,
            subcategory_name=None,
            adjustment_type=adj.adjustment_type,
            adjustment_value=adj.adjustment_value,
            duration=adj.duration,
        ), True

    def _compute_adjusted_profile(
        self, adjustments: list[CategoryAdjustment]
    ) -> tuple[FinancialProfile, list[dict[str, Any]], list[str]]:
        profile = self.profile
        applied: list[dict[str, Any]] = []
        unmatched: list[str] = []

        valid_names = {c.name for c in profile.categories}
        cat_lower = {c.name.lower(): c.name for c in profile.categories}
        for c in profile.categories:
            for sub in c.sub_categories:
                full = f"{c.name}::{sub.name}"
                valid_names.add(full)
                cat_lower[full.lower()] = full

        adj_map: dict[tuple[str, str | None], CategoryAdjustment] = {}
        for adj in adjustments:
            corrected, matched = self._correct_adjustment(adj, valid_names, cat_lower)
            if not matched:
                unmatched.append(
                    f"{adj.matched_category}::{adj.subcategory_name}"
                    if adj.subcategory_name
                    else adj.matched_category
                )
            adj_map[(corrected.matched_category, corrected.subcategory_name)] = (
                corrected
            )

        new_categories: list[CategoryStats] = []
        for cat in profile.categories:
            parent_adj = adj_map.get((cat.name, None))
            sub_adjs = {
                k[1]: v
                for k, v in adj_map.items()
                if k[0] == cat.name and k[1] is not None
            }

            if (parent_adj or sub_adjs) and not cat.is_income:
                p_mean, p_delta = cat.mean, 0.0
                if parent_adj:
                    p_delta = (
                        p_mean * (parent_adj.adjustment_value / 100)
                        if parent_adj.adjustment_type == "percentage"
                        else parent_adj.adjustment_value
                    )
                    applied.append(
                        {
                            "category": cat.name,
                            "subcategory": None,
                            "original_mean": p_mean,
                            "new_mean": max(0.0, p_mean + p_delta),
                            "delta": p_delta,
                            "adjustment_type": parent_adj.adjustment_type,
                            "adjustment_value": parent_adj.adjustment_value,
                        }
                    )

                new_subs: list[SubCategoryStats] = []
                sub_delta_total = 0.0
                for sub in cat.sub_categories:
                    s_adj = sub_adjs.get(sub.name)
                    s_delta = (
                        (
                            sub.mean * (s_adj.adjustment_value / 100)
                            if s_adj.adjustment_type == "percentage"
                            else s_adj.adjustment_value
                        )
                        if s_adj
                        else 0.0
                    )
                    sub_delta_total += s_delta
                    if s_adj:
                        applied.append(
                            {
                                "category": f"{cat.name}::{sub.name}",
                                "subcategory": sub.name,
                                "original_mean": sub.mean,
                                "new_mean": max(0.0, sub.mean + s_delta),
                                "delta": s_delta,
                                "adjustment_type": s_adj.adjustment_type,
                                "adjustment_value": s_adj.adjustment_value,
                            }
                        )
                    new_subs.append(
                        SubCategoryStats(
                            name=sub.name,
                            mean=max(0.0, sub.mean + s_delta),
                            std=sub.std,
                            is_income=sub.is_income,
                            is_recurring=sub.is_recurring,
                            flexibility_score=sub.flexibility_score,
                            necessity_level=sub.necessity_level,
                            annual_growth_rate=sub.annual_growth_rate,
                            income_linked_rate=sub.income_linked_rate,
                            shock_events=sub.shock_events,
                            projected_values=sub.projected_values,
                        )
                    )

                new_categories.append(
                    CategoryStats(
                        name=cat.name,
                        mean=max(0.0, p_mean + p_delta + sub_delta_total),
                        std=cat.std,
                        is_income=cat.is_income,
                        sub_categories=new_subs,
                        is_recurring=cat.is_recurring,
                        flexibility_score=cat.flexibility_score,
                        necessity_level=cat.necessity_level,
                        annual_growth_rate=cat.annual_growth_rate,
                        income_linked_rate=cat.income_linked_rate,
                        shock_events=cat.shock_events,
                        projected_values=cat.projected_values,
                    )
                )
            else:
                new_categories.append(cat)

        adjusted_profile = FinancialProfile(
            monthly_income_mean=profile.monthly_income_mean,
            monthly_income_std=profile.monthly_income_std,
            monthly_expense_mean=sum(c.mean for c in new_categories if not c.is_income),
            monthly_expense_std=profile.monthly_expense_std,
            currency=profile.currency,
            categories=new_categories,
            accounts=profile.accounts,
        )
        return adjusted_profile, applied, unmatched

    def _execute_what_if(self, intent: OptimIntent) -> WhatIfOutcome:
        adjusted_profile, applied, unmatched = self._compute_adjusted_profile(
            intent.adjustments
        )

        if not applied:
            b_res = self.baseline_result
            initial = b_res.percentile_50[0]
            final = b_res.percentile_50[-1]
            multiplier = final / initial if initial > 0 else 0
            years = self.scenario_meta["years"]
            cagr = (
                (multiplier ** (1 / years) - 1) * 100
                if years > 0 and multiplier > 0
                else 0
            )
            return WhatIfOutcome(
                baseline_p50_wealth=float(final),
                new_p50_wealth=float(final),
                wealth_delta=0.0,
                baseline_success_rate=float(b_res.success_rate),
                new_success_rate=float(b_res.success_rate),
                baseline_cagr=float(cagr),
                new_cagr=float(cagr),
                adjustments_applied=[],
                unmatched_names=unmatched,
                session_label="(no matching categories found)",
            )

        new_params = self._build_sim_params(adjusted_profile)
        new_result = self._sim_engine.execute_projection(new_params)

        b_res = self.baseline_result
        n_res = new_result
        years = self.scenario_meta["years"]

        b_initial = b_res.percentile_50[0]
        b_final = b_res.percentile_50[-1]
        n_initial = n_res.percentile_50[0]
        n_final = n_res.percentile_50[-1]

        b_mult = b_final / b_initial if b_initial > 0 else 0
        n_mult = n_final / n_initial if n_initial > 0 else 0
        b_cagr = (b_mult ** (1 / years) - 1) * 100 if years > 0 and b_mult > 0 else 0
        n_cagr = (n_mult ** (1 / years) - 1) * 100 if years > 0 and n_mult > 0 else 0

        return WhatIfOutcome(
            baseline_p50_wealth=float(b_final),
            new_p50_wealth=float(n_final),
            wealth_delta=float(n_final - b_final),
            baseline_success_rate=float(b_res.success_rate),
            new_success_rate=float(n_res.success_rate),
            baseline_cagr=float(b_cagr),
            new_cagr=float(n_cagr),
            adjustments_applied=applied,
            unmatched_names=unmatched,
            session_label="",
        )

    def _point_to_adjustments(self, point: Any) -> list[CategoryAdjustment]:
        """Convert an OptimizationPoint category_adjustments to model list.

        Handles both top-level ("Dining") and subcategory-level
        ("Dining::Restaurants") adjustment keys from the optimizer.
        """
        result: list[CategoryAdjustment] = []
        for entity_name, (
            new_mean,
            _limit,
            _is_limited,
        ) in point.category_adjustments.items():
            delim = SimulationDefaults.SUBCATEGORY_DELIMITER
            if delim in entity_name:
                parent, sub = entity_name.split(delim, 1)
                orig_mean = self._get_sub_mean(parent, sub)
            else:
                parent = entity_name
                sub = None
                orig_mean = self._get_cat_mean(entity_name)

            result.append(
                CategoryAdjustment(
                    user_category_name=entity_name,
                    matched_category=parent,
                    subcategory_name=sub,
                    adjustment_type="absolute",
                    adjustment_value=new_mean - orig_mean,
                )
            )
        return result

    def _get_sub_mean(self, parent: str, sub_name: str) -> float:
        for cat in self.profile.categories:
            if cat.name == parent:
                for sub in cat.sub_categories:
                    if sub.name == sub_name:
                        return sub.mean
        return 0.0

    def _get_cat_mean(self, name: str) -> float:
        for cat in self.profile.categories:
            if cat.name == name:
                return cat.mean
        return 0.0

    def _mc_validate_point(self, point: Any, target: float) -> tuple[float, float]:
        """Runs a full MC simulation for an optimization point."""
        try:
            adj = self._point_to_adjustments(point)
            adj_p, _, _ = self._compute_adjusted_profile(adj)
            res = self._sim_engine.execute_projection(self._build_sim_params(adj_p))
            return float(res.percentile_50[-1]), float(res.success_rate)
        except Exception:
            logger.warning(
                f"MC validation failed for {getattr(point, 'label', 'point')}",
                exc_info=True,
            )
            return point.projected_final_wealth, float(
                self.baseline_result.success_rate
            )

    def _execute_reverse_frontier(
        self, max_qol: float, mc_baseline: float
    ) -> FrontierOutcome:
        """Reverse frontier: QoL budget → max wealth."""
        if self._opt_engine_ref is None:
            return FrontierOutcome(0, mc_baseline, mc_baseline)
        point = self._opt_engine_ref.find_wealth_for_qol(max_qol)
        if point is None:
            return FrontierOutcome(0, mc_baseline, mc_baseline)

        mc_wealth, _ = self._mc_validate_point(point, 0)
        mc_reachable = mc_wealth >= 0
        return FrontierOutcome(
            target_wealth=point.projected_final_wealth,
            baseline_p50_wealth=mc_baseline,
            baseline_deterministic=mc_baseline,
            mc_validated_wealth=mc_wealth,
            is_reachable=mc_reachable,
            points=[
                {
                    "label": f"Max at {max_qol:.0f}% QoL loss",
                    "is_reachable": mc_reachable,
                    "qol_loss_score": point.qol_loss_score,
                    "projected_final_wealth": mc_wealth,
                    "mc_validated": True,
                    "monthly_savings_increase": point.monthly_savings_increase,
                    "category_adjustments": {
                        n: {"new_mean": d[0], "max_cut": d[1], "is_limited": d[2]}
                        for n, d in point.category_adjustments.items()
                    },
                }
            ],
            max_possible_wealth=point.projected_final_wealth,
        )

    def _execute_frontier(self, intent: OptimIntent) -> FrontierOutcome:
        target = intent.target_wealth
        max_qol = intent.max_qol_loss
        mc_baseline = float(self.baseline_result.percentile_50[-1])

        if max_qol is not None and target is None:
            return self._execute_reverse_frontier(max_qol, mc_baseline)

        if target is None:
            target = float(mc_baseline * 1.2)

        try:
            if self._opt_engine_ref is None:
                raise RuntimeError("Optimization engine not available")
            frontier_points = self._opt_engine_ref.generate_efficient_frontier(target)
        except Exception as e:
            logger.warning(f"Frontier generation failed: {e}")
            return FrontierOutcome(
                target, mc_baseline, mc_baseline, max_possible_wealth=mc_baseline
            )

        points_data = []
        best_validated_wealth = None
        for p in frontier_points:
            if not p.is_reachable:
                points_data.append(
                    {
                        "label": p.label,
                        "is_reachable": False,
                        "qol_loss_score": p.qol_loss_score,
                        "projected_final_wealth": p.projected_final_wealth,
                        "success_rate": float(self.baseline_result.success_rate),
                        "mc_validated": False,
                        "monthly_savings_increase": p.monthly_savings_increase,
                        "category_adjustments": {
                            n: {"new_mean": d[0], "max_cut": d[1], "is_limited": d[2]}
                            for n, d in p.category_adjustments.items()
                        },
                    }
                )
                continue
            mc_wealth, mc_sr = self._mc_validate_point(p, target)
            if best_validated_wealth is None:
                best_validated_wealth = mc_wealth
            points_data.append(
                {
                    "label": p.label,
                    "is_reachable": mc_wealth >= target,
                    "qol_loss_score": p.qol_loss_score,
                    "projected_final_wealth": mc_wealth,
                    "success_rate": mc_sr,
                    "mc_validated": True,
                    "monthly_savings_increase": p.monthly_savings_increase,
                    "category_adjustments": {
                        n: {"new_mean": d[0], "max_cut": d[1], "is_limited": d[2]}
                        for n, d in p.category_adjustments.items()
                    },
                }
            )

        max_wealth = max(
            (p.projected_final_wealth for p in frontier_points), default=mc_baseline
        )
        return FrontierOutcome(
            target_wealth=target,
            baseline_p50_wealth=mc_baseline,
            baseline_deterministic=mc_baseline,
            mc_validated_wealth=best_validated_wealth,
            is_reachable=any(pt["is_reachable"] for pt in points_data),
            points=points_data,
            max_possible_wealth=max_wealth,
        )

    def execute_intent(self, intent: OptimIntent) -> dict[str, Any]:
        if intent.intent_type == "what_if":
            wif_outcome = self._execute_what_if(intent)
            return {"type": "what_if", "outcome": wif_outcome}
        elif intent.intent_type == "efficient_frontier":
            fe_outcome = self._execute_frontier(intent)
            return {"type": "frontier", "outcome": fe_outcome}
        else:
            return {"type": "general", "outcome": None}

    def _build_wif_context(self, wif: WhatIfOutcome) -> str:
        """Builds result context for What-If intent."""
        lines = ["## What-If Simulation Results", ""]
        if wif.unmatched_names:
            msg = "⚠️  MATCHING FAILURE: The following categories "
            msg += "could not be found in the user's financial profile:"
            lines.append(msg)
            for name in wif.unmatched_names:
                lines.append(f"  - {name}")
            hint = (
                "The user's actual profile categories are listed above. "
                "Tell the user the matching failed."
            )
            lines.append(hint)
            return "\n".join(lines)

        if not wif.adjustments_applied:
            msg = (
                "⚠️  NO ADJUSTMENTS APPLIED: The parser returned "
                "adjustments but none matched any profile category."
            )
            lines.append(msg)
            return "\n".join(lines)

        lines.append("### Adjustments Applied:")
        for adj in wif.adjustments_applied:
            orig, new_m, delta = adj["original_mean"], adj["new_mean"], adj["delta"]
            direction = "increased" if delta > 0 else "reduced"
            chg = (
                f"{adj['adjustment_value']:+.0f}%"
                if adj["adjustment_type"] == "percentage"
                else f"€{delta:+,.0f}"
            )
            val_s = f"€{orig:,.0f}/mo → €{new_m:,.0f}/mo"
            msg = f"- **{adj['category']}**: {val_s} ({direction} by {chg})"
            lines.append(msg)

        lines.extend(
            [
                "",
                "### Wealth Comparison (P50):",
                f"- Baseline: €{wif.baseline_p50_wealth:,.0f}",
                f"- New (after adjustment): €{wif.new_p50_wealth:,.0f}",
                f"- Difference: {'+' if wif.wealth_delta >= 0 else ''}"
                f"€{wif.wealth_delta:,.0f}",
                "",
                "### Success Rate:",
                f"- Baseline: {wif.baseline_success_rate * 100:.1f}%",
                f"- New: {wif.new_success_rate * 100:.1f}%",
                "",
                "### CAGR:",
                f"- Baseline: {wif.baseline_cagr:.1f}%",
                f"- New: {wif.new_cagr:.1f}%",
            ]
        )
        return "\n".join(lines)

    def _build_frontier_context(self, fe: FrontierOutcome) -> str:
        """Builds result context for Efficient Frontier intent."""
        header = f"  {'Strategy':<16} {'Wealth':>12} {'Success':>9} "
        header += f"{'QoL Loss':>10} {'Mo Save':>10} {'Reachable':>12}"
        lines = [
            "## Efficient Frontier Results",
            f"Target: €{fe.target_wealth:,.0f}",
            f"Baseline P50 (MC): €{fe.baseline_p50_wealth:,.0f}",
            "",
            "### Wealth vs Success Rate Trade-off",
            header,
            "  " + "-" * 75,
        ]
        for pt in fe.points:
            sr = pt.get("success_rate", 0) * 100
            line = f"  {pt['label']:<16} €{pt['projected_final_wealth']:>11,.0f} "
            line += f"{sr:>8.1f}% {pt['qol_loss_score']:>9.1f}% "
            line += f"€{pt['monthly_savings_increase']:>9,.0f} "
            line += f"{'Yes' if pt['is_reachable'] else 'No':>12}"
            lines.append(line)

        if fe.mc_validated_wealth is not None:
            if fe.mc_validated_wealth < fe.target_wealth:
                msg = (
                    f"\n⚠️  CRITICAL: Best MC-validated result "
                    f"(€{fe.mc_validated_wealth:,.0f}) is BELOW target "
                    f"(€{fe.target_wealth:,.0f})."
                )
                lines.append(msg)
            else:
                lines.append("\n✓ Best strategy reaches target in MC simulation.")

        lines.extend(["", "### Strategy Details:"])
        for pt in fe.points:
            lines.append(f"\n#### {pt['label']}")
            if pt["category_adjustments"]:
                lines.append("- Category Adjustments:")
                for cn, ad in pt["category_adjustments"].items():
                    note = " (MAX)" if ad["is_limited"] else ""
                    val = ad["new_mean"]
                    lines.append(f"  - {cn}: → €{val:,.0f}/mo{note}")
        return "\n".join(lines)

    def _build_result_context(self, result: dict[str, Any]) -> str:
        header = "[COMPUTATION RESULTS — use this data to formulate your response]\n\n"
        if result["type"] == "what_if":
            return header + self._build_wif_context(result["outcome"])
        if result["type"] == "frontier":
            return header + self._build_frontier_context(result["outcome"])
        return header

    def process_turn(
        self,
        console: Any,
        messages: list[dict[str, Any]],
        chat_history: list[dict[str, str]],
        lang: dict[str, str],
        user_input: str,
    ) -> None:
        non_system = [m for m in messages if m["role"] != "system"]
        intent = self.parse_user_intent(non_system[-6:], user_input)

        # Determine if we should execute or just chat
        should_execute = False
        if intent is not None:
            if intent.intent_type == "what_if" and intent.adjustments:
                should_execute = True
            elif intent.intent_type == "efficient_frontier" and (
                intent.target_wealth or intent.max_qol_loss
            ):
                should_execute = True
            elif (
                intent.intent_type == "efficient_frontier"
                and not intent.target_wealth
                and not intent.max_qol_loss
            ):
                # User mentioned goal but no specific target — pass to AI
                should_execute = False
            elif intent.intent_type == "what_if" and not intent.adjustments:
                should_execute = False

        result_context = ""
        if should_execute:
            result = self.execute_intent(intent)  # type: ignore[arg-type]
            result_context = self._build_result_context(result)

        turn_messages: list[dict[str, Any]] = list(messages)

        if result_context:
            turn_messages.append(
                {
                    "role": "system",
                    "content": result_context,
                }
            )

        turn_messages.append({"role": "user", "content": user_input})
        chat_history.append({"role": "user", "content": user_input})

        console.print()
        full_response = self._ai.stream_chat(console, turn_messages, lang)
        if full_response is None:
            chat_history.pop()
            return

        if result_context:
            messages.append(
                {
                    "role": "system",
                    "content": result_context,
                }
            )
        messages.append({"role": "user", "content": user_input})
        messages.append({"role": "assistant", "content": full_response})
        chat_history.append({"role": "assistant", "content": full_response})

    def format_simulation_report(self, user: str = "") -> str:
        """Generate the full simulation report and return it as a string."""
        import io
        from contextlib import redirect_stdout

        from prospere.cli.i18n import _set_language
        from prospere.cli.simulate import (
            _display_baseline,
            _display_distribution_histogram,
            _display_header,
            _display_projection_journey,
            generate_insight_report_text,
        )
        from prospere.simulation.models import ScenarioMetadata

        user_name = user or self.user_id
        lang_code = self.lang.get("_code", "en")
        _set_language(lang_code)

        meta = self.baseline_params.scenario_metadata
        if meta is None:
            meta = ScenarioMetadata(
                name=self.scenario_id,
                initial_capital=sum(a.initial_balance for a in self.profile.accounts),
                years=self.scenario_meta["years"],
                iterations=self.scenario_meta.get("iterations", 1000),
                currency=self.scenario_meta.get("currency", "EUR"),
                start_date=self.scenario_meta.get("start_date"),
                end_date=self.scenario_meta.get("end_date"),
                snapshot_name=self.scenario_meta.get("snapshot_name", "default"),
            )

        buf = io.StringIO()
        with redirect_stdout(buf):
            _display_header(meta, user_name)
            _display_baseline(self.profile, meta)
            _display_projection_journey(self.baseline_result, meta)
            insight = generate_insight_report_text(
                self.baseline_result,
                self.baseline_params,
                meta,
            )
            print(insight)
            _display_distribution_histogram(self.baseline_result)

        return buf.getvalue()

    def display_simulation_report_rich(self, user: str = "") -> None:
        """Display the simulation report using Rich formatting directly to terminal."""
        from prospere.cli.i18n import _set_language
        from prospere.cli.simulate import (
            _display_analysis_rich,
            _display_baseline_rich,
            _display_distribution_rich,
            _display_portfolio_rich,
            _display_recommendations_rich,
            _display_summary_rich,
            _display_trajectory_rich,
        )
        from prospere.simulation.models import ScenarioMetadata

        lang_code = self.lang.get("_code", "en")
        _set_language(lang_code)

        meta = self.baseline_params.scenario_metadata
        if meta is None:
            meta = ScenarioMetadata(
                name=self.scenario_id,
                initial_capital=sum(a.initial_balance for a in self.profile.accounts),
                years=self.scenario_meta["years"],
                iterations=self.scenario_meta.get("iterations", 1000),
                currency=self.scenario_meta.get("currency", "EUR"),
                start_date=self.scenario_meta.get("start_date"),
                end_date=self.scenario_meta.get("end_date"),
                snapshot_name=self.scenario_meta.get("snapshot_name", "default"),
            )

        _display_baseline_rich(self.profile, meta)
        _display_summary_rich(self.baseline_result, meta)
        _display_trajectory_rich(self.baseline_result, meta)
        _display_analysis_rich(self.baseline_result, self.baseline_params)
        _display_portfolio_rich(self.baseline_result)
        _display_distribution_rich(self.baseline_result)
        _display_recommendations_rich(self.baseline_result, self.baseline_params)

    def export_html_chat(self) -> str | None:
        """Generate HTML report and return the absolute file path."""
        import os
        import tempfile

        from prospere.simulation.exporter import HTMLExporter
        from prospere.simulation.models import ScenarioMetadata

        lang_code = self.lang.get("_code", "en")

        meta = self.baseline_params.scenario_metadata
        if meta is None:
            meta = ScenarioMetadata(
                name=self.scenario_id,
                initial_capital=sum(a.initial_balance for a in self.profile.accounts),
                years=self.scenario_meta["years"],
                iterations=self.scenario_meta.get("iterations", 1000),
                currency=self.scenario_meta.get("currency", "EUR"),
                start_date=self.scenario_meta.get("start_date"),
                end_date=self.scenario_meta.get("end_date"),
                snapshot_name=self.scenario_meta.get("snapshot_name", "default"),
            )

        # Save to scenario exports dir if workspace available, otherwise temp
        if self.ws_manager:
            from prospere.simulation.scenario import ScenarioRepository

            repo = ScenarioRepository(ws_manager=self.ws_manager)
            export_path = repo.export_html_report(
                self.scenario_id,
                self.baseline_result,
                self.baseline_params,
                template_lang=lang_code,
                user_name=self.user_id,
            )
        else:
            export_dir = os.path.join(tempfile.gettempdir(), "prospere_exports")
            os.makedirs(export_dir, exist_ok=True)
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = os.path.join(export_dir, f"report_{ts}.html")
            exporter = HTMLExporter(template_lang=lang_code)
            exporter.generate(
                self.baseline_result,
                meta,
                self.baseline_params,
                export_path,
                user_name=self.user_id,
            )

        return os.path.abspath(export_path)

    def is_available(self) -> bool:
        return self._ai.is_available()
