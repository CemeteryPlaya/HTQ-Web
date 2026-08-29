/**
 * Реестр модулей платформы.
 *
 * Зеркало `apps/core/models.py::KNOWN_SERVICES` — того же списка, по которому
 * бэкенд валидирует права роли (§4.2 спеки стадии 2). Своего справочника
 * модулей ни одна из сторон не заводит: два расходящихся списка — вопрос
 * времени, а не вероятности.
 *
 * Копия здесь неизбежна: матрицу прав надо отрисовать до всякого запроса, а
 * ручки «отдай список модулей» в контракте нет. Цена копии — сторож
 * `modules.test.ts`: он требует, чтобы каждый модуль, на который ссылается
 * гейт маршрута, был в этом списке. Расхождение в другую сторону (бэкенд
 * завёл модуль, фронт не знает) безопасно: незнакомый модуль просто не
 * показывается в матрице, права по нему при этом не теряются — `PUT`
 * отправляет только то, что показано, поэтому редактирование роли с
 * неизвестным модулем сняло бы ему уровень. Об этом предупреждает сама
 * страница каталога.
 */

export interface AccessModule {
  /** Имя в реестре — то же значение, что уходит в `PUT .../permissions`. */
  name: string;
  /** Ключ перевода; фолбэк используется в тестах и до загрузки словаря. */
  titleKey: string;
  fallback: string;
}

export const ACCESS_MODULES: readonly AccessModule[] = [
  { name: 'hr', titleKey: 'access.modules.hr', fallback: 'Кадры' },
  { name: 'tasks', titleKey: 'access.modules.tasks', fallback: 'Задачи и проекты' },
  { name: 'contracts', titleKey: 'access.modules.contracts', fallback: 'Договоры и бюджеты' },
  { name: 'signoff', titleKey: 'access.modules.signoff', fallback: 'Согласование' },
  { name: 'approvals', titleKey: 'access.modules.approvals', fallback: 'Заявки' },
  { name: 'cms', titleKey: 'access.modules.cms', fallback: 'Сайт и контент' },
  { name: 'media', titleKey: 'access.modules.media', fallback: 'Файлы и медиа' },
  { name: 'mail', titleKey: 'access.modules.mail', fallback: 'Почта' },
  { name: 'messenger', titleKey: 'access.modules.messenger', fallback: 'Мессенджер' },
  { name: 'conference', titleKey: 'access.modules.conference', fallback: 'Конференции' },
  { name: 'users', titleKey: 'access.modules.users', fallback: 'Учётные записи' },
  { name: 'companies', titleKey: 'access.modules.companies', fallback: 'Компании группы' },
  { name: 'access', titleKey: 'access.modules.access', fallback: 'Роли и права' },
] as const;

export const MODULE_NAMES: readonly string[] = ACCESS_MODULES.map((m) => m.name);

export const isKnownModule = (name: string): boolean => MODULE_NAMES.includes(name);
