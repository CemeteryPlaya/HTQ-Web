/**
 * Каталоги проверяемых экранов.
 *
 * Разделены по роли зрителя: посетитель сайта видит маркетинговую часть,
 * сотрудник — рабочие разделы. Список сотрудника намеренно не покрывает все
 * ~60 защищённых маршрутов из `routeDefinitions.ts`: взяты те, что реально
 * открывают с телефона, плюс по одному представителю каждого табличного
 * раздела (таблицы — главный источник горизонтального переполнения).
 */

export interface PageCase {
  /** Путь для перехода. */
  path: string;
  /** Имя в отчёте теста. */
  name: string;
  /**
   * Селекторы, чьё поддерево исключено из проверки переполнения — только для
   * намеренно широких элементов, с объяснением в комментарии рядом.
   */
  overflowAllow?: string[];
  /** То же для размеров тач-целей. */
  touchAllow?: string[];
}

/**
 * Бегущая строка логотипов партнёров: лента едет внутри `overflow-hidden` и
 * обязана быть шире экрана — это не переполнение вёрстки, а сам приём.
 */
const PARTNERS_MARQUEE = ['section:has(> .container-custom) .relative.overflow-hidden'];

export const visitorPages: PageCase[] = [
  { path: '/', name: 'Главная', overflowAllow: PARTNERS_MARQUEE },
  { path: '/projects', name: 'Проекты' },
  { path: '/services', name: 'Услуги' },
  { path: '/news', name: 'Новости' },
  { path: '/contacts', name: 'Контакты' },
  { path: '/login', name: 'Вход' },
  { path: '/register', name: 'Регистрация' },
];

export const employeePages: PageCase[] = [
  { path: '/myprofile', name: 'Мой профиль' },
  { path: '/settings', name: 'Настройки' },
  { path: '/employee/me', name: 'Моя карточка сотрудника' },
  { path: '/messenger', name: 'Мессенджер' },
  { path: '/notifications', name: 'Уведомления' },
  { path: '/calendar', name: 'Календарь' },
  { path: '/files', name: 'Файлы подразделения' },
  { path: '/email', name: 'Почта' },
  { path: '/tasks', name: 'Задачи' },
  { path: '/tasks/daily', name: 'Ежедневные отчёты' },
  { path: '/requests', name: 'Заявки' },
  { path: '/requests/my-stats', name: 'Моя статистика по заявкам' },
  { path: '/contracts', name: 'Контракты — обзор' },
  { path: '/contracts/budgets', name: 'Контракты — бюджеты' },
  { path: '/contracts/counterparties', name: 'Контракты — контрагенты' },
  { path: '/contracts/agreements', name: 'Контракты — договоры' },
  { path: '/signoff', name: 'Согласования — входящие' },
  { path: '/signoff/processes', name: 'Согласования — процессы' },
  { path: '/hr/employees', name: 'HR — сотрудники' },
  { path: '/hr/departments', name: 'HR — подразделения' },
  { path: '/hr/documents', name: 'HR — документы' },
  { path: '/hr/positions', name: 'HR — должности' },
  { path: '/hr/time-tracking', name: 'HR — учёт времени' },
  {
    path: '/hr/org-chart',
    name: 'HR — оргструктура',
    // React Flow — панорамируемый холст: узлы графа по определению лежат за
    // краем экрана, пользователь двигает полотно. Это не переполнение вёрстки.
    overflowAllow: ['.react-flow'],
  },
  { path: '/tasks/roadmap', name: 'Задачи — дорожная карта' },
  { path: '/tasks/reports', name: 'Задачи — отчёты' },
  { path: '/manage/projects', name: 'Проекты (управление)' },
  { path: '/admin/users', name: 'Админ — пользователи' },
];
