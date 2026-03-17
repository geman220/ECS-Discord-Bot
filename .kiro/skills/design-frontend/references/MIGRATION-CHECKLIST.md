## CSS Framework Migration Checklist

When migrating from one CSS framework to another (e.g., Bootstrap → Tailwind):

1. **Tailwind CSS reset kills component styles**: Tailwind 4's `@layer base` includes aggressive resets (`background-color: transparent`, `color: inherit`). Component-scoped CSS using `var(--color-*)` may be overridden. Always verify `background-color` and `color` survive the reset on new components. If not, use `!important`, inline styles, or move critical styles to global CSS.

2. **Audit for orphaned classes after bulk sed**: Automated find-replace misses context-dependent classes. Common Bootstrap stragglers:
   - `offset-md-*` (no Tailwind equivalent — use `mx-auto` or manual margin)
   - `card card-body bg-light` (compound classes that need full replacement)
   - `font-weight-bold` (Tailwind uses `font-bold`)
   - Stale `<script>` tags from Razor copy-paste artifacts in Angular templates

3. **Contrast check on EVERY background**: When proposing colors, run the luminance/contrast calculation against ALL backgrounds the color will appear on — not just the primary one. Yellow (#D69E2E) passes on navy (6.0:1) but fails on cream (2.2:1). Use the python3 contrast script.

4. **Visually verify after deploy**: Build + tests passing does NOT mean CSS is correct. Check at least 3 representative pages in the browser after every CSS migration commit.

5. **ng-bootstrap has hidden usage**: Before removing, grep ALL templates for `ngb` — not just the obvious datepicker. Tooltips (`ngbTooltip`), modals, dropdowns may be scattered across components.
