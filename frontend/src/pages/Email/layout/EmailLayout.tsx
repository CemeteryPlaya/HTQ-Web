import React from 'react';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';

interface Props {
  sidebar: React.ReactNode;
  children: React.ReactNode;
  title?: string;
}

/**
 * Mirrors the HRLayout shell so the Email page sits visually flush with
 * the rest of the workspace pages. Sidebar (260px) + main content; mobile
 * tucks the sidebar above the main pane via `lg:` breakpoint.
 */
export const EmailLayout: React.FC<Props> = ({ sidebar, children, title }) => {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1">
        <div className="container mx-auto px-4 py-8">
          {title && (
            <h1 className="mb-4 text-2xl font-semibold tracking-tight">{title}</h1>
          )}
          <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
            <aside className="lg:sticky lg:top-20 lg:self-start">
              <div className="rounded-2xl border bg-card/70 p-4 shadow-[var(--shadow-soft)]">
                <div className="mb-3 text-xs uppercase tracking-[0.25em] text-muted-foreground">
                  {t('email.sidebar.label', 'Почта')}
                </div>
                {sidebar}
              </div>
            </aside>

            <section className="min-h-[calc(100vh-220px)]">{children}</section>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default EmailLayout;
