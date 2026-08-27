# Application documentation

This directory contains documentation owned by individual application domains.

Each application gets its own folder so product, API, and engineering material can evolve together without adding more unrelated files to the root `docs/` directory.

## Applications

- [Contracts](./contracts/README.md) — budgets, counterparties, agreements, payments, and related expense workflows.
- [Signoff](./signoff/README.md) — configurable approval routes, approval tasks, and the shared approval engine.

## Convention for new applications

Create `docs/apps/<app-name>/` and begin with a `README.md` that links to the documents that apply. Keep documentation close to this shape where relevant:

- `overview.md` — domain scope, terminology, lifecycle, and integrations
- `user-guide.md` — task-oriented guidance for application users
- `api-reference.md` — HTTP resources and integration conventions
- `development.md` — source map, local verification, and change checklist

Add focused pages as the domain grows; avoid placing app-specific notes directly in `docs/`.
