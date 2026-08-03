import React, { useState, useEffect, Suspense } from 'react';
import { Menu, X, Search, ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router-dom';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { useHRLevel } from '@/hooks/useHRLevel';
import { hasEmployeeTaskAccess, isEditor, isHrManager } from '@/lib/auth/roles';
import { splitForHeader, visibleNavItems, type NavItem } from '@/app/navigation/navItems';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
const logo = '/images/logo.webp';
import { UserCircle } from 'lucide-react';

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
  const location = useLocation();

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

  // Разделы для залогиненного берём из единого списка (app/navigation/navItems),
  // общего с мобильной нижней панелью — раньше два списка жили порознь и
  // разошлись: из шапки были недостижимы чаты, почта и файлы.
  const employeeNav = visibleNavItems({
    isEditor: isEditor(activeProfile),
    isHr: isHrManager(activeProfile) || hasHrAccess,
    hasTasks: hasEmployeeTaskAccess(activeProfile),
    hasDepartment: Boolean(activeProfile?.department),
  });

  // Вкладок стало больше, чем помещается в один ряд: держим в ряду первые
  // четыре, остальное — под «Ещё». Ряд делит место с логотипом, поиском,
  // бейджем мессенджера, уведомлениями, языком и кнопкой профиля, поэтому
  // порог низкий намеренно.
  const { primary, overflow } = splitForHeader(employeeNav, 4);

  const navLinkClass = 'link-underline font-medium transition-colors duration-300 text-foreground hover:text-primary whitespace-nowrap';

  const renderEmployeeLink = (item: NavItem) => (
    <Link key={item.id} to={item.href} className={navLinkClass}>
      {t(item.labelKey, item.labelFallback)}
    </Link>
  );

  return (
    <header
      className={`sticky top-0 z-50 transition-all duration-500 ${isScrolled
        ? 'py-3 bg-white/85 shadow-sm border-b border-white/40 opacity-95'
        : 'py-5 bg-white/70 shadow-sm border-b border-white/30 opacity-90'
        }`}
    >
      <div className="container-custom flex items-center justify-between">
        {/* Logo */}
        {/* Логотип: подпись-слоган съедает ~140px в ряду, которому их не хватает.
            На рабочих экранах (залогинен, много разделов) она не нужна —
            показываем её только на широких, а гостю оставляем как было. */}
        <a href="/" className="flex items-center gap-3 group shrink-0">
          <img
            src={logo}
            alt="Hi-Tech Group Logo"
            width={120}
            height={40}
            className="h-10 w-auto transition-transform duration-300 group-hover:scale-110"
          />
          <div className="flex flex-col justify-center h-10 transition-colors duration-300 text-foreground">
            <span className="font-display font-bold text-lg leading-tight">Hi-Tech Group</span>
            <span
              className={`text-[10px] align-center leading-tight opacity-80 max-w-[140px] ${isLoggedIn ? 'hidden xl:block' : ''}`}
            >
              Construction services in energy sector
            </span>
          </div>
        </a>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-4 lg:gap-6 min-w-0">
          {isLoggedIn ? (
            <>
              {primary.map(renderEmployeeLink)}
              {overflow.length > 0 && (
                <DropdownMenu>
                  <DropdownMenuTrigger
                    className={`${navLinkClass} inline-flex items-center gap-1 outline-none`}
                    aria-label={t('header.more', 'Ещё')}
                  >
                    {t('header.more', 'Ещё')}
                    <ChevronDown className="h-4 w-4" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-56">
                    {overflow.map((item) => (
                      <DropdownMenuItem key={item.id} asChild>
                        <Link to={item.href} className="flex items-center gap-2">
                          <item.icon className="h-4 w-4" />
                          {t(item.labelKey, item.labelFallback)}
                        </Link>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </>
          ) : (
            publicLinks.map((link) => (
              link.isInternal && location.pathname !== '/' ? (
                <a key={link.label} href={'/' + link.href} className={navLinkClass}>
                  {link.label}
                </a>
              ) : (
                <Link key={link.label} to={link.href.replace('/#', '#')} className={navLinkClass}>
                  {link.label}
                </Link>
              )
            ))
          )}
          {isLoggedIn && (
            <button
              type="button"
              onClick={() => setIsSearchOpen(true)}
              aria-label={t('search.open', 'Поиск')}
              title={t('search.open', 'Поиск') + ' (/)'}
              className="p-2 rounded-full text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
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
                <span>Профиль</span>
              </span>
            </Link>
          )}
        </div>

        {/* Mobile Menu Toggle */}
        <button
          className="md:hidden p-2 transition-colors text-foreground"
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        >
          {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </div>

      {/* Mobile Menu */}
      {isMobileMenuOpen && (
        <div className="md:hidden absolute top-full left-0 right-0 glass shadow-elevated animate-fade-in">
          <nav className="container-custom py-6 flex flex-col gap-4">
            {isLoggedIn
              ? employeeNav.map((item) => (
                <Link
                  key={item.id}
                  to={item.href}
                  className="flex items-center gap-2 text-foreground font-medium py-2 hover:text-primary transition-colors"
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  <item.icon className="h-4 w-4" />
                  {t(item.labelKey, item.labelFallback)}
                </Link>
              ))
              : publicLinks.map((link) => (
                link.isInternal && location.pathname !== '/' ? (
                  <a
                    key={link.label}
                    href={'/' + link.href}
                    className="text-foreground font-medium py-2 hover:text-primary transition-colors"
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.label}
                    to={link.href.replace('/#', '#')}
                    className="text-foreground font-medium py-2 hover:text-primary transition-colors"
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
                className="flex items-center gap-2 py-2 text-foreground font-medium hover:text-primary transition-colors"
              >
                <Search className="w-5 h-5" />
                <span>{t('search.open', 'Поиск')}</span>
              </button>
            )}
            <div className="flex gap-4 items-center">
              {isLoggedIn && showDeferredControls && <Suspense fallback={null}><NotificationsViewer /></Suspense>}
              {showDeferredControls && <Suspense fallback={null}><LanguageSwitcher /></Suspense>}
            </div>
            {!isLoggedIn ? (
              <Link to="/contacts" onClick={() => setIsMobileMenuOpen(false)}>
                <span className="btn-primary mt-4 inline-flex h-10 w-full items-center justify-center rounded-md px-4 py-2 text-sm font-medium">
                  {t('header.contacts')}
                </span>
              </Link>
            ) : (
              <Link to="/myprofile" onClick={() => setIsMobileMenuOpen(false)}>
                <span className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground">
                  <UserCircle className="w-5 h-5" />
                  Профиль
                </span>
              </Link>
            )}
          </nav>
        </div>
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
