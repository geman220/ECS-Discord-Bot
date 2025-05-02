# ECS Soccer League CSS Architecture

This document outlines the CSS architecture used in the ECS Soccer League application, providing guidelines on maintaining and extending the styles.

## Architecture Overview

The CSS architecture is organized into three main layers:

1. **Core Layer (`ecs-core.css`)**: Fundamental styling, variables, and base elements
   - CSS variables (colors, spacing, etc.)
   - Base typography
   - Z-index hierarchy
   - Theme support (light/dark mode)
   - Accessibility basics

2. **Component Layer (`ecs-components.css`)**: Reusable UI components
   - Form controls (inputs, toggles, etc.)
   - Buttons
   - Cards
   - Modals
   - Dropdown menus
   - Navigation elements

3. **Utilities Layer (`ecs-utilities.css`)**: Helper classes for common patterns
   - Spacing utilities
   - Display helpers
   - Flexbox utilities
   - Text alignment
   - Colors and backgrounds

## Single Source of Truth

This architecture represents the single source of truth for all styling in the application. The following files have been consolidated into this architecture:

- `design-system.css` → `ecs-core.css` and `ecs-components.css`
- `responsive-system.css` → Responsive features in each layer
- `switch-fix.css` → Form controls in `ecs-components.css`
- `button-fix.css` → Button styles in `ecs-components.css`
- `modal-z-fix.css` → Z-index system in `ecs-core.css` and modal styles in `ecs-components.css`
- `dropdown-menu-fix.css` → Dropdown styles in `ecs-components.css`

## Usage Guidelines

### Variables and Theming

All design tokens (colors, spacing, etc.) are defined as CSS variables in `ecs-core.css`. Always reference these variables instead of hardcoding values:

```css
/* Good */
color: var(--ecs-primary);
margin: var(--ecs-space-md);

/* Bad */
color: #696cff;
margin: 1rem;
```

### Component Development

When developing new components:

1. Use the `ecs-` prefix for all component classes
2. Place component styles in `ecs-components.css` in the appropriate section
3. Avoid using `!important` by leveraging proper selector specificity
4. Consider light and dark mode support

### Specificity and Selectors

Follow these guidelines for selector specificity:

1. Use classes instead of element selectors when possible
2. Keep selectors as short as possible (max 3 levels)
3. Avoid overly broad selectors

### Form Controls and Toggles

Form controls, including toggle switches, should:

1. Work consistently across all browsers
2. Support both light and dark mode
3. Use the standard Bootstrap form component classes for compatibility
4. Have proper states (default, hover, focus, disabled)

## Toggle Switch Implementation

Toggle switches are implemented in `ecs-components.css` with both ECS-specific classes and Bootstrap compatibility classes. They provide:

1. Proper pill-shaped appearance
2. Clear on/off state colors
3. Smooth transition animation
4. Correct positioning and alignment

## Maintaining the Architecture

When updating the CSS:

1. Place styles in the appropriate layer
2. Update this documentation when making significant changes
3. Test changes across browsers and in both light and dark modes
4. Avoid creating one-off CSS files for fixes
5. Run the application with cache-busting enabled during development

## Deprecated Files

The following files are being phased out and should not be used for new development:

- `design-system.css` (replaced by ecs-core.css and ecs-components.css)
- `responsive-system.css` (responsive features now included in each layer)
- `switch-fix.css` (toggle switch styling now in ecs-components.css)
- Various `-fix.css` files (fixes integrated into the main architecture)

For questions or assistance with the CSS architecture, contact the development team.