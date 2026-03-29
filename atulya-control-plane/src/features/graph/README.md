Graph feature module for the control plane.

Structure:

- `components/`
  - React UI surfaces for state and evidence graph rendering
  - shared workbench shell used by both graph modes
- `layout/`
  - deterministic graph layout helpers
  - worker entrypoints for off-main-thread layout execution

Guideline:

- keep reusable app-wide UI in `src/components/`
- keep graph-specific rendering, layout, and worker code inside this feature module
- add new graph infrastructure here instead of placing non-UI `.ts` files back into `src/components/`
