# Product Positioning

> Created: 2026-03-31
> Updated: 2026-03-31
> Status: DRAFT
> Related: `DESIGN.md` (design system), `PRODUCT_ARCHITECTURE.md` (technical layers), `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md` (GTM)

---

## The One-Line

A personal AI investment analyst that actually knows your portfolio.

---

## The Problem

The founder built this because he needed it. Managing personal investments after having institutional infrastructure, the gap was immediate: a Schwab login, Yahoo Finance, a spreadsheet that's always out of date, and ChatGPT that doesn't know what you own. Investing quality degrades to gut feel.

Then the same gap showed up in his education program. Students range from retail investors to professional financial analysts, all learning fundamental investing. Every one of them faces the same problem: the tools available to individuals are either consumer-grade (Robinhood, Schwab dashboards) or data-only (Koyfin, Portfolio Visualizer). None of them tell you what to DO. None of them know YOUR portfolio well enough to have an opinion. None of them explain their reasoning in a way that builds your own analytical skill.

The gap isn't hypothetical. It's the founder's daily experience and the experience of a room full of people he already teaches. The alternative to this product is not a competitor. It's doing nothing and investing worse.

---

## What This Product Is

A comprehensive AI investment analyst with institutional-grade competence. It connects to your brokerage accounts, sees your actual positions, and does the full scope of work a human analyst would do: assess risk and factor exposures, attribute performance, diagnose concentration, stress test against historical and hypothetical scenarios, run Monte Carlo simulations, optimize allocations, analyze individual stocks, evaluate option strategies, scan for tax harvesting opportunities, project income, assess leverage capacity, generate rebalance trades, and execute through your broker.

You open the app and the analyst has already done the work. It tells you what happened, what needs attention, and what it recommends. When you want to go deeper, you ask it. When you want to act, it shows you how.

The critical word is "comprehensive." This is not a risk tool or a portfolio tracker with AI on top. It's the full analytical workflow — the same scope of work that a team of analysts, a risk manager, and a portfolio strategist would cover. 80+ analytical tools, 3000+ tests. When it says "DSU is 28% of your exposure and dragging YTD return by 4.7%, here are three ways to reduce that without killing your dividend income, and you have a $2,490 tax harvest opportunity that closes in 3 days," every part of that statement is backed by real computation across multiple analytical domains working together.

---

## What It Is NOT

- **Not a trading app.** Your broker handles execution. This is where you think.
- **Not a robo-advisor.** It doesn't manage your money. It makes you better at managing your own.
- **Not a dashboard.** Dashboards display data and wait for you to interpret it. This tells you what the data means.
- **Not a chatbot wrapper.** "We added AI" is not a product. The product is the analytical engine that makes the AI's answers credible.
- **Not a portfolio tracker.** Tracking is table stakes. The value is the opinion.
- **Not a risk tool.** Risk is one domain of many. The analyst covers performance, trading, tax, income, factors, optimization, research, and scenarios — the full scope of investment analysis.

---

## Who It's For

**First user: The founder.**
Built this to manage personal investments with institutional rigor. Is the primary dogfooder. Every feature exists because he hit a wall and built through it.

**First cohort: The education program.**
Students in the founder's fundamental investing program. A mix of retail investors learning to do real analysis and professional/financial analysts sharpening their process. They range from "knows what beta means and wants to go deeper" to "ran a book at a fund and now manages personal money." This is not a hypothetical persona — these are real people the founder teaches, with real portfolios, who will give direct feedback. The product's analytical depth (factor models, stress testing, Monte Carlo) doubles as teaching infrastructure: the annotation layer (Methodology, Assumption, What changed) explains the reasoning, not just the result.

**From there: Any sophisticated self-directed investor.**
Active investors who have outgrown Schwab/Fidelity dashboards and Yahoo Finance. Manages $100K+ across multiple brokers. Cares about risk, reads earnings reports, thinks about concentration. Hit the ceiling of consumer-grade tools.

**Not for:** Beginners. People who want to be told what to buy. People who want a set-and-forget robo-advisor. People who think a pie chart of sector weights is "portfolio analysis."

---

## What It Replaces

The product replaces a workflow, not a single tool.

