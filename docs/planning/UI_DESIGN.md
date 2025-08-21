Key questions (fast alignment)
Primary goal: What’s the single most important outcome for this UI (e.g., faster insight discovery, better storytelling, fewer clicks, higher engagement)?
Users: Who are the core personas (PM, risk analyst, exec)? What changes between beginner vs power users?
Top workflows: What are the 3 journeys we must make effortless (e.g., diagnose risk spike, rebalance, explain performance)?
KPIs: Which metrics prove success (e.g., time-to-insight, task completion rate, NPS)?
Brand: Existing brand palette/typography or should we introduce a fresh visual language?
Density: Prefer compact “pro” tables/charts or airy “story” layouts?
Navigation: Sidebar app-shell vs top-tabs? Do you want a right-rail assistant?
Data viz: Any charting lib preference (ECharts, Recharts, VisX) and required chart types?
Accessibility & devices: WCAG target and breakpoints (desktop-first with responsive)?
Tech constraints: State/query libs (TanStack Query, Redux?), theming, dark mode, performance budgets, feature flags, rollout plan.

Product brief (aligned)
Personas: pro individual investor (primary), scalable to analysts/PMs/retail; beginners get simplified language via AI.
Core journeys:
1) Diagnose portfolio (risk score, exposures, performance) with clear explanations
2) Action: run scenarios/stress tests and see impact
3) Close loop: recommended actions/optimization and track outcomes
Success metric: engagement (time on platform, return visits) → we’ll design for habit-forming check-ins and quick insight loops.
Brand: new distinctive visual language (we’ll extend tokens and keep dark mode).
Density: compact “pro” tables/charts by default.
Assistant: right-rail explainer on every analytical view.
Devices: desktop-first; readable mobile.
System choices (defaults I’ll implement unless you change)
Direction: Precision Pro (data-dense).
Dashboard KPIs: risk score, annual volatility, max drawdown (adjustable).
Benchmark: per-portfolio selectable with SPY as default.
Navigation: left sidebar app-shell; keep current pills temporarily during migration.
Charts: keep Recharts now; phase in ECharts for more dynamic interactivity.
Timeframes: 1W, 1M, 3M, 6M, 1Y, YTD, ALL.
Tables: virtualization, quick filter chips, column presets, CSV export, row details drawer.
Language: “Explain this” in right rail; beginner/pro tone toggle.

Direction
Precision Pro (data-first, dense, fast). Default to compact density, power-user keyboardability, rich tooltips, compare modes.
Information architecture (lean)
Dashboard: Overview (summary + anomalies), Trends, Alerts.
Portfolio: Overview, Holdings, Risk Analysis, Performance.
Optimization: Strategies, Efficient Frontier, “What to change”.
Research: Factors, Scenarios, Peers.
Settings: Risk settings, Integrations, Preferences.
Core workflows to optimize
Diagnose “what changed” and “why” for risk/performance vs benchmark.
Identify top contributors (positions/factors/industries), test scenarios, and see impact.
Close the loop: recommended actions (trim, add hedge, rebalance, run optimization) with immediate feedback.Page blueprints (first pass)
Dashboard Overview
SummaryBar: total value, risk score, annual vol, drawdown, tracking error.
Performance vs Benchmark (timeframe chips).
Risk Contribution Pareto with cumulative line.
Smart Alerts feed (limit breaches, anomalies).
Portfolio Overview
Snapshot cards + holdings table (virtualized) with quick filters.
Factor exposures and variance decomposition.
“Why today is different” explainer.
Risk Analysis
Factor betas, variance decomposition, correlation heatmap.
Scenarios with deltas to risk/perf metrics.
Optimization
Strategy picker (min variance / max return), frontier, suggested weights, impact preview.
Design language
Keep Tailwind + existing CSS variables in src/index.css. Extend tokens minimally (chart palette, elevations).
Compact tables/charts by default; density toggle at page level.
Accessible color ramps and focus states; dark mode preserved.
Components to standardize
PageHeader, FilterBar (portfolio selector, date range, benchmark), StatCard, InsightCard.
Virtualized DataTable (TanStack Table + react-virtual).
Chart primitives (Recharts): unified tooltip/legend/colors; comparison mode.
Right-rail Insights (optional): explainers + one-click actions.
