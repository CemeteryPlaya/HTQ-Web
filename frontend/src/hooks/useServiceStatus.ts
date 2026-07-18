/**
 * hooks/useServiceStatus.ts
 *
 * Reads the service on/off registry from `GET /api/core/v1/services/`
 * (Task 0.5 — Django `core` app / ServiceGateMiddleware). The Django
 * backend isn't in the request path yet (Phase 0 is backend-only so far),
 * so this endpoint 404s/fails today. The hook MUST degrade gracefully:
 * any request failure (404, network error, CORS, timeout, …) falls back to
 * `DEFAULT_SERVICE_STATUSES` — never blocks rendering, never retries, never
 * touches the auth/refresh/logout flow (that lives entirely in
 * `api/client.ts`'s interceptor and only reacts to 401/403).
 */

import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

/**
 * Local fallback registry. Every service defaults to enabled EXCEPT
 * `conference` — the SFU/webtransport stack is deliberately not wired up
 * yet (plan rev. 2, D10), so conference is treated as disabled unless the
 * backend explicitly says otherwise.
 */
export const DEFAULT_SERVICE_STATUSES: Record<string, boolean> = {
  users: true,
  hr: true,
  tasks: true,
  approvals: true,
  cms: true,
  media: true,
  mail: true,
  messenger: true,
  conference: false,
};

interface ServiceStatusResponse {
  services: Record<string, boolean>;
}

export function useServiceStatus() {
  const { data } = useQuery<ServiceStatusResponse>({
    queryKey: ['service-status'],
    queryFn: async () => {
      const res = await api.get<ServiceStatusResponse>(apiPath('core', 'services/'));
      return res.data;
    },
    staleTime: 30 * 1000,
    retry: false,
  });

  // On success, the backend's flags win but any service it doesn't mention
  // still falls back to the local default. On error (or before the first
  // response), `data` is undefined and this collapses to the defaults.
  const statuses: Record<string, boolean> = {
    ...DEFAULT_SERVICE_STATUSES,
    ...(data?.services ?? {}),
  };

  const isDisabled = (name: string): boolean => statuses[name] === false;

  return { statuses, isDisabled };
}