**Before:** Broker app (check positions, execute trades) + Yahoo Finance (research, quotes) + spreadsheet (tracking, what-if scenarios) + ChatGPT (reasoning, "what should I do?"). Four apps, none of which know about each other, none of which have a complete picture, none of which can chain an analysis into a trade.

**After:** One place that connects to all your accounts, runs institutional-grade analysis on your actual positions, tells you what matters, lets you act on it, and remembers the conversation. Also explains its reasoning so you learn to think this way yourself.

Also replaces:
- The financial advisor who charges 1% AUM for a quarterly PDF you could generate yourself
- The Bloomberg terminal you can't justify at $24K/year for personal use
- The gut-feel investing that happens when you lose your analytical infrastructure
- The gap between learning fundamental investing and having tools that support it

---

## The Moat

"We have AI" is not a moat. Every product will have AI. The moat is the analytical engine that makes the AI's answers real.

**Engine depth.** 80+ specialized tools. Factor analysis, stress testing (historical + hypothetical), Monte Carlo simulation (3 distributions, 4 drift models), multi-objective portfolio optimization, realized performance attribution, option strategy analysis with Greeks, tax-loss harvest scanning, income projection, leverage capacity analysis, rebalance trade generation. 3000+ tests. This is not a weekend project. This is years of domain-specific engineering.

**Connected workflow.** The only product that connects live holdings → risk analysis → performance attribution → scenario modeling → optimization → tax scanning → trade generation → execution → AI reasoning in a single loop. Every domain feeds into every other. A stress test leads to a hedge recommendation, which leads to an optimization, which generates trades, which you can execute. Koyfin can show you data but can't Monte Carlo your positions. Portfolio Visualizer can run simulations but can't execute trades. ChatGPT can reason but has no live data. This product does all of it, connected.

**Institutional expertise + AI implementation.** Most people have either finance domain knowledge or AI engineering capability. Having both in the builder is what lets the product cross the gap between "AI chatbot about investing" and "AI that does what an analyst actually does." The code is replicable. The judgment about what an analyst actually needs is not.

**Built-in distribution.** The founder teaches fundamental investing to a cohort that includes both retail and professional investors. The product is the natural complement to the education: the program teaches you how to think about investing, the product gives you the tools to do it. The first users are already in the room, already motivated, already giving feedback.

---

## The Interaction Model

The product is not a dashboard you navigate. It's an analyst that presents to you.

**1. The analyst's unprompted report (dashboard views).**
You open the app and the analyst has already done the work. The overview is a morning briefing: what happened overnight, what needs your attention, what changed since you last looked. Holdings is a concentration review. Performance is a progress report. Risk is a factor briefing. Trading shows your execution quality. Each view covers a different domain of the analyst's full scope, reads top-to-bottom like an analyst's note: insight first, supporting data, recommended actions.

**2. The analyst answering your questions (scenario tools).**
You ask "stress test my portfolio," "what if I hedge this," "optimize my allocation," "scan for tax harvest opportunities," "simulate forward 12 months," "look up this stock." The analyst runs the analysis across whatever domain the question touches and presents a finding with diagnosis, evidence, and recommendations. This is the strongest part of the product today. The scenario tools already feel like an analyst talking.

