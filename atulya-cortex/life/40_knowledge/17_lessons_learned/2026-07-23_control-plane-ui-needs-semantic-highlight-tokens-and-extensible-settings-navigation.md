# Control Plane UI Needs Semantic Highlight Tokens And Extensible Settings Navigation

Date: 2026-07-23
Repo: atulya
Area: control plane UI, design system, settings UX, responsive layout

## Trigger

Small UI changes exposed a repeated design need:

- important controls needed a consistent brand highlight
- header controls had to share stable height, padding, and radius
- rounded containers needed to clip full-bleed child grids
- Profile & Settings needed room to grow without becoming one long scroll

## Decision

Use semantic design tokens and reusable layout patterns instead of one-off colors or page-specific geometry.

The control plane now has:

- `--highlight: #FFFF00` and `--highlight-foreground: #000000` in `src/app/globals.css`
- Tailwind utilities such as `border-highlight`, `text-highlight`, `bg-highlight`, and `ring-highlight`
- pure yellow only for deliberate emphasis: active navigation, important controls, borders, and focus states
- neutral surfaces and dividers for normal content and secondary information
- fixed control dimensions when adjacent controls must align, such as shared `h-8`, padding, radius, and text scale
- `overflow-hidden` on rounded frames containing full-bleed grids or backgrounds

Profile & Settings uses a reusable section registry in `src/components/user-settings-dialog.tsx`:

1. Profile
2. Access
3. Appearance
4. Sessions
5. System

The registry drives the desktop left navigation, mobile horizontal navigation, active section state, and smooth scrolling. Future sections should be added to the registry and rendered with a matching `settings-<id>` anchor.

## Applied Rule

When building or changing control-plane UI:

1. search for an existing semantic token before adding a color
2. use `highlight` for intentional attention, not as the default surface color
3. reuse stable control dimensions for neighboring header actions
4. use a token-based utility instead of a hard-coded hex value
5. keep settings sections addressable by stable IDs and driven by one navigation registry
6. make desktop navigation vertical and mobile navigation horizontally scrollable when space is limited
7. keep outer frames distinct while keeping inner cards and data rows neutral

## Failure Modes To Avoid

- adding `#FFFF00` directly to individual components
- using the highlight color on every border until hierarchy disappears
- mixing `h-8`, `h-9`, and arbitrary text sizes in one header row
- relying on a rounded parent without clipping children that paint to its edges
- adding settings pages with duplicated navigation arrays
- making a settings dialog wider without adding a mobile gutter
- treating a hidden navigation item as the authorization boundary

## Validation Rule

For UI changes that use these patterns:

- run `cd atulya-control-plane && npm run typecheck`
- run the focused ESLint check for changed components
- run the control-plane production build when adding new Tailwind utilities
- inspect desktop and mobile states for clipping, overflow, active navigation, and focus visibility

## Expected Benefits

- future agents can reuse a named token instead of inventing colors
- active and important controls remain visually discoverable
- settings can grow without redesigning the dialog shell
- responsive navigation stays usable on narrow screens
- visual fixes remain small, local, and consistent with the existing system

## Cortex Links

- Root brain contract: [BRAIN.md](../../../../../BRAIN.md)
- Related UI work: [organization-admin-page.tsx](../../../../../atulya-control-plane/src/components/organization-admin-page.tsx)
- Related UI work: [user-settings-dialog.tsx](../../../../../atulya-control-plane/src/components/user-settings-dialog.tsx)
- Related design tokens: [globals.css](../../../../../atulya-control-plane/src/app/globals.css)
