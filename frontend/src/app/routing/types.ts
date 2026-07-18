import type { ComponentType, LazyExoticComponent } from 'react';

export type LazyPage = LazyExoticComponent<ComponentType>;

/** Coarse role buckets enforced at the route layer.
 *
 * - ``admin``  — full superuser/admin access (mapped to ELEVATED_ROLES with
 *   admin/superuser, plus ``staff`` since staff is treated as admin-equivalent
 *   on this codebase today).
 * - ``hr``     — HR or higher (admin / staff / hr_manager / senior_hr /
 *   junior_hr / senior_manager / junior_manager).
 * - ``editor`` — content-editing access for the marketing CMS pages
 *   (``editors`` / ``staff``).
 */
export type RouteRole = 'admin' | 'hr' | 'editor';

export interface RouteConfig {
  path: string;
  component: LazyPage;
  requiresAuth?: boolean;
  /** Optional role gate. ``requiresAuth`` MUST also be true for this to
   * take effect — RouteElement only mounts the guard for protected paths. */
  requiresRole?: RouteRole;
}
