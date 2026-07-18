import { getAccessToken } from '@/lib/auth/profileStorage';

/**
 * Grafana URL с SSO через платформенный JWT.
 *
 * Два механизма (оба валидируются общим HS256-секретом через [auth.jwt];
 * superuser → Admin, staff → Editor, остальным вход запрещён):
 *
 * 1. `?auth_token=` (url_login) аутентифицирует первый переход;
 * 2. cookie `htq_access` (path=/grafana) — edge-прокси (vite в dev, nginx
 *    в prod) копирует её в заголовок `X-JWT-Assertion` на КАЖДОМ запросе,
 *    иначе XHR-запросы Grafana-SPA остались бы без аутентификации
 *    (Grafana не выдаёт сессионную cookie при JWT-входе).
 *
 * Без токена откроется обычная страница логина Grafana.
 */
export const grafanaSsoUrl = (path = '/'): string => {
    const token = getAccessToken();
    const base = `/grafana${path.startsWith('/') ? path : `/${path}`}`;
    if (!token) return base;
    document.cookie = `htq_access=${encodeURIComponent(token)}; path=/grafana; SameSite=Lax`;
    return `${base}?auth_token=${encodeURIComponent(token)}`;
};
