import json
import os
import typing

import numpy as np

from prospere.core.constants import PathConfig, SimulationDefaults
from prospere.core.workspace import WorkspaceManager
from prospere.simulation.models import (
    DynamicGrowth,
    GrowthPolicy,
    MarketAssumptions,
    ScenarioMetadata,
    SimulationParams,
    SimulationResult,
    TaxRule,
)


class ScenarioRepository:
    """Manages the persistence and retrieval of simulation scenarios."""

    def __init__(self, ws_manager: WorkspaceManager | None = None):
        self.ws_manager = ws_manager

    def resolve_scenario_directory(self, scenario_id: str) -> str:
        if self.ws_manager:
            return self.ws_manager.get_scenario_dir(scenario_id)
        return os.path.join(PathConfig.SIM_SCENARIOS_DIR, scenario_id)

    def get_configuration_file_paths(self, scenario_id: str) -> dict[str, str]:
        base = self.resolve_scenario_directory(scenario_id)
        return {
            "metadata": os.path.join(base, PathConfig.SCENARIO_METADATA),
            "category_config": os.path.join(base, PathConfig.CATEGORY_CONFIG),
            "account_config": os.path.join(base, PathConfig.ACCOUNT_CONFIG),
        }

    def list_available_scenarios(self) -> list[str]:
        root = (
            self.ws_manager.get_scenarios_root()
            if self.ws_manager
            else PathConfig.SIM_SCENARIOS_DIR
        )
        if not os.path.exists(root):
            return []
        return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]

    def persist_scenario_metadata(self, metadata: ScenarioMetadata) -> None:
        paths = self.get_configuration_file_paths(metadata.name)
        os.makedirs(os.path.dirname(paths["metadata"]), exist_ok=True)

        growth_policy_dict = {}
        if metadata.growth_policy:
            growth_policy_dict = {
                "default_income_growth": metadata.growth_policy.default_income_growth,
                "default_expense_growth": metadata.growth_policy.default_expense_growth,
                "inflation_rate": metadata.growth_policy.inflation_rate,
                "category_overrides": metadata.growth_policy.category_overrides,
            }
            if metadata.growth_policy.dynamic_income_growth:
                dg = metadata.growth_policy.dynamic_income_growth
                growth_policy_dict["dynamic_income_growth"] = {
                    "initial_rate": dg.initial_rate,
                    "terminal_rate": dg.terminal_rate,
                    "transition_years": dg.transition_years,
                }
            if metadata.growth_policy.dynamic_expense_growth:
                dg = metadata.growth_policy.dynamic_expense_growth
                growth_policy_dict["dynamic_expense_growth"] = {
                    "initial_rate": dg.initial_rate,
                    "terminal_rate": dg.terminal_rate,
                    "transition_years": dg.transition_years,
                }

        with open(paths["metadata"], "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": metadata.name,
                    "initial_capital": metadata.initial_capital,
                    "currency": metadata.currency,
                    "years": metadata.years,
                    "iterations": metadata.iterations,
                    "start_date": metadata.start_date,
                    "end_date": metadata.end_date,
                    "growth_policy": growth_policy_dict,
                    "taxable_income_categories": metadata.taxable_income_categories,
                    "tax_categories": metadata.tax_categories,
                    "tax_rules": [
                        {
                            "name": r.name,
                            "base": r.base,
                            "rate": r.rate,
                            "exempt_accounts": r.exempt_accounts,
                            "deduct_from": r.deduct_from,
                            "apply_only_to_positive": r.apply_only_to_positive,
                            "timing": r.timing,
                        }
                        for r in metadata.tax_rules
                    ],
                    "estimated_effective_tax_rate": (
                        metadata.estimated_effective_tax_rate
                    ),
                    "snapshot_name": metadata.snapshot_name,
                },
                f,
                indent=4,
                ensure_ascii=False,
            )

    def export_simulation_result(
        self, scenario_id: str, result: SimulationResult
    ) -> str:
        """Exports simulation results to a timestamped JSON file."""
        import datetime

        base_dir = self.resolve_scenario_directory(scenario_id)
        export_dir = os.path.join(base_dir, "exports", "json")
        os.makedirs(export_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(export_dir, f"result_{timestamp}.json")

        meta = self.retrieve_scenario_metadata(scenario_id)

        # Helper to convert numpy objects to serializable lists
        def _to_list(obj: typing.Any) -> typing.Any:
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, dict):
                return {k: _to_list(v) for k, v in obj.items()}
            return obj

        export_data = {
            "metadata": {
                "scenario_id": scenario_id,
                "timestamp": timestamp,
                "success_rate": result.success_rate,
                "years": meta.years,
                "iterations": meta.iterations,
                "growth_policy": {
                    "default_income_growth": meta.growth_policy.default_income_growth
                    if meta.growth_policy
                    else 0.0,
                    "default_expense_growth": meta.growth_policy.default_expense_growth
                    if meta.growth_policy
                    else 0.0,
                },
            },
            "summary": {
                "median_final_assets": float(result.percentile_50[-1]),
                "p10_final_assets": float(result.percentile_10[-1]),
                "p90_final_assets": float(result.percentile_90[-1]),
                "cumulative_tax_paid": float(result.cumulative_tax_paid_50),
                "effective_tax_rate": float(result.effective_tax_rate),
                "monthly_tax_history": _to_list(result.monthly_tax_history_50),
                "success_rate": float(result.success_rate),
                "earliest_failure_year": result.earliest_failure_year,
                "portfolio_mix": _to_list(result.portfolio_mix_50),
                "net_cash_flow_median": _to_list(result.net_cash_flow_50),
                "essential_expense_ratio": float(result.essential_expense_ratio),
                "liquidity_stress_months": int(result.liquidity_stress_months),
                "shock_crash_months_median": int(result.shock_crash_months_median),
                "shock_income_loss_months_median": int(
                    result.shock_income_loss_months_median
                ),
                "shock_expense_spike_months_median": int(
                    result.shock_expense_spike_months_median
                ),
                "shock_crash_iter_pct": float(result.shock_crash_iter_pct),
                "shock_income_loss_iter_pct": float(result.shock_income_loss_iter_pct),
                "shock_expense_spike_iter_pct": float(
                    result.shock_expense_spike_iter_pct
                ),
                "total_income_median": float(result.total_income_median),
                "total_expenses_median": float(result.total_expenses_median),
                "account_roi_contribution": result.account_roi_contribution,
            },
            "trajectories": {
                "p10": result.percentile_10.tolist(),
                "p50": result.percentile_50.tolist(),
                "p90": result.percentile_90.tolist(),
                "present_value_50": result.present_value_50.tolist(),
                "passive_income_coverage_50": (
                    result.passive_income_coverage_50.tolist()
                ),
                "monthly_income_history_50": (
                    result.monthly_income_history_50.tolist()
                ),
                "monthly_expenses_history_50": (
                    result.monthly_expenses_history_50.tolist()
                ),
                "monthly_gains_history_50": (result.monthly_gains_history_50.tolist()),
            },
            "distribution": {
                "final_wealth": result.final_wealth_distribution.tolist(),
            },
            "account_histories_50": {
                k: v.tolist() for k, v in result.account_histories_50.items()
            },
        }

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=4, ensure_ascii=False)

        return file_path

    def export_optimization_context(
        self, scenario_id: str, result: SimulationResult, params: SimulationParams
    ) -> str:
        """Exports simulation context formatted for the optimization engine."""
        import datetime

        from prospere.simulation.exporter import JSONExporter

        base_dir = self.resolve_scenario_directory(scenario_id)
        export_dir = os.path.join(base_dir, "exports", "optimization")
        os.makedirs(export_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(export_dir, f"opt_context_{timestamp}.json")

        return JSONExporter.export_optimization_context(result, params, file_path)

    def export_html_report(
        self,
        scenario_id: str,
        result: SimulationResult,
        params: SimulationParams,
        template_lang: str = "en",
        user_name: str = "User",
    ) -> str:
        """Generates and exports an HTML report."""
        import datetime

        from prospere.simulation.exporter import HTMLExporter

        base_dir = self.resolve_scenario_directory(scenario_id)
        export_dir = os.path.join(base_dir, "exports", "html")
        os.makedirs(export_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(export_dir, f"report_{timestamp}.html")

        meta = self.retrieve_scenario_metadata(scenario_id)
        exporter = HTMLExporter(template_lang=template_lang)
        return exporter.generate(result, meta, params, file_path, user_name=user_name)

    def retrieve_scenario_metadata(self, scenario_id: str) -> ScenarioMetadata:
        """Retrieves metadata from disk. Raises FileNotFoundError if missing."""
        paths = self.get_configuration_file_paths(scenario_id)
        if not os.path.exists(paths["metadata"]):
            raise FileNotFoundError(f"Scenario metadata missing: {paths['metadata']}")

        with open(paths["metadata"], encoding="utf-8") as f:
            data = json.load(f)

            growth_data = data.get("growth_policy")
            growth_policy = None
            if growth_data:
                dynamic_income = None
                if "dynamic_income_growth" in growth_data:
                    dg_data = growth_data["dynamic_income_growth"]
                    dynamic_income = DynamicGrowth(**dg_data)

                dynamic_expense = None
                if "dynamic_expense_growth" in growth_data:
                    dg_data = growth_data["dynamic_expense_growth"]
                    dynamic_expense = DynamicGrowth(**dg_data)

                growth_policy = GrowthPolicy(
                    default_expense_growth=growth_data.get(
                        "default_expense_growth", 0.0
                    ),
                    default_income_growth=growth_data.get("default_income_growth", 0.0),
                    inflation_rate=growth_data.get("inflation_rate", 0.02),
                    category_overrides=growth_data.get("category_overrides", {}),
                    dynamic_income_growth=dynamic_income,
                    dynamic_expense_growth=dynamic_expense,
                )

            return ScenarioMetadata(
                name=data["name"],
                initial_capital=data.get("initial_capital", 0.0),
                currency=data.get("currency", "EUR"),
                years=data.get("years", SimulationDefaults.YEARS),
                iterations=data.get("iterations", SimulationDefaults.ITERATIONS),
                start_date=data.get("start_date"),
                end_date=data.get("end_date"),
                growth_policy=growth_policy,
                taxable_income_categories=data.get("taxable_income_categories", []),
                tax_categories=data.get("tax_categories", []),
                tax_rules=[TaxRule(**r) for r in data.get("tax_rules", [])],
                estimated_effective_tax_rate=data.get("estimated_effective_tax_rate"),
                market_assumptions=(
                    MarketAssumptions(**data["market_assumptions"])
                    if data.get("market_assumptions")
                    else None
                ),
                snapshot_name=data.get("snapshot_name", "default"),
            )
