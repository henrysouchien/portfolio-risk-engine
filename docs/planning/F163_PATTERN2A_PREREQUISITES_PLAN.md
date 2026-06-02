# F163 — Pattern 2A Completion Prerequisites

**Status:** DRAFT R1 — needs Codex review.
**Created:** 2026-06-01.
**Scope:** Three missing prerequisites that must ship alongside or before F122 for Pattern 2A to produce usable output: (1) design system CSS bundle injected into the sandboxed iframe, (2) structural quality gate with markdown fallback, (3) agent prompt documentation of available HTML classes.

**Authority:** `docs/reference/VISUALIZATION_STACK.md` §"Pattern A — Agent-Rendered HTML" + §"Gaps & next steps — Pattern 2A"; `docs/planning/F122_HTML_ARTIFACT_RENDERER_SPEC.md` §7 (sandbox model); `DESIGN.md` (token source of truth).

**Why this plan exists:** F122's impl plan (PASS R3, 2026-05-31) specifies the rendering pipeline and sandbox correctly but does not define the CSS the agent targets or the quality gate that prevents unstyled or broken HTML from reaching the user. Without both, Pattern 2A ships but produces artifacts that either render unstyled (design regression) or, worse, render malformed output with no fallback. The agent prompt gap means agents will guess class names that don't exist.

**Relationship to F122:** These are additive deliverables, not changes to the locked F122 PR sequence. PR-1 and PR-2 below extend `buildSandboxedDocument.ts` (which F122 PR-5 creates). The agent methodology PR (PR-3) is a separate ai-excel-addin change that ships alongside F122 impl.

---

## 1. Architecture

```
Agent emits HTML using known semantic class names
           ↓
ai-excel-addin: HtmlArtifact stored (.html + .json sidecar)
           ↓
risk_module: F122 proxy fetches + passes to renderer
           ↓
buildSandboxedDocument.ts
  ├─ Quality gate: structural validation → fallback to markdown if fail
  ├─ Inject <style> block from AGENT_ARTIFACT_STYLES (the CSS bundle)
  └─ Wrap in <html><head>CSP meta</head><body>agent HTML</body></html>
           ↓
<iframe srcDoc={...} sandbox="allow-scripts" />
```

The CSS bundle is a TypeScript const string (not a `.css` file loaded at runtime). The styles are injected as a `<style>` block at document-build time — the only reliable path because the CSP F122 locks (`default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'`) must not be changed. No Google Fonts, no external `<link>` loads. Fonts fall back to `system-ui, sans-serif` and `monospace` — design tokens (colors, spacing, class semantics) are what matter for agent artifacts; exact typefaces are secondary for v1. (Q2 decided: system fonts; Q1 decided: TS const.)

---

## 2. PR Sequencing

| PR | Repo | Scope | Gate |
|---|---|---|---|
| PR-1 | risk_module | CSS bundle const + `buildSandboxedDocument.ts` injection | Extends F122 PR-5 deliverable |
| PR-2 | risk_module | Quality gate + markdown fallback in renderer | Extends F122 PR-5 renderer component |
| PR-3 | ai-excel-addin | Extend `emit_html_artifact` tool description with HTML class reference | Part of HTML addendum impl; ships alongside it |

PRs 1 and 2 are bundled into the F122 PR-5 dispatch brief. PR-3 is part of the HTML addendum impl (ai-excel-addin) and must ship before the first live `emit_html_artifact` call in any skill.

---

## 3. PR-1 — Design system CSS bundle

### New file
`frontend/packages/ui/src/components/research/artifact/agentArtifactStyles.ts`

Exports a single const string: `AGENT_ARTIFACT_STYLES`. Contents mirror DESIGN.md tokens and define semantic classes the agent targets.

**CSS custom properties (dark theme defaults, light theme via `@media (prefers-color-scheme: light)`):**

