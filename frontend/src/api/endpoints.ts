export const API_ENDPOINTS = {
  users: 'users/v1',
  cms: 'cms/v1',
  hr: 'hr/v1',
  tasks: 'tasks/v1',
  mediaFiles: 'media/v1/files',
  email: 'email/v1',
  messenger: 'messenger/v1',
  requests: 'requests/v1',
  admin: 'admin/v1',
} as const;

export const apiPath = (
  service: keyof typeof API_ENDPOINTS,
  path = '',
): string => {
  const suffix = path.startsWith('/') ? path.slice(1) : path;
  return suffix ? `${API_ENDPOINTS[service]}/${suffix}` : API_ENDPOINTS[service];
};
