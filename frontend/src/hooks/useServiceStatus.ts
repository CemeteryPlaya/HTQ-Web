/**
 * hooks/useServiceStatus.ts
 *
 * Reads the service on/off registry from `GET /api/core/v1/services/`
 * (Django `core` app / ServiceGateMiddleware). That endpoint is live — the
 * note that used to sit here, saying the Django backend "isn't in the
 * request path yet" and that this always 404s, predates the cutover and was
 * itself the reason a real gap went unnoticed: the dev server had no proxy
 * rule for `/api/core/`, so the request never left Vite. Fixed in
 * `vite.config.ts`; prod always worked via nginx's generic `location /api/`.
 *
 * The hook still MUST degrade gracefully: any request failure (404, network
 * error, CORS, timeout, …) falls back to `DEFAULT_SERVICE_STATUSES` — never
 * blocks rendering, never retries, never touches the auth/refresh/logout
 * flow (that lives entirely in `api/client.ts`'s interceptor and only reacts
 * to 401/403).
 */

import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';

/**
 * Local fallback registry — действует, ПОКА ответ реестра не пришёл (или если
 * запрос упал). Все сервисы по умолчанию включены, включая `conference`.
 *
 * Раньше здесь стояло `conference: false` — наследие тех времён, когда
 * SFU/webtransport ещё не были подключены (plan rev. 2, D10). С тех пор они
 * стартуют вместе со стеком, и этот дефолт стал вредным: до первого ответа
 * реестра (а при упавшем запросе — навсегда) рабочая функция выглядела
 * отключённой. Оптимистичный дефолт безопасен: если сервис действительно
 * выключен, бэкенд ответит 503 `service_disabled`, и его перехватит
 * ServiceUnavailableListener — та же модалка, но по факту, а не по догадке.
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
  conference: true,
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