```css
:root {
  --bg: #0F1115;
  --surface: #1A1D23;
  --surface-raised: #21252D;
  --border: #2A2E36;
  --border-subtle: #1F2229;
  --ink: #F2F0EC;
  --text: #E8E6E3;
  --text-muted: #6B6F76;
  --text-dim: #484C54;
  --accent: #C8A44E;
  --up: #34A853;
  --down: #EA4335;
  --up-bg: rgba(52,168,83,0.08);
  --down-bg: rgba(234,67,53,0.08);
  --surface-2: #22262E;
}
@media (prefers-color-scheme: light) {
  :root {
    --bg: #F8F8F6;
    --surface: #FFFFFF;
    --surface-raised: #FDFCF9;
    --border: #D2D2CC;
    --border-subtle: #D8D8D2;
    --ink: #1C1917;
    --text: #1A1D23;
    --text-muted: #6B6F76;
    --text-dim: #838790;
    --accent: #9E7E2E;
    --up: #1B7F37;
    --down: #C5221F;
    --surface-2: #F0F0EE;
  }
}
```

**Base reset + typography:**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Instrument Sans', system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.5;
  padding: 16px;
}
```

**Semantic classes (what the agent uses):**

| Class | Renders as | Key CSS |
|---|---|---|
| `.insight` | Analyst's opening statement | `font-size: 16px; color: var(--ink); padding: 12px 16px; background: var(--surface-raised)` |
| `.metric-strip` | Horizontal key metrics row | `display: flex; gap: 0; border: 1px solid var(--border)` |
| `.metric-strip .metric` | Single metric cell | `flex: 1; padding: 8px 12px; border-right: 1px solid var(--border); text-align: center` |
| `.metric-strip .metric .label` | Metric label | `font-family: 'Geist Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-dim)` |
| `.metric-strip .metric .value` | Metric value | `font-family: 'Geist Mono', monospace; font-size: 13px; font-variant-numeric: tabular-nums` |
| `.data-table` | Financial data table | `width: 100%; border-collapse: collapse; font-family: 'Geist Mono', monospace; font-size: 12.5px` |
| `.data-table th` | Table header | `font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-dim); padding: 6px 8px; border-bottom: 1px solid var(--border); text-align: left` |
| `.data-table td` | Table cell | `padding: 6px 8px; border-bottom: 1px solid var(--border-subtle); font-variant-numeric: tabular-nums` |
| `.section-break` | Named section divider | `font-family: 'Geist Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-dim); padding: 12px 0 6px; border-bottom: 1px solid var(--border-subtle)` |
| `.comparison-table` | Before/after comparison | Extends `.data-table`; `.current` col uses `var(--text)`, `.proposed` col uses `var(--text)`, `.delta` col uses `var(--up)` / `var(--down)` via `.up` / `.down` helper classes |
| `.up` | Positive financial direction | `color: var(--up)` |
| `.down` | Negative financial direction | `color: var(--down)` |
| `.source-chip` | Citation reference | `font-family: 'Geist Mono', monospace; font-size: 10px; color: var(--text-muted); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px` |
| `.prose` | Analyst narrative text | `font-size: 13px; color: var(--text); line-height: 1.6` |
| `.prose.large` | Primary analyst voice | `font-size: 16px; color: var(--ink)` |
| `.artifact-claim` | Analyst's claim sentence above the exhibit | `font-size: 16px; color: var(--ink); line-height: 1.5; margin-bottom: 8px` |
| `.artifact-exhibit` | The exhibit itself — no container, gold provenance rail | `border-left: 1px solid var(--accent); padding-left: 14px; margin: 8px 0` |
| `.artifact-interpretation` | Interpretation sentence below the exhibit | `font-size: 13px; color: var(--text-muted); margin-top: 8px` |
| `.gen-stamp` | GEN timestamp bottom-right provenance mark | `font-family: monospace; font-size: 9px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.1em` |
| `.annotation-tag` | Expandable metadata tag (Methodology, As of, etc.) | `font-family: monospace; font-size: 10px; color: var(--text-muted); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; cursor: pointer` |
| `.exit-ramps` | Exit ramp links row | `margin-top: 12px; font-size: 13px; color: var(--text)` |
| `.exit-ramps a` | Individual exit ramp link | `color: var(--text); text-decoration: none` — arrow `→` styled `color: var(--accent)` |
| `.preset-pills` | Interactive control strip (parametric artifacts only) | `display: flex; gap: 6px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border-subtle)` |
| `.preset-pills button` | Individual preset pill | `font-family: monospace; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; border: 1px solid var(--border); background: none; color: var(--text-muted); padding: 3px 8px; cursor: pointer` |
| `.preset-pills button.active` | Active preset pill | `background: var(--surface-2); color: var(--ink)` |

