import React, { useState, useEffect, Suspense } from 'react';
import { Menu, X, Search, ArrowLeft, UserCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { useHRLevel } from '@/hooks/useHRLevel';
import { hasEmployeeTaskAccess, isEditor, isHrManager } from '@/lib/auth/roles';
const logo = '/images/logo.webp';

// Lazy-load heavy components only needed by logged-in users
const NotificationsViewer = React.lazy(() =>
  import('./NotificationsViewer').then(m => ({ default: m.NotificationsViewer }))
);
const LanguageSwitcher = React.lazy(() =>
  import('./LanguageSwitcher').then(m => ({ default: m.LanguageSwitcher }))
);
const CreateTaskModal = React.lazy(() =>
  import('./tasks/CreateTaskModal').then(m => ({ default: m.CreateTaskModal }))
);
const GlobalSearch = React.lazy(() =>
  import('./GlobalSearch').then(m => ({ default: m.GlobalSearch }))
);
// Unread badge + desktop notifications. Lazy like its neighbours: it opens a
// socket connection, which only logged-in users need.
const MessengerBadge = React.lazy(() =>
  import('@/features/messenger/MessengerBadge').then(m => ({ default: m.MessengerBadge }))
);

export const Header = () => {
  const { t } = useTranslation();
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [showDeferredControls, setShowDeferredControls] = useState(false);
  const navigate = useNavigate();
  // Именно роутерный `useLocation`, а не глобальный `window.location`: последний
  // не перерисовывает Header при SPA-переходе, и `isSubpage` залипал бы на том
  // значении, что было на момент полной загрузки страницы.
  const location = useLocation();
  const isSubpage = location.pathname !== '/';

  const { activeProfile, isLoggedIn } = useActiveProfile({
    staleTime: 5 * 60 * 1000,
  });
  const { hasHrAccess } = useHRLevel({ enabled: isLoggedIn });

  useEffect(() => {
    const handleScroll = () => {
      const offset = window.scrollY;
      if (offset > 50) {
        setIsScrolled(true);
      } else if (offset < 30) {
        setIsScrolled(false);
      }
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    if (isMobileMenuOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isMobileMenuOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isLoggedIn) return; // Search & create are for logged-in users only.

      // Create task hotkey: Cmd+K or Ctrl+K
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setIsCreateOpen(prev => !prev);
        return;
      }

      // Global search hotkey: "/" — but never while typing in a field.
      if (e.key === '/' && !(e.metaKey || e.ctrlKey || e.altKey)) {
        const el = document.activeElement as HTMLElement | null;
        const tag = el?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || el?.isContentEditable) return;
        e.preventDefault();
        setIsSearchOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isLoggedIn]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setShowDeferredControls(true);
    }, 1200);

    return () => window.clearTimeout(timeoutId);
  }, []);

  const publicLinks = [
    { label: t('header.about'), href: '/#about', isInternal: true },
    { label: t('header.projects'), href: '/projects', isInternal: false },
    { label: t('header.services'), href: '/services', isInternal: false },
    { label: t('header.news'), href: '/news', isInternal: false },
  ];

  const employeeLinks = [
    { label: t('header.news'), href: '/news', reqRole: null },
    { label: t('hr.nav.calendar', 'Календарь'), href: '/calendar', reqRole: null },
    // Раздел договоров/бюджетов. Пока без ролевого условия: тонкой роли
    // «финансист» в платформе нет, а сами страницы всё равно закрыты
    // requiresAuth, и запись на бэкенде требует админа (api_view(admin=True)).
    { label: t('contracts.nav.title', 'Договоры'), href: '/contracts', reqRole: null },
    // Согласования — без ролевого условия: очередь «ждёт меня» персональна,
    // и решает названный в маршруте человек, а не администратор. Настройка
    // маршрутов внутри раздела закрыта отдельно.
    { label: t('signoff.nav.title', 'Согласования'), href: '/signoff', reqRole: null },
  ];

  if (activeProfile) {
    if (isEditor(activeProfile)) {
      employeeLinks.push({ label: t('profile.sidebar.manageNews', 'Упр. Новостями'), href: '/manage/news', reqRole: 'editor' });
    }
    if (isHrManager(activeProfile) || hasHrAccess) {
      employeeLinks.push({ label: t('profile.sidebar.employees', 'Сотрудники'), href: '/hr/employees', reqRole: 'hr' });
    }
    if (hasEmployeeTaskAccess(activeProfile)) {
      employeeLinks.push({ label: t('profile.sidebar.tasks', 'Задачи'), href: '/tasks', reqRole: 'tasks' });
    }
  }

  const navLinks = isLoggedIn ? employeeLinks : publicLinks;

  return (
    <header
      className={`sticky top-0 z-50 transition-all duration-500 ${isScrolled
        ? 'py-3 bg-white/85 shadow-sm border-b border-white/40 opacity-95'
        : 'py-5 bg-white/70 shadow-sm border-b border-white/30 opacity-90'
        }`}
    >
      <div className="container-custom flex items-center justify-between">
        {/* Logo & Mobile Back button */}
        <div className="flex items-center gap-2">
          {isSubpage && (
            <button
              type="button"
              onClick={() => {
                if (window.history.length > 1) {
                  navigate(-1);
                } else {
                  navigate('/myprofile');
                }
              }}
              className="md:hidden inline-flex items-center gap-1.5 min-h-[44px] min-w-[44px] px-3.5 py-2.5 rounded-full bg-muted/70 text-xs font-semibold text-foreground hover:bg-muted active:scale-95 transition-all border shadow-2xs"
              aria-label={t('common.back', 'Назад')}
            >
              <ArrowLeft className="h-4 w-4 text-primary shrink-0" />
              <span>{t('common.back', 'Назад')}</span>
            </button>
          )}
          <a href="/" className="flex min-h-[44px] min-w-[44px] items-center gap-3 group">
            <img
              src={logo}
              alt="Hi-Tech Group Logo"
              width={120}
              height={40}
              className="h-9 sm:h-10 w-auto transition-transform duration-300 group-hover:scale-110"
            />
            <div className={`flex flex-col justify-center h-10 transition-colors duration-300 text-foreground ${isSubpage ? 'hidden sm:flex' : 'flex'}`}>
              <span className="font-display font-bold text-lg leading-tight">Hi-Tech Group</span>
              <span className="text-[10px] align-center leading-tight opacity-80 max-w-[140px]">Construction services in energy sector</span>
            </div>
          </a>
        </div>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-6">
          {navLinks.map((link) => (
            link.isInternal && !isLoggedIn && location.pathname !== '/' ? (
              <a
                key={link.label}
                href={'/' + link.href}
                className="link-underline font-medium transition-colors duration-300 text-foreground hover:text-primary whitespace-nowrap"
              >
                {link.label}
              </a>
            ) : (
              <Link
                key={link.label}
                to={link.href.replace('/#', '#')}
                className="link-underline font-medium transition-colors duration-300 text-foreground hover:text-primary whitespace-nowrap"
              >
                {link.label}
              </Link>
            )
          ))}
          {isLoggedIn && (
            <button
              type="button"
              onClick={() => setIsSearchOpen(true)}
              aria-label={t('search.open', 'Поиск')}
              title={t('search.open', 'Поиск') + ' (/)'}
              className="p-2.5 min-h-[44px] min-w-[44px] inline-flex items-center justify-center rounded-full text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <Search className="w-5 h-5" />
            </button>
          )}
          {isLoggedIn && showDeferredControls && <Suspense fallback={null}><MessengerBadge /></Suspense>}
          {isLoggedIn && showDeferredControls && <Suspense fallback={null}><NotificationsViewer /></Suspense>}
          {showDeferredControls && <Suspense fallback={null}><LanguageSwitcher /></Suspense>}
        </nav>

        {/* CTA Button */}
        <div className="hidden md:flex items-center gap-4">
          {!isLoggedIn ? (
            <Link to="/contacts">
              <span
                className={`inline-flex h-10 items-center justify-center rounded-full px-6 py-2.5 text-sm font-medium transition-all duration-300 ${isScrolled
                  ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                  : 'bg-secondary text-secondary-foreground hover:bg-secondary/90'
                  }`}
              >
                {t('header.contacts')}
              </span>
            </Link>
          ) : (
            <Link to="/myprofile">
              <span className="inline-flex h-10 items-center justify-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground">
                <UserCircle className="w-5 h-5" />
                <span>{t('header.profile')}</span>
              </span>
            </Link>
          )}
        </div>

        {/* Mobile Menu Toggle */}
        <button
          type="button"
          aria-label="Toggle mobile navigation menu"
          className="md:hidden min-h-[44px] min-w-[44px] p-2.5 flex items-center justify-center rounded-xl transition-colors text-foreground hover:bg-accent/50"
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        >
          {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </div>

      {/* Mobile Menu Backdrop & Drawer */}
      {isMobileMenuOpen && (
        <>
          <div
            className="md:hidden fixed inset-0 top-[65px] bg-black/40 backdrop-blur-xs z-40 animate-fade-in"
            onClick={() => setIsMobileMenuOpen(false)}
          />
          <div className="md:hidden absolute top-full left-0 right-0 z-50 glass shadow-elevated animate-fade-in border-b border-border/40">
            <nav className="container-custom py-6 flex flex-col gap-2 max-h-[80vh] overflow-y-auto">
              {navLinks.map((link) => (
                link.isInternal && !isLoggedIn && location.pathname !== '/' ? (
                  <a
                    key={link.label}
                    href={'/' + link.href}
                    className="text-foreground font-medium min-h-[44px] px-4 py-3 rounded-xl hover:bg-accent/60 hover:text-primary transition-colors flex items-center w-full text-base"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.label}
                    to={link.href.replace('/#', '#')}
                    className="text-foreground font-medium min-h-[44px] px-4 py-3 rounded-xl hover:bg-accent/60 hover:text-primary transition-colors flex items-center w-full text-base"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {link.label}
                  </Link>
                )
              ))}
              {isLoggedIn && (
                <button
                  type="button"
                  onClick={() => { setIsMobileMenuOpen(false); setIsSearchOpen(true); }}
                  className="flex items-center gap-3 min-h-[44px] px-4 py-3 rounded-xl text-foreground font-medium hover:bg-accent/60 hover:text-primary transition-colors text-base w-full text-left"
                >
                  <Search className="w-5 h-5 shrink-0" />
                  <span>{t('search.open', 'Поиск')}</span>
                </button>
              )}
              <div className="flex gap-4 items-center px-4 py-2 mt-1">
                {isLoggedIn && showDeferredControls && <Suspense fallback={null}><NotificationsViewer /></Suspense>}
                {showDeferredControls && <Suspense fallback={null}><LanguageSwitcher /></Suspense>}
              </div>
              {!isLoggedIn ? (
                <Link to="/contacts" onClick={() => setIsMobileMenuOpen(false)} className="mt-2">
                  <span className="btn-primary inline-flex min-h-[44px] w-full items-center justify-center rounded-xl px-4 py-3 text-base font-semibold shadow-md">
                    {t('header.contacts')}
                  </span>
                </Link>
              ) : (
                <Link to="/myprofile" onClick={() => setIsMobileMenuOpen(false)} className="mt-2">
                  <span className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl border border-input bg-background px-4 py-3 text-base font-semibold transition-colors hover:bg-accent hover:text-accent-foreground shadow-2xs">
                    <UserCircle className="w-5 h-5" />
                    {t('header.profile')}
                  </span>
                </Link>
              )}
            </nav>
          </div>
        </>
      )}

      {isLoggedIn && (
        <Suspense fallback={null}>
          <CreateTaskModal
            open={isCreateOpen}
            onOpenChange={setIsCreateOpen}
          />
        </Suspense>
      )}

      {isLoggedIn && isSearchOpen && (
        <Suspense fallback={null}>
          <GlobalSearch open={isSearchOpen} onOpenChange={setIsSearchOpen} />
        </Suspense>
      )}
    </header>
  );
};
