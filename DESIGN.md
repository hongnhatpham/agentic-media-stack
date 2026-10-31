# Operator console design

## Direction

The application is a dark, quiet operations console for one private Unraid media stack. It should feel closer to a control room than a streaming storefront: the work is finding a release, seeing why it is safe, and watching it become verified library media.

## Tokens

- Canvas: `#0d1117`; raised panels: `#151c26`; borders: `#273244`.
- Text: `#f4f7fb`; muted text: `#8e9aae`.
- Signal blue: `#55a7ff` for active controls and links.
- Signal amber: `#f0b85b` for review and caution.
- Signal green: `#68d391` for verified health and library state.
- Typography: system sans for the console, tabular numerals for progress and IDs.

## Layout and interaction

The desktop layout uses a narrow rail and a wide work surface. The overview leads with health, active jobs, and review count. Search and request keeps the query, media kind, and candidate list in one flow. Imports and library use dense rows with a clear status chip and a single next action. On small screens the rail becomes a top bar and cards stack.

Focus rings remain visible, controls use sentence case, and reduced-motion users get no animated progress shimmer. Empty states always explain the next useful action. Amber is reserved for ambiguous work, never used as decoration.