**3. "Tell me more" (AI chat + analyst's canvas).**
Not a sidebar chatbot. A communication channel between you and the analyst. Every insight, every chart, every recommendation has an entry point: ask the analyst about this. The chat is a structural part of the layout, not a floating widget. The boundary between "reading the report" and "talking to the analyst" blurs by design.

The analyst has a canvas. When text isn't enough to make a point, the analyst produces a visual — a custom chart, an interactive exploration, a comparison. "Your Real Estate concentration has been drifting for 3 months — here's what happened:" followed by a generated weight-over-time chart with the analyst's callouts. This appears inline, annotated, and explained. The user doesn't switch to a different mode or open a different view. The analyst just... shows them. Generated artifacts carry the same annotation tags (Methodology, Assumption) as prose insights. They can be interactive (sliders, toggles) when that helps the explanation. They feel authored, not system-generated.

**4. The analyst working while you're away (autonomous skills).**
Morning briefing generated before you open the app. Risk limit breach alerts. Earnings preview for held positions. Exit signal scans. Tax harvest windows opening. Performance milestones. The analyst does the work overnight across every domain and brings you the findings. This is what turns "useful tool" into "I need to open this every morning."

Mode 4 is the product's endgame. When the analyst has something new to tell you every time you open the app, the engagement problem solves itself.

---

## The Entry Point

Two entry points, not one.

**For the education cohort (warm):** The founder introduces it during the program. "This is what I use to manage my own portfolio. Here's what it says about a sample portfolio. Upload yours." No marketing funnel. Direct, in-context, with the founder available to explain what the analyst is showing them. The product's annotation layer (Methodology, Assumption) serves double duty: analytical transparency AND teaching tool.

**For cold traffic:** "Upload your portfolio. Get an AI-generated analyst briefing — risk score, factor exposures, concentration diagnosis, performance attribution, tax harvest opportunities, and specific recommendations — in 60 seconds." The risk score is the hook, but the breadth is the retention: users realize this isn't a risk tool, it's a full analyst covering every angle of their portfolio.

**Progressive engagement (both paths):**
1. Upload CSV → instant briefing + risk score + AI-generated analysis (free)
2. "Want live data?" → connect via Plaid OAuth (10,000+ institutions)
3. "Want the analyst working for you?" → AI agent, skills, memory (Pro tier)
4. "Want to act on recommendations?" → connect broker API for trading

Each step adds value. No step is mandatory. A user can get real value from step 1 alone.

---

## The Differentiation

| | This product | Koyfin | Portfolio Visualizer | Wealthfront | ChatGPT |
|---|---|---|---|---|---|
| Knows your positions | Yes (live) | No | Manual input | Yes (managed) | No |
| Factor analysis | Yes | Partial | Yes | No | No |
| Stress testing | Yes (custom) | No | Limited | No | Can discuss |
| Performance attribution | Yes | Partial | Yes | No | No |
| Tax harvest scanning | Yes | No | No | Yes (auto) | No |
| Portfolio optimization | Yes (multi-objective) | No | Basic | Auto-only | No |
| Option analysis | Yes (Greeks, strategies) | No | No | No | Can discuss |
| Stock research | Yes (fundamentals + AI) | Yes (data-only) | No | No | Yes (blind) |
| Has opinions | Yes | No | No | Preset | Generic |
| Can trade | Yes | No | No | Auto-only | No |
| AI reasoning | Yes (contextual) | No | No | No | Yes (blind) |
| Tool chaining | Full loop | N/A | N/A | N/A | N/A |
| Explains reasoning | Yes (annotations) | No | No | No | Sometimes |
| Remembers you | Yes | N/A | No | Preset | Session only |

The unique position: **comprehensive analytical depth across every investment domain + AI that reasons about YOUR portfolio + ability to act on the recommendations + explains its reasoning so you learn.** No other product combines all four.

---

## The Design Implication

If the product is "an analyst presenting to you," the design follows:

- **Editorial, not industrial.** The analyst's opinion layer reads like a research note. Dense data where data lives, but insight sections have editorial pacing and breathing room.
- **Prose-first, not metrics-first.** The analyst's sentence is the hero element. Numbers are evidence, subordinate. Every view opens with an opinion in plain English.
- **Two visual registers.** Warm `--ink` text for the analyst's voice, cool `--text` for data. The user's eye learns which is which.
- **The interface is a communication surface, not a report container.** The analyst can produce visual artifacts dynamically — custom charts, interactive explorations, comparisons — that appear inline without breaking the reading flow. The layout accommodates generated content alongside pre-built reports.
- **Chat as structural margin, not bolted-on widget.** The "tell me more" interaction is part of the layout, not a floating modal. Default state is annotations-first (methodology, what-changed, related conversations). The margin is part of the communication channel.
- **No empty states that look like a system.** The analyst doesn't show you a blank report. Conversational sentences before and during loading.
- **Polished like a well-crafted communication, not like a SaaS product.** The difference between "someone built this for me" and "this product is well-engineered."

See `DESIGN.md` for the full design system.

---

## What Needs to Be True

For this positioning to hold:

1. **The analyst must actually have something to say.** Static portfolio data displayed nicely is a dashboard, regardless of layout. The skills system (morning briefing, risk check, exit signal scan) is what generates the content that makes the analyst feel alive. Without mode 4, the product is useful but not engaging.

2. **The analytical depth must be real.** Every insight must be backed by actual computation, not LLM-generated plausible-sounding advice. The engine IS the product. If the factor analysis breaks, the analyst loses credibility.

3. **60-second time-to-value on first visit.** Upload CSV → see your risk score + AI briefing. If onboarding takes 10 minutes, the hook doesn't land. For the education cohort, the founder is there to walk them through it. For cold traffic, the product must stand alone.

4. **The chat must feel integrated, not separate.** The UI has three layers: the viewer (the analyst's polished output), the analyst (available to help, explain, drive), and direct access (tools, scenarios). These are complementary, not competing. The chat is not a bolted-on sidebar. It's the analyst being available — subordinate to the report when you're reading, primary when you're asking. The visual hierarchy must make this legible.

5. **The annotation layer must serve both credibility and learning.** For experienced investors, "Methodology: factor decomposition via 11-factor model" is transparency. For students in the education program, it's a lesson. The same feature serves both audiences because both need to understand HOW the analyst arrived at its opinion.

6. **Generated artifacts must feel authored, not system-generated.** When the analyst produces a custom chart or interactive exploration, it must carry the same annotation tags, the same visual language, the same analyst voice as everything else. A generated visualization should feel like it was drawn for you by someone who understands your portfolio, not rendered by a charting library. This is the difference between "the system generated a chart" and "the analyst showed me something."

---

## How We Got Here

This product was not designed top-down. It was built bottom-up from the founder's actual needs, and each layer expanded the scope:

1. Needed to update financial models → built model-engine
2. Needed risk analysis on personal portfolio → built portfolio-risk-engine (factor models, stress testing)
3. Wanted it all accessible through Claude Code → built MCP tools (fmp-mcp, ibkr-mcp, portfolio-mcp)
4. Needed to trade on recommendations → built brokerage-connect + trade execution
5. Realized this is an agent, not a tool collection → built agent runner, memory, skills
6. Needed research done by the agent → built stock fundamentals, earnings transcripts, market context
7. Needed performance tracking → built realized performance attribution, trading analysis
8. Needed tax efficiency → built tax harvest scanner, wash sale detection
9. Needed income planning → built income projection, leverage capacity analysis
10. Needed portfolio construction → built multi-objective optimizer, rebalance trade generation
11. Needed a visual surface for people who don't live in terminals → built the dashboard

What started as a risk analysis tool became a comprehensive investment analyst. Every piece exists because the founder hit a wall and built through it. That's why it all fits together — it was built as one expanding workflow, not assembled from features. Risk was the starting point, not the boundary. The dashboard is the last piece because it was the last thing the founder needed. Now it's needed because other people can't live inside a terminal.

---

## Next Steps

1. **Lock the design system.** DESIGN.md updated with full editorial toolkit (ticker tape, dateline, revision marks, annotation layer, urgency hierarchy, chart language). Three-layer visual hierarchy (viewer dominant, analyst subordinate, tools chrome) resolves the report-vs-chat tension. Preview at `/tmp/design-consultation-preview.html`.
2. **Wire up mode 4 (autonomous content).** Morning briefing skill, risk alerts, "what changed since yesterday." Revision marks make this visible. This is what makes the analyst feel alive.
3. **Education cohort beta.** Not 10 hand-picked strangers — the founder's own students. They're already learning fundamental investing. The product is the practical complement to the education. Introduce it during the program, observe directly, iterate on their actual usage.
4. **Iterate based on what the cohort actually does.** What do they open? What do they ignore? What do they ask the analyst about? What annotations do they expand? The education context gives richer feedback than cold users because the founder can ask follow-up questions in person.

---

*This document captures the product positioning as of 2026-03-31. It synthesizes the office hours review (2026-03-19), product architecture doc (2026-02-23), open source launch strategy (2026-03-16), the design system evolution (2026-03-30), and the design consultation (2026-03-31) which sharpened the audience from abstract personas to the founder + education program cohort. The positioning should be re-evaluated after the education cohort beta produces user feedback.*
