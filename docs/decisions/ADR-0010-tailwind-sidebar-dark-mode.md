# ADR-0010: Tailwind CSS, Sidebar Layout, and Dark Mode

## Status

Accepted

## Context

The Observatory frontend originally used CSS Modules and inline styles with a horizontal top-nav bar. The rhai-org-pulse project — a sibling internal tool — uses a collapsible sidebar layout, Tailwind CSS utility classes, dark mode via class toggling, and lucide icons. The user wanted Observatory to visually match org-pulse as closely as possible so both tools feel like parts of the same platform.

The existing CSS Modules approach had ~3,600 lines of scoped CSS across 10 files, with no dark mode support and no design system consistency.

## Decision

1. **Replace CSS Modules with Tailwind CSS 3** — utility-first classes applied directly in JSX. PostCSS + autoprefixer for the build pipeline. The org-pulse primary color palette (blue 50–900) is replicated exactly in `tailwind.config.mjs`.

2. **Replace horizontal top-nav with a collapsible sidebar** — fixed left sidebar (260px expanded / 72px collapsed) with frosted glass effect (`backdrop-blur-xl`), matching org-pulse's `AppSidebar.vue` design. A sticky top bar shows the current page title and theme toggle.

3. **Add class-based dark mode** — `useTheme` hook cycles through light / dark / system modes, persisted to localStorage. The `dark` class is toggled on `<html>`. Every Tailwind color utility has a `dark:` variant.

4. **Use lucide-react for icons** — the React equivalent of org-pulse's `lucide-vue-next`, ensuring visual parity for nav items and UI elements.

## Alternatives Considered

- **Keep CSS Modules, just add sidebar**: Would preserve existing styles but miss the dark mode and design consistency goals. Two styling systems in one project adds cognitive overhead.
- **CSS-in-JS (styled-components, emotion)**: More powerful than Tailwind for dynamic styles, but org-pulse uses Tailwind — matching it requires Tailwind.
- **Shadcn/UI or Radix**: Component libraries that pair well with Tailwind, but add dependencies and abstractions the project doesn't need. The org-pulse approach is utility classes directly in templates.

## Consequences

Positive:
- Visual parity with org-pulse — both tools look like one platform
- Dark mode across all 11 pages
- Collapsible sidebar with grouped navigation sections
- No CSS files to maintain — styling is co-located with markup
- Smaller CSS bundle (28KB vs scattered module files)

Negative:
- Long `className` strings in JSX reduce readability compared to semantic CSS class names
- Tailwind is a build-time dependency — the JIT compiler must process all source files
- Developers need Tailwind familiarity (mitigated by the utility pattern being consistent and searchable)
