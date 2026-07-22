import { lazyPages } from './lazyPages';
import type { RouteConfig } from './types';

export const publicRoutes: RouteConfig[] = [
  { path: '/projects', component: lazyPages.Projects },
  { path: '/services', component: lazyPages.Services },
  { path: '/news', component: lazyPages.News },
  { path: '/news/:slug', component: lazyPages.NewsDetail },
  { path: '/contacts', component: lazyPages.Contacts },
  { path: '/design-preview', component: lazyPages.DesignPreview },
  { path: '/login', component: lazyPages.Login },
  { path: '/register', component: lazyPages.Register },
  // Public org view — shareable token, no auth required
  { path: '/public/org/:token', component: lazyPages.PublicOrgView },
  // Public single-employee card — shareable token, no auth required
  { path: '/public/employee/:token', component: lazyPages.PublicEmployeeView },
];

export const protectedRoutes: RouteConfig[] = [
  // ─── CMS / marketing manage pages ─────────────────────────────────────
  // Editorial role (or higher) — protect against random users hitting
  // ``/manage/news`` directly and altering published content.
  { path: '/manage/news', component: lazyPages.AdminNews, requiresAuth: true, requiresRole: 'editor' },
  { path: '/manage/contacts', component: lazyPages.AdminContacts, requiresAuth: true, requiresRole: 'editor' },
  { path: '/manage/projects', component: lazyPages.AdminProjects, requiresAuth: true, requiresRole: 'editor' },

  // ─── Personal / messenger / tasks (any logged-in user) ────────────────
  { path: '/myprofile', component: lazyPages.MyProfile, requiresAuth: true },
  { path: '/settings', component: lazyPages.Settings, requiresAuth: true },
  { path: '/messenger', component: lazyPages.Messenger, requiresAuth: true },
  { path: '/notifications', component: lazyPages.NotificationsHistory, requiresAuth: true },
  { path: '/admin/users', component: lazyPages.AdminUsers, requiresAuth: true },
  { path: '/admin/chats', component: lazyPages.AdminChats, requiresAuth: true },
  { path: '/admin/mailboxes', component: lazyPages.AdminMailboxes, requiresAuth: true },
  { path: '/admin/levels', component: lazyPages.HRAccessLevels, requiresAuth: true },
  { path: '/admin/registrations', component: lazyPages.AdminRegistrations, requiresAuth: true },
  { path: '/hr/employees', component: lazyPages.HREmployees, requiresAuth: true },
  { path: '/hr/employees/:id', component: lazyPages.HREmployeeCard, requiresAuth: true },
  { path: '/hr/departments', component: lazyPages.HRDepartments, requiresAuth: true },
  { path: '/hr/time-tracking', component: lazyPages.HRTimeTracking, requiresAuth: true },
  { path: '/hr/recruitment', component: lazyPages.HRRecruitment, requiresAuth: true },
  { path: '/hr/documents', component: lazyPages.HRDocuments, requiresAuth: true },
  { path: '/hr/logs', component: lazyPages.HRLogs, requiresAuth: true },
  { path: '/hr/history', component: lazyPages.HRHistory, requiresAuth: true },
  { path: '/hr/archive', component: lazyPages.HRArchive, requiresAuth: true },
  { path: '/hr/accounts', component: lazyPages.HRAccounts, requiresAuth: true },
  { path: '/hr/org-chart', component: lazyPages.HROrgChart, requiresAuth: true },
  { path: '/hr/pmo', component: lazyPages.HRPMO, requiresAuth: true },
  { path: '/hr/share-links', component: lazyPages.HRShareLinks, requiresAuth: true },
  { path: '/hr/positions', component: lazyPages.HRPositions, requiresAuth: true },
  { path: '/hr/vacancies', component: lazyPages.HRVacancies, requiresAuth: true },
  { path: '/hr/applications', component: lazyPages.HRApplications, requiresAuth: true },
  { path: '/hr/offers', component: lazyPages.HROffers, requiresAuth: true },
  { path: '/hr/production-calendar', component: lazyPages.HRProductionCalendar, requiresAuth: true },
  { path: '/hr/staffing', component: lazyPages.HRStaffing, requiresAuth: true },
  { path: '/calendar', component: lazyPages.HRCalendar, requiresAuth: true },
  { path: '/files', component: lazyPages.DepartmentFiles, requiresAuth: true },
  { path: '/conference', component: lazyPages.ConferencePage, requiresAuth: true },
  { path: '/room/:roomId', component: lazyPages.ConferencePage, requiresAuth: true },
  { path: '/tasks', component: lazyPages.TaskRouter, requiresAuth: true },
  { path: '/tasks/:id', component: lazyPages.TaskDetailRouter, requiresAuth: true },
  { path: '/tasks/roadmap', component: lazyPages.HRRoadmap, requiresAuth: true },
  { path: '/tasks/reports', component: lazyPages.HRReports, requiresAuth: true },
  { path: '/tasks/resources', component: lazyPages.HRResourceSchedule, requiresAuth: true },
  { path: '/tasks/equipment', component: lazyPages.HREquipment, requiresAuth: true },
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
  { path: '/requests/projects', component: lazyPages.RequestsProjectsPage, requiresAuth: true, requiresRole: 'admin' },
  { path: '/requests/templates', component: lazyPages.RequestsTemplatesPage, requiresAuth: true, requiresRole: 'admin' },
  { path: '/requests/templates/:id/editor', component: lazyPages.RequestsTemplateEditorPage, requiresAuth: true, requiresRole: 'admin' },
  { path: '/requests/stats', component: lazyPages.RequestsStatsPage, requiresAuth: true, requiresRole: 'admin' },
  { path: '/requests/reference', component: lazyPages.RequestsReferencePage, requiresAuth: true, requiresRole: 'admin' },
  { path: '/requests/data', component: lazyPages.RequestsDataPage, requiresAuth: true },
  { path: '/requests/:id', component: lazyPages.RequestDetailPage, requiresAuth: true },

  // ─── Admin-only ───────────────────────────────────────────────────────
  { path: '/admin/users', component: lazyPages.AdminUsers, requiresAuth: true, requiresRole: 'admin' },
  { path: '/admin/chats', component: lazyPages.AdminChats, requiresAuth: true, requiresRole: 'admin' },
  { path: '/admin/mailboxes', component: lazyPages.AdminMailboxes, requiresAuth: true, requiresRole: 'admin' },
  { path: '/admin/levels', component: lazyPages.HRLevelsAdmin, requiresAuth: true, requiresRole: 'admin' },
  { path: '/admin/registrations', component: lazyPages.AdminRegistrations, requiresAuth: true, requiresRole: 'admin' },
  { path: '/admin/infrastructure', component: lazyPages.AdminInfrastructure, requiresAuth: true, requiresRole: 'admin' },

  // ─── HR (admin / staff / HR-manager roles) ────────────────────────────
  { path: '/hr/employees', component: lazyPages.HREmployees, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/employees/:id', component: lazyPages.HREmployeeCard, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/departments', component: lazyPages.HRDepartments, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/time-tracking', component: lazyPages.HRTimeTracking, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/recruitment', component: lazyPages.HRRecruitment, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/documents', component: lazyPages.HRDocuments, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/logs', component: lazyPages.HRLogs, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/history', component: lazyPages.HRHistory, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/archive', component: lazyPages.HRArchive, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/accounts', component: lazyPages.HRAccounts, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/org-chart', component: lazyPages.HROrgChart, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/pmo', component: lazyPages.HRPMO, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/share-links', component: lazyPages.HRShareLinks, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/positions', component: lazyPages.HRPositions, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/vacancies', component: lazyPages.HRVacancies, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/applications', component: lazyPages.HRApplications, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/offers', component: lazyPages.HROffers, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/production-calendar', component: lazyPages.HRProductionCalendar, requiresAuth: true, requiresRole: 'hr' },
  { path: '/hr/staffing', component: lazyPages.HRStaffing, requiresAuth: true, requiresRole: 'hr' },
];
