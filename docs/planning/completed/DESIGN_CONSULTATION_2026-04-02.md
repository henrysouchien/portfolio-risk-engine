# Design Consultation — Full Review with Outside Voices

> Date: 2026-04-02
> Reviewers: Codex (GPT-5.4), Claude Subagent (Opus), Primary (fresh-eyes)
> Artifacts: `docs/design-unified-preview.html`, `DESIGN.md`, `docs/PRODUCT_POSITIONING.md`

---

## Competitive Landscape

**Table stakes (Layer 1):** Dark mode, dense monospaced tables, sidebar nav, red/green signal. Every product does this.

**Converging trends (Layer 2):** AI features bolted onto data display products (Koyfin chatbot, TradingView summaries). Customizable widget dashboards. All additive — none restructured layout around AI.

**First-principles break (Layer 3):** Every competitor is a data display tool that added AI. This product is an AI analyst that uses data as evidence. Insight-first layout (prose → evidence) is a genuine structural inversion. Chat-as-margin is closer to institutional research annotation than consumer chatbot.

---

## Three-Voice Consensus

### KEEP (all three agree):
1. **Analyst-first, prose-first hierarchy.** Nobody else does this. It's the product's identity.
2. **Gold scarcity rule.** Accent used ONLY for analyst direct address. Gives system identity.
3. **Two-register typography** (Instrument Sans prose vs Geist Mono data). Core visual contract.
4. **Generated artifact draw animation.** Strongest provenance signal. Behavioral, not just visual.
5. **Margin-as-annotations concept.** Correct inversion for analyst product (not chatbot-first).
6. **Revision marks.** Strongest visual expression of "analyst was working while you were away."

### WATCH (concerns raised):
1. **Signal layer count** — "The next round should be subtraction, not invention" (Codex). Opinion, evidence, generated artifact, report chart, revision, annotation, status line, margin sketch, presets — if each gets a strong visual cue, the system fragments.
2. **Gold semantic overload** — doing direct address, artifact marking, active emphasis, urgency dots. Risk of scarcity collapsing if it appears too often.
3. **`--ink` vs `--text` perceptibility** — 6-point luminance difference (#F2F0EC vs #E8E6E3). Subagent says imperceptible on calibrated displays. Size gap (20px vs 13px) does most of the work. If more separation needed, increase warmth (e.g., #F5F0E6), not luminance.
4. **12.5px Geist Mono in dark mode** — near the readability edge. Audit for actual reading comfort, not just density.

### DEBATE (voices diverged):

**A) Chat margin default state**
- Codex: 280px is generous but OK if well-ordered
- Subagent: Should default collapsed, icon strip with dots is better default
- Primary: Balanced at desktop, tight on laptops
- Resolution: Responsive — open at 1440px+, collapsed at <1280px

**B) Annotation tag count**
- Codex: "Make Confidence concrete or remove it"
- Subagent: "Two max: What changed + Source"
- Primary: 4 core tags OK as expandable disclosures, show 2-3 per insight based on relevance
- Resolution: Keep 4 (Methodology, What changed, Confidence, Source), surface contextually. Confidence only when tied to specific model limitations.

**C) Generated chart y-tick/container grammar**
- Codex: "Most original part" — keep it
- Subagent: y-tick semantics and container distinction won't survive user contact, keep draw + gold rail only
- Primary: Distinction is clear in preview
- Resolution: Keep draw animation + gold rail as primary provenance. Container/y-tick differences are secondary signals that reinforce but shouldn't be relied on alone.

**D) Over-designed elements (subagent flagged)**
- Y-before-X-by-40ms draw phasing — "love letter to yourself"
- Margin sketch-to-exhibit promotion — "designing bookshelf before books"
- 6 annotation tag types — "institutional overkill for single-user product"
- Resolution: These are aspirational spec items. Don't prioritize implementing them. Focus on basics first.

---

## Codebase Gap (Critical Finding — Subagent)

The subagent audited the actual frontend codebase and found the design system is not implemented:
- Zero custom fonts loaded (still system defaults)
- Zero `--ink` or `--surface-raised` tokens in use
- InsightBanner still uses emerald gradients, icon circles, colored backgrounds
- 226 occurrences of `rounded-2xl`/`rounded-3xl` (DESIGN.md caps at 6px panels)
- 142 skeleton loading states (explicitly banned in DESIGN.md)
- 26 files with breathing/floating/pulsing animations (explicitly banned)
- Tailwind config still has `breathe`, `float-gentle`, `pulse-gentle` keyframes

**Subagent's one-afternoon plan (all three voices endorse):**
1. Add Google Fonts link for Instrument Sans + Geist Mono (20 min)
2. Set CSS custom properties: `--ink`, `--surface-raised`, `--bg`, etc. (20 min)
3. Rewrite InsightBanner: kill color schemes/gradients/icons, make it `--surface-raised` + `--ink` 20px Instrument Sans (90 min)
4. Kill `animate-breathe`, `animate-float-gentle`, `animate-pulse-gentle`, `animate-stagger-fade-in` globally (30 min)
5. Add `font-variant-numeric: tabular-nums` to number-rendering elements (15 min)
6. Replace `rounded-2xl`/`rounded-3xl` with `rounded-md` on visible components (remaining time)

**Priority: Close the spec-to-codebase gap before extending the design system.**

---

## Preview Fixes Applied (this session)

| # | Fix | Files |
|---|-----|-------|
| 1 | Light `--surface-raised` #FFFFFF → #FDFCF9 (warm cream) | DESIGN.md + preview |
| 2 | Chat margin opacity 0.92 removed | preview |
| 3 | Light `--ticker-bg` #EEEEE8 → #E8E8E0 | DESIGN.md + preview |
| 4 | Sidebar active: 2px left indicator + icon opacity 1.0 | preview |
| 5 | Light-mode gold rail: 2px width + brighter #C8A44E | preview |
| 6 | Margin notes: card containers → bottom-border separators | preview |
| 7 | Exit ramps: 64px bottom padding clears controls bar | preview |

---

## Sources

- [Koyfin — features](https://www.koyfin.com/features/)
- [Koyfin — custom dashboards](https://www.koyfin.com/features/custom-dashboards/)
- [Balyasny AI research engine (OpenAI case study)](https://openai.com/index/balyasny-asset-management/)
- [AI in Portfolio Management — Wall Street Prep](https://www.wallstreetprep.com/knowledge/ai-in-portfolio-management/)
- [Muzli Dashboard Design Examples 2026](https://muz.li/blog/best-dashboard-design-examples-inspirations-for-2026/)
