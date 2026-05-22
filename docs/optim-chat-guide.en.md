# Chat with Prospere — Prompt Guide

Prospere features an AI-powered conversational interface for financial budget optimization. Users can ask questions in natural language — English or Chinese — and Prospere runs Monte Carlo simulations or Efficient Frontier optimization behind the scenes, explaining the results conversationally.

This guide explains how to effectively prompt Prospere to get the best optimization results.

---

## What You Can Ask

### 1. What-If Analysis

Ask Prospere what happens if you change your spending in specific categories. The engine runs a full Monte Carlo simulation and reports the impact on your final wealth, success rate, and growth rate.

| You say | What Prospere does |
|---------|-------------|
| "Reduce dining by 20%" | Simulates cutting the matched category by 20% |
| "少花餐飲 20%" | Same, in Chinese |
| "Cut entertainment by €100 per month" | Simulates a fixed €100/month reduction |
| "Food & Dining::Restaurants reduce 20%" | Targets a specific subcategory |
| "Reduce dining 20% and cut shopping €50" | Simulates multiple adjustments at once |
| "Increase salary by 10%" | Simulates an income-side change |

The response includes:
- Which categories were adjusted and by how much
- P50 wealth comparison (baseline vs adjusted)
- Success rate change
- CAGR change

### 2. Wealth Goal Planning (Forward Frontier)

Tell Prospere your wealth target, and it finds the optimal budget allocation to reach it while minimizing Quality-of-Life impact.

| You say | What Prospere does |
|---------|-------------|
| "I want to reach €100,000 in 3 years" | Finds optimal cuts to hit €100k |
| "兩年後要達到 70k，怎麼調？" | Same, in Chinese |
| "How can I optimize my budget to reach 80k?" | Same, with auto-detected target |

The response includes:
- A **Wealth vs Success Rate trade-off table** comparing 3 strategies:
  - Optimal — minimal lifestyle impact
  - Balanced — 20% more wealth buffer
  - Aggressive — 50% more wealth buffer
- For each strategy: projected P50 wealth, success rate, QoL loss score, monthly savings needed
- Detailed category-level adjustments
- Honest warning if the target cannot be reached with current budget bounds

### 3. Reverse Frontier (QoL Budget → Maximum Wealth)

Tell Prospere your maximum acceptable Quality-of-Life loss, and it finds the highest wealth you can achieve.

| You say | What Prospere does |
|---------|-------------|
| "How much wealth can I reach with at most 5% QoL loss?" | Binary search to maximize wealth within a 5% QoL budget |
| "犧牲不超過 3% 生活品質，最高能到多少？" | Same, in Chinese |
| "Show me the best plan with no more than 8% lifestyle impact" | Same |

### 4. General Questions

You can ask about your financial situation or Prospere's capabilities.

| You say | Response |
|---------|----------|
| "What can you do?" | Lists available features |
| "你能做什麼？" | Same, in Chinese |
| "Explain my current financial situation" | Summarizes your profile and baseline simulation |
| "What's my biggest expense?" | Points out your largest spending category |

When your intent is unclear, Prospere will ask ONE clarifying question at a time to guide you.

---

## Category Matching

You can refer to categories naturally:
- "外食" / "eating out" → automatically matches "Food & Dining::Restaurants"
- "房租" / "rent" → matches "Household::Mortgage/Rent"
- "Netflix" / "訂閱" → matches "Subscription::Streaming & Entertainment"

Subcategories use the `::` delimiter (e.g. "Food & Dining::Restaurants"). You don't need to type the exact names — Prospere finds the best semantic match from your profile.

If no reasonable match exists, Prospere will ask you to clarify.

---

## Commands Inside Chat

| Command | Action |
|---------|--------|
| `/help` or `help` | Show this guide |
| `/clear` or `clear` | Reset conversation |
| `/exit` or `exit` or `退出` | End session |

---

## What Prospere Cannot Do (Yet)

- **Time-phased strategies**: All adjustments apply uniformly across the entire projection period. You cannot say "cut more in year 1, relax in year 2."
- **Automatic waste detection**: Prospere does not analyze your historical spending to suggest what you "should" cut. You decide what to adjust.
- **Multi-goal optimization**: Prospere optimizes for a single wealth target. It reports success rate as additional information, but does not optimize for both simultaneously.
- **Portfolio allocation advice**: Prospere does not suggest how to rebalance your investment accounts.
- **Tax optimization**: Prospere does not model tax-advantaged strategies.

---

## Tips

- Start with a **what-if** on your biggest expense to see the sensitivity.
- Use **forward frontier** when you have a specific goal in mind.
- Use **reverse frontier** when you want to know "what's possible" without sacrificing too much.
- If a strategy shows the target as NOT reachable, try: relaxing bounds (allow larger cuts), extending the timeframe, or lowering the target.
- The **higher the QoL loss**, the more aggressive the cuts — but also the lower the success rate (more risk).