**No external fonts.** The F122-locked CSP (`default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'`) must not be changed. Font families in the CSS bundle use `system-ui, sans-serif` and `monospace` as v1 system-font fallbacks. Design tokens (colors, spacing, class semantics) are what matter for agent artifacts.

### Modify `buildSandboxedDocument.ts` (F122 PR-5)

Add `AGENT_ARTIFACT_STYLES` import. Inject as `<style>` block in the document head:

```ts
import { AGENT_ARTIFACT_STYLES } from './agentArtifactStyles';

// Must be identical to SANDBOX_CSP_V1 in F122_HTML_ARTIFACT_RENDERER_SPEC.md §7
const SANDBOX_CSP_V1 =
  "default-src 'none';" +
  "script-src 'unsafe-inline';" +
  "style-src 'unsafe-inline';" +
  "img-src data:;" +
  "font-src data:;" +
  "connect-src 'none';" +
  "form-action 'none';" +
  "base-uri 'none';" +
  "object-src 'none';" +
  "frame-src 'none';" +
  "frame-ancestors 'none';";

export function buildSandboxedDocument(htmlContent: string): string {
  // F122 locked behavior: strip any outer document wrappers the agent may have emitted
  // (<!DOCTYPE>, <html>, <head>, <body> tags) before injecting into the controlled skeleton.
  // F163 adds CSS injection to this existing normalization step — do NOT replace the
  // stripOuterDocumentWrappers call; add AGENT_ARTIFACT_STYLES alongside it.
  const normalizedBody = stripOuterDocumentWrappers(htmlContent);
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="${SANDBOX_CSP_V1}">
  <style>${AGENT_ARTIFACT_STYLES}</style>
</head>
<body>${normalizedBody}</body>
</html>`;
}
```

The CSP const is imported from or duplicated in lockstep with F122's `SANDBOX_CSP_V1`. No changes to F122's locked tests or CSP assertions. If F122 updates the CSP, F163 follows.

### Tests
- `buildSandboxedDocument` output contains `<style>` block with at least one CSS custom property
- Dark and light theme tokens both present
- All semantic class names from the table above present in the bundle
- Output is parseable as HTML

---

## 4. PR-2 — Quality gate + markdown fallback

### Where it lives
In the `HtmlArtifactRenderer` component (F122 PR-5), before passing content to `buildSandboxedDocument`.

### Validation rules

Use DOM-based checks (not regex) — `DOMParser` with `'text/html'` is best-effort and does NOT reliably produce a `<parsererror>` element for malformed HTML. Parse into a DOM and inspect the tree.

A valid agent HTML artifact must pass all of:

1. **Size limit** — raw HTML must be `< 50_000` characters (checked before parse).
2. **No forbidden tags** — the DOM must contain none of: `script`, `style`, `link`, `meta`, `base`, `iframe`, `object`, `embed`, `form`. Agent HTML must not define its own styles or scripts; all styling comes from the injected CSS bundle.
3. **No inline `style` attributes** — `doc.querySelector('[style]')` must return null.
4. **No event handler attributes** — reject any element with an `on*` attribute (`onclick`, `onload`, `onerror`, etc.). F122 keeps `sandbox="allow-scripts"` + `script-src 'unsafe-inline'`, so inline handlers are executable.
5. **No `javascript:` scheme URIs** — for each element, read `href`, `src`, and `action` via `getAttribute`. Normalize before checking: (a) strip embedded tab/LF/CR via `replace(/[\t\n\r]/g, '')`, (b) strip leading/trailing C0 controls and spaces via `replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '')`, (c) `.toLowerCase()`, then `.startsWith('javascript:')`. Both steps are required: browsers normalize embedded control chars AND strip leading/trailing C0/space before parsing the scheme, so skipping either allows bypass. No CSS selectors.
6. **Non-empty body** — `doc.body.textContent?.trim()` must be non-empty.

Any failing check is a validation failure: the renderer shows the markdown fallback instead of the iframe.

### Fallback surface

On validation failure, render `sidecar.summary` as a `MarkdownRenderer` block (field name confirmed in F122 impl plan §8 line 165). If `sidecar.exports?.copy_as_markdown` is present and non-empty, prefer that as it contains richer rendered content. Append a `[⚠ Rendering unavailable — artifact structure invalid]` caption in `--text-dim` / monospace 10px.

Do not show raw HTML, do not throw, do not leave a blank space.

### Implementation sketch

```ts
const FORBIDDEN_TAGS = ['script', 'style', 'link', 'meta', 'base', 'iframe', 'object', 'embed', 'form'];

