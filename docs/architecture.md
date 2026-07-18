# Architecture Guide

## Goal
Make the codebase understandable for a new teammate within 30-60 minutes.

## Backend (Django)

### Current structure
- `backend/tasks/services/`: business rules and query composition.
- `backend/tasks/viewsets/`: HTTP layer (DRF ViewSets).
- `backend/tasks/views.py`: compatibility export for legacy imports.

### Layering rules
- ViewSet layer should only orchestrate request/response flow.
- Access control, filtering, statistics, and graph validation live in `services/`.
- Serializers keep validation and representation logic.
- URL routing imports from `viewsets`, not from a monolithic module.

### Why this helps
- New developer can change one concern without reading a 500+ line file.
- Domain behavior becomes reusable in tests and scheduled jobs.
- Smaller modules reduce merge conflicts between team members.

## Frontend (React + Vite)

### Current structure
- `frontend/src/app/routing/`: route config, lazy page map, prefetch strategy.
- `frontend/src/app/components/`: app-level infrastructure (`AppErrorBoundary`, `PageLoader`).
- `frontend/src/hooks/useActiveProfile.ts`: single source of profile loading/caching.
- `frontend/src/lib/auth/`: auth storage and role helpers.

### Layering rules
- `App.tsx` should compose infrastructure only, not contain all route details.
- Route list is declarative (`publicRoutes`, `protectedRoutes`).
- Profile query logic is centralized in one hook and reused by UI components.
- Role checks should use helper functions, not repeated string lists.

### Why this helps
- Navigation changes happen in one place.
- Auth/profile behavior is consistent across Header, BottomNav, guards, and task routing.
- New teammate can quickly find where to add a route or change access rules.

## Team conventions
- Keep files focused: one main responsibility per module.
- Prefer pure helper functions in services/hooks for easier tests.
- Preserve backward compatibility when moving modules (`views.py` compatibility exports).
- Add short docstrings/comments where intent is non-obvious.
