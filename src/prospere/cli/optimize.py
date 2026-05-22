import argparse
import sys

from prospere.cli.i18n import _set_language, _t, detect_lang
from prospere.cli.utils import format_currency
from prospere.core.constants import CLIConfig, OptimizationDefaults
from prospere.optimization.engine import OptimizationEngine


def _display_context(engine: OptimizationEngine) -> None:
    """Displays optimization scenario context."""
    print(f"\n[0] {_t('optimize_context_title')}")
    print(f"  {_t('optimize_scenario_label')}    {engine.opt_config['scenario_name']}")
    print(
        f"  {_t('optimize_source_sim_label')}  {engine.opt_config['source_simulation']}"
    )


def _display_baseline_gap(
    engine: OptimizationEngine, target_wealth_goal: float | None
) -> None:
    """Displays baseline wealth and gap to target."""
    baseline_p50_wealth = engine.baseline["final_wealth_p50"]
    print(f"\n[1] {_t('optimize_baseline_title')}")
    print(
        f"  {_t('optimize_current_p50_wealth')} {format_currency(baseline_p50_wealth)}"
    )

    if target_wealth_goal is not None:
        print(
            f"  {_t('optimize_target_wealth')}      "
            f"{format_currency(target_wealth_goal)}"
        )
        wealth_gap = target_wealth_goal - baseline_p50_wealth
        status = _t("optimize_shortfall") if wealth_gap > 0 else _t("optimize_surplus")
        print(
            f"  {_t('optimize_wealth_gap')}         "
            f"{format_currency(wealth_gap)} ({status})"
        )


def run_optimization_cli() -> None:
    """Main entry point for the Prospere Optimization CLI."""
    parser = argparse.ArgumentParser(description="Prospere Financial Optimization")
    parser.add_argument("--user", type=str, default="default_user")
    parser.add_argument(
        "--scenario", type=str, required=True, help="Name of optimization scenario"
    )
    parser.add_argument("--what-if", nargs="+", help="Simulate specific budget changes")
    parser.add_argument(
        "--lang",
        type=str,
        default=detect_lang(),
        choices=["en", "zh-Hant", "zh-Hans"],
        help="Language for CLI output",
    )
    args = parser.parse_args()
    _set_language(args.lang)

    width = CLIConfig.TABLE_WIDTH
    print("\n" + "─" * width)
    print(f"  {_t('optimize_header', args.user, args.scenario)}")
    print("─" * width)

    from prospere.core.models import WorkspaceContext
    from prospere.core.workspace import WorkspaceManager

    context = WorkspaceContext(user=args.user, scenario=args.scenario)
    ws_manager = WorkspaceManager(context)

    try:
        engine = OptimizationEngine(args.scenario, ws_manager=ws_manager)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    target_wealth_goal = engine.opt_config.get("target_wealth")
    _display_context(engine)
    _display_baseline_gap(engine, target_wealth_goal)

    if target_wealth_goal is None and not args.what_if:
        print(f"\n{_t('optimize_missing_target_error')}")
        sys.exit(1)

    if args.what_if:
        _handle_what_if_mode(engine, args.what_if)
    else:
        _handle_optimization_mode(engine, target_wealth_goal)  # type: ignore[arg-type]


def _handle_what_if_mode(
    engine: OptimizationEngine, adjustments_raw: list[str]
) -> None:
    """Processes and displays the impact of manual budget adjustments."""
    print(f"\n[2] {_t('optimize_whatif_title')}")
    print(f"  {_t('optimize_evaluating')}")

    adjustments = {}
    original_means = {cat["name"]: cat["mean"] for cat in engine.profile["categories"]}

    for item in adjustments_raw:
        try:
            category_name, value_string = item.rsplit(":", 1)
            if category_name not in original_means:
                print(f"  {_t('optimize_category_not_found', category_name)}")
                return

            original_value = original_means[category_name]
            if value_string.endswith("%"):
                percentage = float(value_string.rstrip("%")) / 100.0
                delta_amount = original_value * percentage
            else:
                delta_amount = float(value_string)

            adjustments[category_name] = delta_amount
        except ValueError:
            print(f"  {_t('optimize_format_error', item)}")
            return

    results = engine.evaluate_what_if(adjustments)

    print(f"\n  {_t('optimize_adjustments_title')}")
    print(
        f"    {_t('optimize_col_category'):<25} | "
        f"{_t('optimize_col_original'):>12} | "
        f"{_t('optimize_col_change'):>12} | "
        f"{_t('optimize_col_new_value'):>12}"
    )
    print("    " + "-" * 67)
    for cat_name, delta in adjustments.items():
        orig = original_means[cat_name]
        print(
            f"    {cat_name:<25} | {format_currency(orig):>12} | "
            f"{format_currency(delta):>12} | {format_currency(orig + delta):>12}"
        )

    print(f"\n  {_t('optimize_longterm_impact_title')}")
    print(
        f"    {_t('optimize_baseline_final_wealth')} "
        f"{format_currency(results['baseline_wealth'])}"
    )
    print(
        f"    {_t('optimize_new_projected_wealth')}  "
        f"{format_currency(results['new_wealth'])}"
    )

    wealth_delta = results["wealth_delta"]
    performance_pct = (wealth_delta / (results["baseline_wealth"] or 1)) * 100
    wealth_delta_str = format_currency(wealth_delta)
    perf_str = f"({'+' if wealth_delta > 0 else ''}{performance_pct:.1f}%)"
    print(f"    {_t('optimize_wealth_difference')}     {wealth_delta_str} {perf_str}")

    _print_footer(_t("optimize_footer_whatif"))


