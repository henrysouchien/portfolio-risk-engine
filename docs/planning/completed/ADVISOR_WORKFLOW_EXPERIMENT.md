# Advisor Workflow Experiment

> **Goal**: Run an advisor agent against real questions to discover natural tool usage patterns.
> These patterns inform the frontend toolbox UI — which tools cluster, what sequence, what's high-frequency.

---

## Advisor Agent Profile

```
You are an expert financial advisor managing a personal investment portfolio.
You have access to a comprehensive set of portfolio analysis tools (the "Advisor Toolbox").

Your approach:
- Always start by understanding the current state before making recommendations
- Use data to support every recommendation — never speculate without running the numbers
- Consider risk, tax implications, and portfolio fit for every decision
- Be direct and action-oriented — end with specific next steps

When answering questions, use whatever tools you need to give a thorough, data-backed answer.
Think out loud about which tools you're using and why.
```

---

## Question Bank (30 questions)

### Morning Check-In (what should I know today?)

1. "Give me a morning briefing on my portfolio — any alerts, news, or positions I should pay attention to?"
2. "What happened to my portfolio this week? Any significant moves?"
3. "Are there any upcoming earnings or dividends for my holdings?"
4. "Do I have any option positions expiring soon that need attention?"

### Risk Review (am I safe?)

5. "Am I overexposed to any single sector or factor right now?"
6. "What's my overall risk score and am I within my risk limits?"
7. "How would my portfolio hold up in a 2008-style crash?"
8. "Is my portfolio too concentrated in mega-cap tech?"
9. "What's my downside risk — how much could I lose in a bad month?"

### Performance Evaluation (how am I doing?)

10. "How is my portfolio performing versus the S&P 500 this year?"
11. "Which positions are dragging down my returns?"
12. "What's my Sharpe ratio and is my risk-adjusted return any good?"
13. "Am I a good trader? How's my timing and win rate?"

### Research & Stock Analysis (should I buy/sell this?)

14. "Should I add NVDA at current levels? How does it fit my portfolio?"
15. "I'm thinking about adding bond exposure — what's the best way?"
16. "Compare AAPL vs MSFT vs GOOGL — which is the best fit for my portfolio right now?"
17. "What are the top hedge candidates for my biggest risk exposures?"

### Planning & What-If (what should I change?)

18. "What if I shift 10% from equities to bonds — how does that change my risk?"
19. "What's the optimal allocation for my portfolio given my risk tolerance?"
20. "Should I rebalance? How far have I drifted from my targets?"
21. "Run a backtest — how would a 60/40 portfolio have done over the last 5 years versus my current allocation?"
22. "Show me the efficient frontier — where am I on it and where should I be?"

### Tax & Income (money management)

23. "Any tax-loss harvesting opportunities before year end?"
24. "What's my projected dividend income for the next 12 months?"
25. "Which of my losing positions should I sell for tax purposes?"

### Execution (do something)

26. "Generate the rebalance trades to get me back to my target allocation"
27. "I want to buy 100 shares of AAPL — preview the trade"
28. "Create a basket of the top 10 S&P 500 holdings so I can track it"
29. "What are my open orders right now?"

### Hot Topics 2026 (current market concerns)

30. "I'm worried about AI concentration risk — how exposed am I to the Magnificent 7?"
31. "With rates staying higher for longer, should I extend my bond duration?"
32. "How diversified am I really? Are my 'diversifiers' actually correlated?"
33. "What's my portfolio's sensitivity to a tariff-driven market selloff?"

---

## Experiment Protocol

### For each question, capture:

1. **Tools called** (in order)
2. **Tool inputs** (what parameters were used)
3. **Tool dependencies** (which tools needed output from prior tools)
4. **Decision point** (where the agent stopped gathering and started recommending)
5. **Final action** (what concrete step was recommended)

### Analysis outputs:

- **Co-occurrence matrix**: Which tools are used together most often?
- **Sequence patterns**: What's the typical tool chain for each question type?
- **Entry points**: What's the FIRST tool called for each category?
- **Frequency distribution**: Which tools appear across the most questions?
- **Natural groupings**: Do the tool clusters match our 5-section nav hypothesis?

---

## Expected Tool Chains (Hypothesis)

| Question Type | Expected Chain |
|---|---|
| Morning check-in | `get_positions` → `get_risk_score` → `get_portfolio_news` → `get_portfolio_events_calendar` → `monitor_hedge_positions` |
| Risk review | `get_risk_analysis` → `get_factor_analysis` → `get_factor_recommendations` |
| Performance | `get_performance` → `get_trading_analysis` |
| Stock research | `analyze_stock` → `get_quote` → (portfolio context from `get_positions`) |
| What-if planning | `get_positions` → `run_whatif` → `compare_scenarios` → `generate_rebalance_trades` |
| Tax optimization | `suggest_tax_loss_harvest` → `get_trading_analysis` |
| Execution | `preview_trade` → `execute_trade` |

These are hypotheses — the experiment will validate or challenge them.
