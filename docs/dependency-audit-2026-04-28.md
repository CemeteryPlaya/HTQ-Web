# Dependency Audit — Phase 6.3

**Date:** 2026-04-28

## Tools

| Tool      | Version | Scope                                |
|-----------|---------|--------------------------------------|
| pip-audit | 2.10.0  | All `services/*/requirements.txt`    |
| npm audit | bundled | `frontend/package-lock.json`         |

## Python (pip-audit)

### Before — 50 unique CVEs across 8 services

Common vulnerabilities (used by multiple services):

| Package           | Version | CVE             | Fix     |
|-------------------|---------|-----------------|---------|
| PyJWT             | 2.10.1  | CVE-2026-32597  | 2.12.0  |
| starlette         | 0.41.3  | CVE-2025-54121  | 0.47.2  |
| starlette         | 0.41.3  | CVE-2025-62727  | 0.49.1  |
| python-multipart  | 0.0.19  | CVE-2026-24486  | 0.0.22  |
| python-multipart  | 0.0.19  | CVE-2026-40347  | 0.0.26  |
| cryptography      | 44.0.0  | CVE-2024-12797, 26007, 34073 | 46.0.6 |
| cryptography      | 46.0.6  | CVE-2026-39892  | 46.0.7  |
| python-socketio   | 5.12.1  | CVE-2025-61765  | 5.14.0  |
| pytest            | 8.3.4   | CVE-2025-71176  | 9.0.3   |

### Coordinated bumps applied

- `fastapi`: 0.115.6 → 0.136.1 (required to allow `starlette>=0.49`)
- `starlette`: explicit pin 0.49.1 added (transitive override of fastapi's range)
- `pytest-asyncio`: 0.25.2 → 1.3.0 (required for pytest 9 compat)
- All other CVE-fixing pins applied consistently across the 8 services + `_template/`

### After — 0 CVEs across all 8 services ✅

Verified via `pip-audit -r services/<svc>/requirements.txt` for each. Per-service
JSON snapshots saved to `docs/audit-2026-04-28/pip-audit-<svc>-after.json`.

## JavaScript (npm audit)

### Before
- critical: 0
- high:     **10** (axios DoS, react-router XSS, lodash prototype pollution,
  rollup path traversal, glob/picomatch/minimatch ReDoS, flatted DoS)
- moderate: 9
- low:      3
- **total:  22**

### After `npm audit fix`
- critical: 0
- high:     **0** ✅
- moderate: 2 (esbuild ≤0.24 dev-server CORS — only affects `npm run dev`,
  fix requires `vite@8` breaking-change major)
- low:      3
- **total:  5**

### Deferred — breaking-change vite@8 upgrade
Will be picked up by Dependabot once `npm audit fix --force` is reviewed
under the next Vite-major roadmap step.

## Continuous monitoring

[.github/dependabot.yml](../.github/dependabot.yml) added:
- Weekly pip updates per service (8 entries)
- Weekly npm updates for frontend
- Monthly docker base-image updates
- Weekly GitHub Actions updates (placeholder for Phase 6.1.d)

## Rebuild required

The image rebuild for the new pins is left for the next operational cycle.
Until rebuild, the running containers still run the older versions; the
pip-audit clean state applies to `requirements.txt` (the build manifest).
