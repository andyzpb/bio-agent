# Akashic Dashboard Design Spec

This document is the source of truth for the current dashboard visual and
interaction direction. The previous editorial warm-cream/coral/serif direction
has been retired. The active direction is a Codex-style neutral agent
workspace: compact, task-oriented, low-noise, and review-first for
application-level plugins.

Do not use Tailwind, Bootstrap classes, or inline styles for dashboard UI.
Prefer shared CSS tokens in `static/dashboard/styles.css` and plugin-local
tokens only when an application plugin needs a scoped visual system.

## 1. Visual Direction

The dashboard should feel like an agent workbench, not a marketing page or a
decorative analytics dashboard.

Core traits:

- neutral black/gray palette;
- thin hairline borders;
- minimal shadows;
- 8px or smaller radius for ordinary controls and cards;
- compact information density;
- short navigation labels;
- progressive disclosure for raw JSON, trace, graph, and debug tools;
- no decorative gradients, orbs, bokeh, or large color blocks.

For application-level plugins, optimize for the user's primary workflow. The
Biomedical Evidence plugin is Review-first: reviewers should see recent runs,
claim cards, validation, audit action, and evidence/provenance links before raw
graph nodes or full trace JSON.

## 2. Tokens

The canonical dashboard tokens live in `static/dashboard/styles.css`:

```css
:root {
  --bg:           #f7f7f5;
  --bg-soft:      #f0f0ed;
  --paper:        #fbfbfa;
  --paper-strong: #ffffff;

  --line:         #deded8;
  --line-strong:  #a8a8a2;
  --line-soft:    rgba(23, 23, 23, 0.07);

  --text:         #171717;
  --text-soft:    #6f6f6a;

  --accent:       #171717;
  --accent-soft:  #ecefed;
  --accent-hover: #000000;

  --green:        #5db872;
  --green-soft:   #e1f0e7;
  --yellow-soft:  #f5edce;
  --red-soft:     #f2d6ce;
  --blue-soft:    #e4ebf5;
  --neutral-soft: #eeeeeb;
  --system:       #8b6b09;
  --tool:         #276489;
  --danger:       #b03a3a;

  --shadow: 0 1px 2px rgba(23, 23, 23, 0.06);

  --radius:    8px;
  --radius-lg: 8px;
  --radius-xl: 10px;

  --display: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --sans:    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --mono:    "JetBrains Mono", "ui-monospace", "SF Mono", "Cascadia Code", monospace;
}
```

Rules:

- Use `var(--sans)`, `var(--display)`, and `var(--mono)` rather than
  hard-coding font stacks.
- Use `var(--accent)` for the primary command surface. In the current design
  this is near-black, not a bright brand color.
- Use semantic soft colors only for status badges and warnings. Do not let one
  hue dominate the page.
- Do not add new global tokens unless a repeated pattern needs them.

## 3. Shell Layout

Default shell:

```text
topbar
workspace
  sessions-pane | messages/plugin-workbench | optional detail-pane
```

The framework shell remains generic, but application-level plugins can enter
`plugin-workbench-mode`.

In `plugin-workbench-mode`:

- hide generic session filters and unrelated nav groups;
- reduce the left pane to compact plugin navigation;
- hide duplicate pane headers when the plugin provides its own workbench title;
- let the plugin main area own the task layout.

Current Biomedical Evidence layout:

```text
topbar
left compact nav: Review / Run / Projects / Watch / Advanced / Boundary
main: Review-first run QA workspace
```

The main review surface is one primary column. Inspector/details are contextual
and hidden until a claim, evidence card, trace, provenance, or export action is
selected.

## 4. Navigation

Framework navigation should be short and quiet:

- use plain text labels;
- avoid large badges except counts that materially affect the workflow;
- use active state through white surface plus hairline border;
- avoid nested cards in nav.

Application-level plugin navigation should expose no more than 5-7 primary
items. Biomedical Evidence currently uses:

- `Review`
- `Run`
- `Projects`
- `Watch`
- `Advanced`
- `Boundary`

Raw graph, audit, trace, evidence browser, provenance, and JSON export belong
behind `Advanced` or contextual Review actions, not as always-visible top-level
buttons.

## 5. Components

Buttons:

- primary command: black background, white text, 8px radius;
- secondary command: white surface, hairline border, black text;
- destructive command: use `--danger` only when the action is truly destructive.

Inputs:

- white background;
- `1px solid var(--line)`;
- 8px radius;
- stable height and width constraints;
- no text clipping for IDs or long biomedical terms.

Cards:

- use cards only for repeated items, tools, modals, claim cards, and genuinely
  framed review artifacts;
- do not put page sections inside floating cards;
- avoid cards inside cards when a separator or heading is enough.

Badges:

- compact pills for status such as `valid`, `persisted`, `mixed`,
  `refuse_or_abstain`;
- use neutral pills by default;
- reserve color for risk or state changes that require attention.

JSON/trace blocks:

- use monospace;
- max-height with scroll;
- place behind Advanced or contextual inspector actions;
- never dominate the default Review view.

## 6. Biomedical Evidence Workspace

The Biomedical Evidence plugin is a productized application-level plugin. Its
UI should prioritize review decisions and evidence trust.

Default entry:

```text
Review
  recent runs
  load/snapshot controls
  final answer summary
  graph snapshot status
  validation status
  claim cards
  evidence card / trace / provenance / export actions
```

Run view:

- template-first workflow runner;
- hide raw LLM flags behind advanced controls;
- keep `Run Workflow` as the primary action.

Advanced view:

- evidence browser;
- raw Evidence Graph v1 explorer;
- related/directed path lookup;
- citation/logic audit;
- full trace;
- redacted JSON export.

Boundary view:

- research-only policy;
- clinical refusal behavior;
- memory-as-context boundary;
- source limitations.

## 7. Responsive Rules

Desktop:

- compact left nav, single primary main column for Review;
- contextual inspector hidden until needed;
- no page-level horizontal overflow.

Tablet/mobile:

- topbar remains compact;
- plugin navigation becomes one horizontal scroll row;
- Review controls stack into a single column;
- recent run cards match the available container width;
- raw graph/trace/JSON remain behind Advanced or inspector actions;
- no critical text overlap.

Screenshot validation should cover:

- desktop around 1280px wide;
- mobile around 390px wide;
- Review view loaded with a recent run;
- no page-level horizontal overflow;
- no console errors.

## 8. Implementation Rules

- Edit dashboard React in `frontend/dashboard/src/`.
- Edit compiled dashboard assets only through `npm run build`.
- Edit Biomedical Evidence application UI in
  `plugins/biomed_evidence/dashboard_panel.ts` and
  `plugins/biomed_evidence/dashboard_panel.css`.
- Build generated dashboard assets with `npm run build`; do not commit
  `static/dashboard/app.js`.
- Run `npm run typecheck` and `npm run build` before committing UI changes.
- For substantial UI changes, rebuild the Docker dashboard and take Browser
  screenshots at desktop and mobile widths.

## 9. Non-Goals

- No marketing hero pages inside the dashboard.
- No decorative gradient backgrounds or ornamental blobs.
- No graph database UI as the default Biomedical Evidence entry point.
- No clinical decision support UI.
- No hidden raw JSON as the only way to inspect a reviewer-critical state.
