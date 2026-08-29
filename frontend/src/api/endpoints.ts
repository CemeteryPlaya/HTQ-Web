export const API_ENDPOINTS = {
  users: 'users/v1',
  cms: 'cms/v1',
  hr: 'hr/v1',
  tasks: 'tasks/v1',
  mediaFiles: 'media/v1/files',
  email: 'email/v1',
  messenger: 'messenger/v1',
  requests: 'requests/v1',
  // Бюджеты / реестр контрактов / договоры (Django app apps.contracts).
  contracts: 'contracts/v1',
  // Универсальное согласование чужих объектов (Django app apps.signoff).
  // Не путать с `requests` (apps.approvals) — тот согласует собственные
  // RequestInstance из своего конструктора форм.
  signoff: 'signoff/v1',
  admin: 'admin/v1',
  // Роли, права должностей и личные назначения (Django app apps.access).
  // Каталог ролей глобален — одна роль действует во всех компаниях, — а
  // роли должностей и личные назначения относятся к компании запроса.
  access: 'access/v1',
  // Django "core" app (Phase 0) — service on/off registry (Task 0.5/0.7).
  // Not fronted by nginx yet; see hooks/useServiceStatus.ts for the
  // graceful-degradation contract while the Django backend isn't in traffic.
  core: 'core/v1',
} as const;

export const apiPath = (
  service: keyof typeof API_ENDPOINTS,
  path = '',
): string => {
  const suffix = path.startsWith('/') ? path.slice(1) : path;
  return suffix ? `${API_ENDPOINTS[service]}/${suffix}` : API_ENDPOINTS[service];
};
