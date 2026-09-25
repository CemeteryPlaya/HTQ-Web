/**
 * Компания определяется поддоменом, поэтому переключение компании — это
 * навигация, а не запрос к API.
 *
 * Главная сложность: localStorage привязан к origin, поэтому access-токен,
 * сохранённый на kz.example.kz, недоступен на uz.example.kz. Чтобы переход
 * не выглядел разлогином, refresh-токен живёт в cookie на РОДИТЕЛЬСКОМ
 * домене — cookie, в отличие от localStorage, общая для всех поддоменов.
 * На новом поддомене SPA не находит access-токен, обменивает refresh-cookie
 * на новый и продолжает работу. Access-токен в cookie не переезжает: он
 * остаётся привязан к своему поддомену (см. profileStorage.ts) — иначе
 * браузер подставил бы токен чужой компании раньше, чем сработает обмен.
 */

/**
 * Та же регулярка, что и nginx `server_name` в infra/nginx/default.conf, —
 * и вход нормализуется так же, как это делает nginx (он приводит `Host` к
 * нижнему регистру до сравнения с `server_name`, отсюда `.toLowerCase()`
 * в companyFromHost/parentDomain ниже). Оба конца обязаны сходиться в том,
 * что считается компанией: если фронт посчитает хост компанией, а шлюз —
 * нет, заголовок X-HTQ-Company не появится, и запрос молча уйдёт в схему
 * public вместо своей компании.
 *
 *   - компания начинается с буквы — этим отсечены IP-адреса ("192.168...");
 *   - "www" зарезервирован под общий домен и компанией не считается;
 *   - корень — либо буквально "localhost" (разработка на *.localhost), либо
 *     содержит свою точку (минимум два уровня после компании), поэтому
 *     голый домен второго уровня (example.kz) компанией не считается.
 */
const COMPANY_HOST_PATTERN = /^(?!www\.)([a-z][a-z0-9-]*)\.(?:localhost|[^.]+(?:\.[^.]+)+)$/;

/** Компания из имени хоста, или null если поддомена-компании нет. */
export const companyFromHost = (host: string): string | null => {
  const withoutPort = host.split(':')[0].toLowerCase();
  const match = COMPANY_HOST_PATTERN.exec(withoutPort);
  return match ? match[1] : null;
};

/**
 * Домен для refresh-cookie: общий для всех компаний.
 *
 * localhost — особый случай: браузеры отвергают cookie с Domain=.localhost,
 * поэтому там домен указывается без ведущей точки.
 */
export const parentDomain = (host: string): string => {
  const withoutPort = host.split(':')[0].toLowerCase();
  const labels = withoutPort.split('.');
  const tail = labels.length > 2 ? labels.slice(1) : labels;
  const joined = tail.join('.');
  return joined.endsWith('localhost') ? 'localhost' : `.${joined}`;
};

/**
 * Домен refresh-cookie для текущей страницы. Вычисляется один раз при
 * загрузке модуля: `switchCompany` переходит на новый поддомен полной
 * навигацией (`window.location.assign`), поэтому модуль пересобирается и
 * значение пересчитывается заново — устаревшим оно не бывает.
 */
export const REFRESH_COOKIE_DOMAIN: string =
  typeof window !== 'undefined' ? parentDomain(window.location.host) : '';

/**
 * Компания в адресе: короткий псевдоним, если он задан, иначе слаг (блок I.2).
 *
 * Слаг компании, у которой есть псевдоним, шлюз не принимает (404), поэтому
 * адрес строится только отсюда — не подставляйте `slug` в хост напрямую.
 */
export const hostLabelOf = (company: { slug: string; subdomain?: string | null }): string =>
  company.subdomain || company.slug;

/**
 * Перейти в другую компанию.
 *
 * Без `path` — сохранив текущий путь, query-параметры и hash (переключатель в
 * шапке: та же страница, другая компания). С `path` — на него: экран выбора
 * компании возвращает человека туда, куда он шёл до редиректа на выбор, а не
 * на сам экран выбора. `path` — путь вместе с query и hash, начиная с `/`.
 */
export const switchCompany = (
  company: { slug: string; subdomain?: string | null },
  path?: string,
): void => {
  const { host, pathname, search, hash, protocol } = window.location;
  const tail = parentDomain(host).replace(/^\./, '');
  const port = host.includes(':') ? `:${host.split(':')[1]}` : '';
  const target = path ?? `${pathname}${search}${hash}`;
  window.location.assign(`${protocol}//${hostLabelOf(company)}.${tail}${port}${target}`);
};
