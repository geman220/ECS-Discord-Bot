# CSS Architecture Documentation

## Overview

The ECS Discord Bot WebUI uses a modern CSS architecture based on:
- **CSS Cascade Layers** (`@layer`) for explicit specificity control
- **BEM naming convention** for component classes
- **Design tokens** for consistent theming
- **Vite build system** for bundling and optimization

## File Structure

```
app/static/css/
├── main-entry.css          # Main entry point with layer declarations
├── bootstrap-minimal.css   # Bootstrap utilities (grid, flex, spacing)
├── components.css          # Legacy consolidated components
├── tokens/                 # Design system tokens
│   ├── colors.css          # Color palette (MUST load first)
│   ├── typography.css      # Font sizes, weights, families
│   ├── spacing.css         # Margin/padding scale
│   ├── shadows.css         # Elevation system
│   ├── borders.css         # Border radius, width
│   └── animations.css      # Timing functions, durations
├── core/                   # Foundation styles
│   ├── variables.css       # ECS variable mappings
│   ├── z-index.css         # Z-index scale
│   ├── component-aliases.css # Bootstrap→BEM class aliases
│   ├── bootstrap-theming.css # Bootstrap class overrides
│   └── admin-utilities.css # Admin-specific utilities
├── components/             # BEM component styles
│   ├── c-btn.css           # Buttons (.c-btn)
│   ├── c-card.css          # Cards (.c-card)
│   ├── c-modal.css         # Modals (.c-modal)
│   ├── c-table.css         # Tables (.c-table)
│   ├── c-tabs.css          # Tabs (.c-tabs)
│   └── ...                 # Other BEM components
├── layout/                 # Page structure
│   ├── base-layout.css     # Base template layout
│   ├── sidebar-modern.css  # Sidebar navigation
│   ├── navbar.css          # Top navigation
│   └── auth-layout.css     # Authentication pages
├── mobile/                 # Mobile-responsive styles
│   ├── index.css           # Mobile orchestrator
│   ├── _variables.css      # Mobile breakpoints
│   ├── buttons.css         # Mobile button sizing
│   ├── forms.css           # Mobile form inputs
│   ├── tables.css          # Mobile table adaptations
│   └── navigation.css      # Mobile navigation
├── features/               # Feature-specific styles
│   ├── draft.css           # Draft system
│   ├── pitch-view.css      # Match pitch view
│   ├── schedule-manager.css # Schedule management
│   └── ...                 # Other features
├── pages/                  # Page-specific styles
│   ├── admin/              # Admin pages
│   ├── admin-panel/        # Admin panel pages
│   └── match-operations/   # Match operation pages
├── themes/                 # Theme variants
│   └── modern/
│       ├── modern-light.css # Light mode colors
│       ├── modern-dark.css  # Dark mode colors
│       └── modern-components.css # Theme component overrides
└── utilities/              # Utility classes
    ├── display-utils.css   # Display, visibility
    ├── layout-utils.css    # Position, overflow
    ├── mobile-utils.css    # Mobile-specific utilities
    └── ...                 # Other utilities
```

## CSS Cascade Layers

The layer hierarchy (lowest to highest priority):

```css
@layer tokens, bootstrap, core, components, layout, features, pages, themes, utilities;
```

1. **tokens** - CSS custom properties (design system)
2. **bootstrap** - Third-party Bootstrap CSS
3. **core** - Foundation styles, variable mappings
4. **components** - BEM component styles
5. **layout** - Page structure
6. **features** - Feature-specific styles
7. **pages** - Page-specific styles
8. **themes** - Light/dark mode overrides
9. **utilities** - Highest priority utility classes

## BEM Naming Convention

Components use the Block-Element-Modifier pattern:

```css
/* Block */
.c-card { }

/* Element */
.c-card__header { }
.c-card__body { }
.c-card__footer { }

/* Modifier */
.c-card--elevated { }
.c-card--compact { }
```

Prefix: `c-` for component classes to avoid conflicts with Bootstrap.

## Design Tokens

All colors, spacing, and typography use CSS custom properties:

```css
/* Colors */
--ecs-primary: var(--color-primary-500);
--ecs-bg-body: var(--color-bg-primary);

/* Spacing */
--space-1: 0.25rem;
--space-4: 1rem;

/* Typography */
--text-sm: 0.875rem;
--font-medium: 500;
```

## Dark Mode Support

Dark mode is implemented via:

1. **Data attribute**: `[data-style="dark"]`
2. **System preference**: `@media (prefers-color-scheme: dark)`

```css
/* Manual toggle */
[data-style="dark"] .c-card {
    background: var(--ecs-dark-bg-card);
}

/* System preference (auto) */
@media (prefers-color-scheme: dark) {
    :root:not([data-style]) .c-card { ... }
}
```

## Build System

- **Development**: `npm run dev` - Vite dev server with HMR
- **Production**: `npm run build` - Optimized bundle in `vite-dist/`

Vite provides:
- CSS minification
- Autoprefixer (vendor prefixes)
- Source maps (dev mode)
- Hash-based cache busting

## Adding New Styles

1. **Component**: Add to `components/c-{name}.css`, import in `main-entry.css`
2. **Feature**: Add to `features/{name}.css`
3. **Page**: Add to `pages/{name}.css`
4. **Utility**: Add to appropriate `utilities/*.css`

Always use design tokens for colors/spacing. Always add dark mode support.
