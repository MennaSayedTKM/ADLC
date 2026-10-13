# TKMiND frontend

React 19 + TypeScript + Vite. No router, UI kit or state library — hash routing and React
context are enough for this surface. The Vite dev server proxies `/api/*` to the backend.

```bash
npm run dev      # http://localhost:5173
npm run build    # tsc -b && vite build
npm run lint     # oxlint
```

## Layout

```
src/
  api/            client.ts (typed fetch wrapper) · types.ts (mirrors backend schemas, by hand)
  lib/            Pure logic, no React: router, theme, lifecycle (stepper + "next step"),
                  sources (type guess + readiness), stories (status + version diff),
                  design (alignment summary), format helpers
  state/          AppContext (project list) · ProjectContext (one project's data + long-running
                  actions) · hooks for questions, standards, prompts, publish history
  components/
    ui/           Design-system pieces: Button, Badge, Banner, Panel, Modal (native <dialog>),
                  Tabs, Toggle, Progress/Ring, Icon, LockedState, DropTarget …
    shell/        AppShell, Sidebar, Topbar (+ page-action slot), Stepper, ⌘K CommandPalette
    sources/ requirements/ validate/ publish/ home/   Components owned by one page
  pages/          One file per screen
```

## How the pieces fit

- **Routes** are `#/`, `#/standards`, `#/settings` and `#/p/<projectId>/<page>?<query>`
  (`lib/router.ts`). Deep links such as `…/requirements?story=US-05` or `?tab=gaps` work and are
  what ⌘K results and the traceability table link to.
- **`ProjectProvider`** wraps every project route, keyed by project id. It loads sources,
  requirements and design once; pages mutate through it (`setRequirements`, `setDesign`) so the
  sidebar badges, stepper and guide stay in step. Until all three have answered, `ready` is false
  and the stepper/guide show a neutral state instead of a wrong guess.
- **Lifecycle is derived**, not stored (`lib/lifecycle.ts`): the six steps, the single next
  action and the project-card label all come from the same function.
- **Long runs** (`generateRequirements`, `runValidation`) start in the provider, so leaving the
  page doesn't abort them and the result is picked up when you return.
- **Page actions** (Approve, Export …) are portalled into the top bar with `<TopbarActions>`.
- **Backend gaps are shown honestly**: where the API can't do something (change a source's type
  after upload, preview use-case diagrams, list PDF exports) the UI offers the nearest real
  behaviour or a disabled "Soon" placeholder, never a control that pretends to work.

## Design system

- Tokens live in `src/index.css` (colour, type scale, spacing, radius, shadow). Light is the base;
  dark follows the OS or the manual toggle (`data-theme` on `<html>`, `lib/theme.ts`).
- Use tokens, not hex values. Text is ≥ 12px.
- **Accessibility rules**: ≥ 4.5:1 text contrast in both themes (don't put `opacity` on text),
  status is icon **and** label, one visible focus ring (`:focus-visible`), every control has an
  accessible name, dialogs use `<dialog>` so focus is trapped, motion respects
  `prefers-reduced-motion`. Check both themes and 375px width before shipping a screen.

## Trying it without real documents

`backend/tests/seed_demo_data.py` and `seed_design_demo.py` populate a database with sample
projects. Point `TKMIND_DB_PATH` / `TKMIND_DATA_DIR` at a scratch folder first so your real `data/`
is untouched (see the root README).
