import { lazyPages } from './lazyPages';
import type { RouteConfig } from './types';

export const publicRoutes: RouteConfig[] = [
  { path: '/projects', component: lazyPages.Projects },
  { path: '/services', component: lazyPages.Services },
  { path: '/news', component: lazyPages.News },
  { path: '/news/:slug', component: lazyPages.NewsDetail },
  { path: '/contacts', component: lazyPages.Contacts },
  { path: '/login', component: lazyPages.Login },
  { path: '/register', component: lazyPages.Register },
  // Public org view — shareable token, no auth required
  { path: '/public/org/:token', component: lazyPages.PublicOrgView },
  // Public single-employee card — shareable token, no auth required
  { path: '/public/employee/:token', component: lazyPages.PublicEmployeeView },
  // Вход в конференцию по ссылке-приглашению: сюда приходит внешний
  // участник, у которого учётки нет вовсе (см. ConferenceJoin.tsx).
  { path: '/join/:token', component: lazyPages.ConferenceJoin },
  // Комната открыта без обязательной авторизации намеренно: в ней может
  // оказаться гость с токеном из sessionStorage. Право войти проверяет не
  // маршрут, а SFU — он принимает гостевой токен только в ту комнату, на
  // которую тот выписан. Сама страница отправит на /login того, у кого нет
  // ни рабочей сессии, ни гостевой.
  { path: '/room/:roomId', component: lazyPages.ConferencePage },
];