function validateAgentHtml(html: string): { valid: true } | { valid: false; reason: string } {
  if (html.length > 50_000) return { valid: false, reason: 'size_limit' };
  const doc = new DOMParser().parseFromString(`<html><body>${html}</body></html>`, 'text/html');
  for (const tag of FORBIDDEN_TAGS) {
    if (doc.querySelector(tag)) return { valid: false, reason: `forbidden_tag_${tag}` };
  }
  if (doc.querySelector('[style]')) return { valid: false, reason: 'inline_style_attr' };
  // Reject on* event handlers (executable under sandbox="allow-scripts")
  const allElements = Array.from(doc.querySelectorAll('*'));
  for (const el of allElements) {
    for (const attr of Array.from(el.attributes)) {
      if (attr.name.startsWith('on')) return { valid: false, reason: 'event_handler_attr' };
    }
  }
  // Reject javascript: scheme URIs.
  // Strip ASCII whitespace control chars before lowercasing — browsers normalize
  // embedded \t/\n/\r in URLs (e.g. "java\nscript:" → "javascript:") but trim() does not.
  const urlAttrs = ['href', 'src', 'action'];
  for (const el of allElements) {
    for (const attrName of urlAttrs) {
      const raw = el.getAttribute(attrName);
      if (raw != null) {
        const normalized = raw
          .replace(/[\t\n\r]/g, '')
          .replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, '')
          .toLowerCase();
        if (normalized.startsWith('javascript:')) {
          return { valid: false, reason: 'javascript_uri' };
        }
      }
    }
  }
  if (!doc.body.textContent?.trim()) return { valid: false, reason: 'empty_body' };
  return { valid: true };
}
```

Note: wrapping the agent HTML in `<html><body>...</body></html>` before parsing ensures `doc.body` is always available and prevents fragment quirks.

### Tests
- Each forbidden tag variant rejects correctly
- `[style]` attribute rejects correctly
- `onclick` and other `on*` attributes reject correctly
- `href="javascript:"` rejects correctly
- Size limit rejects correctly
- Valid HTML using only semantic classes passes
- Invalid HTML falls back to `sidecar.summary` + caption, no throw
- Missing `summary` falls back gracefully (no crash)

---

## 5. PR-3 — Agent prompt HTML class documentation (ai-excel-addin)

### Where it lives — tool description, not methodology file

`api/memory/workspace/notes/methodology/` files are `MethodologyUnit` entries that require YAML frontmatter and are accessed via explicit `memory_read` calls — they are NOT automatically injected into every prompt. The analyst system prompt only auto-injects `_answer-fidelity.md`. A new methodology file here would not reach the agent at tool-call time.

The correct injection point is the **`emit_html_artifact` tool description** in the gateway foundation layer (ai-excel-addin). Tool descriptions are part of the MCP tool manifest and are always visible to the model when the tool is available. This is where the class documentation belongs.

### Change: extend `emit_html_artifact` tool description

In the gateway foundation layer (ai-excel-addin, part of the HTML addendum impl), extend the `emit_html_artifact` tool's `description` field to include the available semantic classes and correct usage pattern. Specifically, append a "## HTML class reference" section to the tool description covering:

### Content structure

The text below is the tool description content to append to `emit_html_artifact`. It uses no nested code fences to avoid markdown rendering issues in the tool manifest.

---

**HTML Artifact Authoring**

When you call `emit_html_artifact`, your `html_content` is rendered in a sandboxed iframe that injects the Hank design system. Use semantic classes only — never `style=` attributes, `<style>` tags, or `<script>` tags.

**Available classes — Layout:**
- `.insight` — opening analyst statement (ink color, raised background)
- `.prose` — body narrative text (13px)
- `.prose.large` — primary analyst voice (16px, ink color)
- `.section-break` — named section divider (monospace uppercase label)

**Available classes — Data display:**
- `.metric-strip` — horizontal key metrics row; each cell: `.metric` > `.label` + `.value`
- `.data-table` — financial data table (monospace, compact rows)
- `.comparison-table` — before/after table; add `.up` / `.down` to delta cells

**Available classes — Analyst Canvas (generated artifacts):**
- `.artifact-claim` — claim sentence above the exhibit (16px, ink color)
- `.artifact-exhibit` — exhibit with 1px gold left provenance rail, 14px internal padding
- `.artifact-interpretation` — interpretation sentence below the exhibit (13px, muted color)
- `.gen-stamp` — GEN timestamp provenance mark (monospace 9px uppercase)
- `.annotation-tag` — expandable metadata tag (monospace 10px, bordered)
- `.exit-ramps` — exit ramp links row; arrow characters use accent color
- `.preset-pills` — interactive control strip; `.preset-pills button` for each option; add `.active` class to selected

**Available classes — Utilities:**
- `.up` — positive financial direction (green)
- `.down` — negative financial direction (red)
- `.source-chip` — citation reference inline (monospace 10px, bordered)

**Correct pattern example:**

    <div class="insight">Your portfolio would lose $47,200 (-6.8%) in a 2022-style rate shock.</div>
    <div class="section-break">SCENARIO RESULTS</div>
    <div class="metric-strip">
      <div class="metric"><span class="label">PORTFOLIO LOSS</span><span class="value down">-6.8%</span></div>
      <div class="metric"><span class="label">TOP DRIVER</span><span class="value">DSU -14.2%</span></div>
    </div>

**Never do this:**
- No `style="..."` attributes — validation rejects any inline style
- No `<script>`, `<style>`, `<link>`, `<meta>`, `<base>`, `<iframe>`, `<form>` tags
- No `on*` event handler attributes (`onclick`, `onload`, etc.)
- No `javascript:` URIs in `href`, `src`, or `action`
- No inline color values — use `.up` / `.down` for financial direction
- No HTML longer than ~50,000 characters

---

### Tests (ai-excel-addin)
- `emit_html_artifact` tool description includes class reference and forbidden-pattern list
- Integration smoke: confirm a reference artifact using only documented classes passes the risk_module quality gate

---

## 6. Verification

After all 3 PRs land:

1. Manually emit an `HtmlArtifact` from the dev gateway using a fixture that uses the semantic classes above.
2. Confirm the artifact renders styled (not plain HTML) in the research workspace iframe.
3. Confirm an artifact with an inline `style=` attribute falls back to `sidecar.summary` + caption.
4. Confirm CSS custom property tokens (`--ink`, `--accent`, etc.) are visible in the rendered iframe.
5. Confirm dark/light theme tokens render correctly in each mode.
6. Confirm the F122 CSP test suite still passes unchanged.

---

## 7. Open decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Should the CSS bundle be a `.ts` const or a `.css` file imported via Vite's `?raw` loader? | **DECIDED: `.ts` const** — avoids Vite build config changes, works in tests without asset pipeline. |
| Q2 | Font loading via Google Fonts in sandbox — acceptable? | **DECIDED: system fonts for v1** — no external `<link>`, no CSP change. Design tokens are the priority; typeface fidelity is a v2 enhancement if needed. |
| Q3 | Should PR-1/PR-2 be part of F122 PR-5 or a separate follow-on PR? | **DECIDED: bundle into F122 PR-5 dispatch brief** — flag in the Codex dispatch prompt that `buildSandboxedDocument.ts` must include CSS injection + validation gate. |
| Q4 | Where does class documentation inject? | **DECIDED: `emit_html_artifact` tool description** — this is the only path that reaches the agent reliably at tool-call time. Methodology files require explicit `memory_read`; they are not auto-injected. |