def _handle_optimization_mode(engine: OptimizationEngine, target_wealth: float) -> None:
    """Executes the optimization engine and displays the efficient frontier."""
    print(f"\n[2] {_t('optimize_frontier_title')}")
    print(f"  {_t('optimize_searching')}")

    frontier = engine.generate_efficient_frontier(target_wealth)

    if not frontier:
        print(f"  {_t('optimize_no_optimizable')}")
        return

    # Find the primary strategy (Optimal)
    optimal_point = next(
        (p for p in frontier if OptimizationDefaults.STRATEGY_OPTIMAL in p.label),
        frontier[0],
    )

    if not optimal_point.is_reachable:
        _print_unreachable_warning(target_wealth, optimal_point.projected_final_wealth)
        return

    header = (
        f"\n  {_t('optimize_col_strategy'):<20} | "
        f"{_t('optimize_col_qol_loss'):>10} | "
        f"{_t('optimize_col_final_wealth'):>18} | "
        f"{_t('optimize_col_savings_plus'):>10}"
    )
    print(header)
    print("  " + "-" * 75)

    for point in frontier:
        wealth_str = f"{point.projected_final_wealth:>18,.0f}"
        savings_str = f"+{point.monthly_savings_increase:>9.0f}"
        row = (
            f"  {point.label:<20} | {point.qol_loss_score:>9.1f}% | "
            f"{wealth_str} | {savings_str}"
        )
        print(row)

    print(f"\n[3] {_t('optimize_recommendations_title')}")
    _display_top_adjustments(engine, frontier)

    _print_footer(_t("optimize_footer_advice"))


def _display_top_adjustments(engine: OptimizationEngine, frontier: list) -> None:
    """Displays category-level adjustments for the best strategy found."""
    best_strategy = None
    for label in [
        OptimizationDefaults.STRATEGY_OPTIMAL,
        OptimizationDefaults.STRATEGY_BALANCED,
        OptimizationDefaults.STRATEGY_AGGRESSIVE,
    ]:
        strat = next((p for p in frontier if p.label == label), None)
        if strat:
            best_strategy = strat
            break

    if not best_strategy:
        best_strategy = frontier[0]

    print("  (" + _t("optimize_displaying", best_strategy.label) + ")")
    adj_header = (
        f"  {_t('optimize_col_category'):<25} | "
        f"{_t('optimize_col_original'):>10} | "
        f"{_t('optimize_col_new'):>10} | "
        f"{_t('optimize_col_cut_pct'):>7} | "
        f"{_t('optimize_col_limit')}"
    )
    print(adj_header)
    print("  " + "-" * 75)

    original_means = {cat["name"]: cat["mean"] for cat in engine.profile["categories"]}
    sorted_adjustments = sorted(
        best_strategy.category_adjustments.items(), key=lambda x: x[1][0], reverse=False
    )

    for cat_name, (new_mean, limit_amount, is_limited) in sorted_adjustments[:12]:
        orig = original_means.get(cat_name, 0.0)
        cut_ratio = (1 - new_mean / orig) * 100 if orig > 0 else 0
        limit_ratio = (limit_amount / orig) * 100 if orig > 0 else 0

        status_flag = _t("optimize_max_flag") if is_limited else ""
        print(
            f"  {cat_name:<25} | {orig:>10,.0f} | {new_mean:>10,.0f} | "
            f"{cut_ratio:>6.1f}% | {limit_ratio:>3.0f}%{status_flag}"
        )


def _print_unreachable_warning(target: float, max_possible: float) -> None:
    """Prints a prominent warning when the target wealth is unreachable."""
    width = CLIConfig.TABLE_WIDTH
    print("\n" + "!" * width)
    text = " [!] " + _t("optimize_unreachable_title") + " "
    print(text.center(width, "!"))
    print("!" * width)
    print(f"  {_t('optimize_target_impossible', format_currency(target))}")
    print(f"  {_t('optimize_comfort_bounds')}")
    print(f"\n  {_t('optimize_max_possible', format_currency(max_possible))}")
    shortfall = format_currency(target - max_possible)
    print(f"  {_t('optimize_shortfall_amount', shortfall)}")
    print(f"\n  {_t('optimize_suggestions')}")
    print(f"  {_t('optimize_suggestion_1')}")
    print(f"  {_t('optimize_suggestion_2')}")
    print(f"  {_t('optimize_suggestion_3')}")
    print("\n" + "█" * width + "\n")


def _print_footer(message: str) -> None:
    """Prints a styled footer message."""
    width = CLIConfig.TABLE_WIDTH
    print("\n" + "█" * width)
    print(message.center(width))
    print("█" * width + "\n")


if __name__ == "__main__":
    run_optimization_cli()