// NOTE: paths in this array must be UNIQUE. `<Routes>` scores identical
// path strings equally and renders whichever was declared first, so a
// duplicate silently shadows the later entry — which is exactly how every
// `/admin/*` and `/hr/*` route lost its module gate for as long as an
// ungated copy sat above the gated one. `routeDefinitions.test.ts` fails
// the build if a duplicate comes back.
export const protectedRoutes: RouteConfig[] = [
  // ─── CMS / marketing manage pages ─────────────────────────────────────
  // Editorial role (or higher) — protect against random users hitting
  // ``/manage/news`` directly and altering published content.
  // Блоки лендинга: порядок, видимость, тексты. Роль editor — тот же
  // контур, что новости и обращения; правит содержимое сайта, не систему.
  { path: '/manage/home', component: lazyPages.ManageHomeSections, requiresAuth: true, requires: { module: 'cms', level: 'write' } },
  { path: '/manage/news', component: lazyPages.AdminNews, requiresAuth: true, requires: { module: 'cms', level: 'write' } },
  { path: '/manage/contacts', component: lazyPages.AdminContacts, requiresAuth: true, requires: { module: 'cms', level: 'write' } },
  // ``/manage/projects`` keeps its historical path but is NOT a CMS page: it
  // manages tasks-domain projects (apps.tasks.Project), which are an
  // operational entity, not marketing content. Hence the ``hr`` bucket
  // (admins + staff) rather than ``editor`` — with ``editor`` an admin
  // without the editors role could not reach it at all, while a content
  // editor who can reach it would get 403 from every write.
  { path: '/manage/projects', component: lazyPages.HRProjects, requiresAuth: true, requires: { module: 'hr', level: 'read' } },

  // ─── Personal / messenger / tasks (any logged-in user) ────────────────
  { path: '/myprofile', component: lazyPages.MyProfile, requiresAuth: true },
  { path: '/employee/me', component: lazyPages.MyEmployeeCard, requiresAuth: true },
  { path: '/settings', component: lazyPages.Settings, requiresAuth: true },
  { path: '/messenger', component: lazyPages.Messenger, requiresAuth: true },
  { path: '/notifications', component: lazyPages.NotificationsHistory, requiresAuth: true },
  { path: '/calendar', component: lazyPages.HRCalendar, requiresAuth: true },
  { path: '/files', component: lazyPages.DepartmentFiles, requiresAuth: true },
  { path: '/conference', component: lazyPages.ConferencePage, requiresAuth: true },
  // История встреч: кто собирал, когда, запись и протокол. Конкретный путь
  // идёт перед параметрическим — иначе `/conference/history` попал бы в
  // `:sessionId` соседнего маршрута.
  { path: '/conference/history', component: lazyPages.ConferenceHistory, requiresAuth: true },
  {
    path: '/conference/history/:sessionId',
    component: lazyPages.ConferenceSessionDetail,
    requiresAuth: true,
  },

  // ─── Tasks ────────────────────────────────────────────────────────────
  // `/tasks` and `/tasks/:id` are for everyone — TaskRouter serves regular
  // employees a scoped board of their own work. The four management
  // surfaces below are not: the roadmap, reports and resource schedule show
  // the whole company's load, and the equipment page edits a shared
  // register (its writes are admin-only on the backend, so leaving it open
  // here would only mean a page full of 403s).
  { path: '/tasks', component: lazyPages.TaskRouter, requiresAuth: true },
  { path: '/tasks/roadmap', component: lazyPages.HRRoadmap, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  // Перед `/tasks/:id` (см. ниже) и перед ним же по смыслу: карточка пакета
  // работ, а не задачи.
  { path: '/tasks/roadmaps/:id', component: lazyPages.HRRoadmapDetail, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  // Дашборд план/факта проекта. Под /tasks/, а не /manage/: это
  // рабочий экран раздела задач, а не управление справочником.
  { path: '/tasks/projects/:id/plan-fact', component: lazyPages.HRProjectPlanFact, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/tasks/daily', component: lazyPages.HRDailyReports, requiresAuth: true },
  // Численность персонала по участкам. Под ролью, в отличие от соседней
  // ежедневки: та про свою смену, эта — управленческие данные по объекту
  // целиком (бэкенд пускает только владельца проекта и админа).
  { path: '/tasks/project-daily', component: lazyPages.HRProjectStaffReports, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/tasks/reports', component: lazyPages.HRReports, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/tasks/resources', component: lazyPages.HRResourceSchedule, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/tasks/equipment', component: lazyPages.HREquipment, requiresAuth: true, requires: { module: 'tasks', level: 'admin' } },
  { path: '/tasks/sites', component: lazyPages.HRSites, requiresAuth: true, requires: { module: 'tasks', level: 'admin' } },
  { path: '/tasks/contractors', component: lazyPages.HRContractors, requiresAuth: true, requires: { module: 'tasks', level: 'admin' } },
  // Declared last: `/tasks/:id` would otherwise swallow the static paths above.
  { path: '/tasks/:id', component: lazyPages.TaskDetailRouter, requiresAuth: true },

  // ─── Contracts (бюджеты / реестр контрактов / договоры) ───────────────
  // Статический `/new` объявлен ПЕРЕД `/:id` — react-router сопоставляет в
  // порядке объявления, и иначе "new" ушёл бы в параметр.
  //
  // Карточки открыты любому сотруднику, как и списки: читать домен разрешено
  // всем (`api_view(auth="jwt")`), а операции внутри карточки бэкенд
  // проверяет сам — смена статуса админская, загрузка скана разрешена автору
  // черновика. Роутером это не закрывается: право здесь зависит от строки, а
  // не от раздела.
  { path: '/contracts', component: lazyPages.ContractsOverview, requiresAuth: true },
  { path: '/contracts/tasks', component: lazyPages.ContractsMyTasks, requiresAuth: true },
  { path: '/contracts/budgets', component: lazyPages.ContractsBudgetList, requiresAuth: true },
  { path: '/contracts/budgets/new', component: lazyPages.ContractsBudgetCreate, requiresAuth: true },
  { path: '/contracts/budgets/:id', component: lazyPages.ContractsBudgetDetail, requiresAuth: true },
  { path: '/contracts/budgets/:id/edit', component: lazyPages.ContractsBudgetEdit, requiresAuth: true },
  { path: '/contracts/counterparties', component: lazyPages.ContractsCounterpartyList, requiresAuth: true },
  { path: '/contracts/counterparties/new', component: lazyPages.ContractsCounterpartyCreate, requiresAuth: true },
  { path: '/contracts/counterparties/:id', component: lazyPages.ContractsCounterpartyDetail, requiresAuth: true },
  { path: '/contracts/counterparties/:id/edit', component: lazyPages.ContractsCounterpartyEdit, requiresAuth: true },
  { path: '/contracts/agreements', component: lazyPages.ContractsAgreementList, requiresAuth: true },
  { path: '/contracts/agreements/new', component: lazyPages.ContractsAgreementCreate, requiresAuth: true },
  { path: '/contracts/agreements/:id', component: lazyPages.ContractsAgreementDetail, requiresAuth: true },
  { path: '/contracts/agreements/:id/edit', component: lazyPages.ContractsAgreementEdit, requiresAuth: true },
  { path: '/contracts/invoices', component: lazyPages.ContractsInvoiceList, requiresAuth: true },
  { path: '/contracts/invoices/new', component: lazyPages.ContractsInvoiceCreate, requiresAuth: true },
  { path: '/contracts/invoices/:id', component: lazyPages.ContractsInvoiceDetail, requiresAuth: true },
  { path: '/contracts/invoices/:id/edit', component: lazyPages.ContractsInvoiceEdit, requiresAuth: true },
  { path: '/contracts/advance-payments', component: lazyPages.ContractsAdvancePaymentList, requiresAuth: true },
  { path: '/contracts/advance-payments/new', component: lazyPages.ContractsAdvancePaymentCreate, requiresAuth: true },
  { path: '/contracts/advance-payments/:id', component: lazyPages.ContractsAdvancePaymentDetail, requiresAuth: true },
  { path: '/contracts/accountable-funds-requests', component: lazyPages.ContractsAccountableFundsRequestList, requiresAuth: true },
  { path: '/contracts/accountable-funds-requests/new', component: lazyPages.ContractsAccountableFundsRequestCreate, requiresAuth: true },
  { path: '/contracts/accountable-funds-requests/:id', component: lazyPages.ContractsAccountableFundsRequestDetail, requiresAuth: true },
  { path: '/contracts/contract-payments', component: lazyPages.ContractsContractPaymentList, requiresAuth: true },
  { path: '/contracts/contract-payments/new', component: lazyPages.ContractsContractPaymentCreate, requiresAuth: true },
  { path: '/contracts/contract-payments/:id', component: lazyPages.ContractsContractPaymentDetail, requiresAuth: true },
  { path: '/contracts/completion-acts', component: lazyPages.ContractsCompletionActList, requiresAuth: true },
  { path: '/contracts/completion-acts/new', component: lazyPages.ContractsCompletionActCreate, requiresAuth: true },
  { path: '/contracts/completion-acts/:id', component: lazyPages.ContractsCompletionActDetail, requiresAuth: true },

  // ─── Signoff (универсальное согласование, apps.signoff) ───────────────
  // Очередь и карточки открыты любому сотруднику: решает НАЗВАННЫЙ в
  // маршруте человек, а не обладатель админского флага, и право проверяет
  // бэкенд по самой задаче. Админской является только настройка маршрутов —
  // писать их разрешено лишь администратору (`api_view(admin=True)`).
  { path: '/signoff', component: lazyPages.SignoffInbox, requiresAuth: true },
  { path: '/signoff/processes', component: lazyPages.SignoffProcessList, requiresAuth: true },
  { path: '/signoff/processes/:id', component: lazyPages.SignoffProcessDetail, requiresAuth: true },
  { path: '/signoff/routes', component: lazyPages.SignoffRouteList, requiresAuth: true, requires: { module: 'signoff', level: 'admin' } },
  { path: '/signoff/routes/:id', component: lazyPages.SignoffRouteEditor, requiresAuth: true, requires: { module: 'signoff', level: 'admin' } },

  { path: '/email', component: lazyPages.EmailInbox, requiresAuth: true },
  { path: '/email/oauth/callback', component: lazyPages.OAuthCallbackPage, requiresAuth: true },

  // ─── Requests (approvals) ─────────────────────────────────────────────
  // Static prefixes (`/projects`, `/templates`, `/new`) MUST precede the
  // `/:id` route — react-router matches in declaration order.
  { path: '/requests', component: lazyPages.RequestsPage, requiresAuth: true },
  { path: '/requests/new', component: lazyPages.NewRequestPage, requiresAuth: true },
  // Personal stats — every logged-in user, scoped to their own requests.
  { path: '/requests/my-stats', component: lazyPages.RequestsMyStatsPage, requiresAuth: true },
  // Templates / projects / general stats are administration surfaces — admin only.
  { path: '/requests/projects', component: lazyPages.RequestsProjectsPage, requiresAuth: true, requires: { module: 'approvals', level: 'admin' } },
  { path: '/requests/templates', component: lazyPages.RequestsTemplatesPage, requiresAuth: true, requires: { module: 'approvals', level: 'admin' } },
  { path: '/requests/templates/:id/editor', component: lazyPages.RequestsTemplateEditorPage, requiresAuth: true, requires: { module: 'approvals', level: 'admin' } },
  { path: '/requests/stats', component: lazyPages.RequestsStatsPage, requiresAuth: true, requires: { module: 'approvals', level: 'admin' } },
  { path: '/requests/reference', component: lazyPages.RequestsReferencePage, requiresAuth: true, requires: { module: 'approvals', level: 'admin' } },
  { path: '/requests/data', component: lazyPages.RequestsDataPage, requiresAuth: true },
  { path: '/requests/:id', component: lazyPages.RequestDetailPage, requiresAuth: true },

  // ─── Admin-only ───────────────────────────────────────────────────────
  { path: '/admin/users', component: lazyPages.AdminUsers, requiresAuth: true, requires: { module: 'users', level: 'admin' } },
  { path: '/admin/chats', component: lazyPages.AdminChats, requiresAuth: true, requires: { module: 'messenger', level: 'admin' } },
  { path: '/admin/mailboxes', component: lazyPages.AdminMailboxes, requiresAuth: true, requires: { module: 'mail', level: 'admin' } },
  // Не путать с уровнями ДОЛЖНОСТЕЙ: это уровни HR-ДОСТУПА
  // (junior/middle/senior/lead). Справочник уровней должностей раньше жил на
  // соседнем /admin/levels, а теперь это вкладка на /hr/positions?tab=levels.
  { path: '/admin/access-levels', component: lazyPages.HRAccessLevels, requiresAuth: true, requires: { module: 'hr', level: 'admin' } },
  { path: '/admin/registrations', component: lazyPages.AdminRegistrations, requiresAuth: true, requires: { module: 'users', level: 'admin' } },
  { path: '/admin/infrastructure', component: lazyPages.AdminInfrastructure, requiresAuth: true, requires: { module: 'users', level: 'admin' } },

  // ─── HR (admin / staff / HR-manager roles) ────────────────────────────
  { path: '/hr/employees', component: lazyPages.HREmployees, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/employees/:id', component: lazyPages.HREmployeeCard, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/departments', component: lazyPages.HRDepartments, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/time-tracking', component: lazyPages.HRTimeTracking, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/recruitment', component: lazyPages.HRRecruitment, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/documents', component: lazyPages.HRDocuments, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/logs', component: lazyPages.HRLogs, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/history', component: lazyPages.HRHistory, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/archive', component: lazyPages.HRArchive, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/accounts', component: lazyPages.HRAccounts, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/identity-requests', component: lazyPages.HRIdentityRequests, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/org-chart', component: lazyPages.HROrgChart, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/pmo', component: lazyPages.HRPMO, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/share-links', component: lazyPages.HRShareLinks, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/positions', component: lazyPages.HRPositions, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/vacancies', component: lazyPages.HRVacancies, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/applications', component: lazyPages.HRApplications, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/offers', component: lazyPages.HROffers, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/production-calendar', component: lazyPages.HRProductionCalendar, requiresAuth: true, requires: { module: 'hr', level: 'read' } },
  { path: '/hr/staffing', component: lazyPages.HRStaffing, requiresAuth: true, requires: { module: 'hr', level: 'read' } },

  // ─── Доступ и роли ────────────────────────────────────────────────────
  // Гейт на собственный модуль: каталог общий для всех компаний, и его
  // мутации бэкенд отдаёт только суперпользователю (403 иначе). Уровень
  // admin здесь — минимум для входа на страницу, а не полный эквивалент
  // серверной проверки: страница сама скрывает правку у неплатформенного
  // администратора.
  { path: '/access/roles', component: lazyPages.AccessRoleCatalog, requiresAuth: true, requires: { module: 'access', level: 'admin' } },
];
