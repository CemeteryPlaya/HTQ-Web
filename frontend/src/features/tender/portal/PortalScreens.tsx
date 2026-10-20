/**
 * Каркас страницы поставщика и экраны состояний (T3.5): одна колонка под
 * телефон, без шапки приложения — поставщик не сотрудник.
 */
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Ban, Clock, Link2Off, Smartphone, WifiOff } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { formatDateTime } from '@/features/bpp/format';

import type { PortalScreen } from './portalErrors';
import type { PortalCard } from './types';

export function PortalShell({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <main className="mx-auto w-full max-w-xl space-y-5 px-4 py-6 sm:py-10">
        {title && <p className="text-sm font-medium text-muted-foreground">{title}</p>}
        {children}
      </main>
    </div>
  );
}

export function ErrorScreen({ screen, retryAfter, onRetry }: {
  screen: PortalScreen; retryAfter?: number | null; onRetry?: () => void;
}) {
  const { t } = useTranslation();
  const texts: Record<PortalScreen, [ReactNode, string, string]> = {
    invalid: [<Link2Off key="i" className="h-10 w-10" />,
      t('tender.portal.invalidTitle', 'Ссылка недействительна'),
      t('tender.portal.invalidText', 'Ссылка устарела, отозвана или набрана с ошибкой. Запросите у закупщика новую ссылку.')],
    device: [<Smartphone key="d" className="h-10 w-10" />,
      t('tender.portal.deviceTitle', 'Ссылка открыта на другом устройстве'),
      t('tender.portal.deviceText',
        'Предложение по этой ссылке ведётся только с одного устройства — обратитесь к закупщику, чтобы он сбросил привязку.')],
    closed: [<Clock key="c" className="h-10 w-10" />,
      t('tender.portal.closedTitle', 'Приём предложений завершён'),
      t('tender.portal.closedText', 'Срок подачи предложений истёк. О решении сообщит закупщик.')],
    rate: [<Clock key="r" className="h-10 w-10" />,
      t('tender.portal.rateTitle', 'Слишком много запросов'),
      retryAfter
        ? t('tender.portal.rateText', 'Слишком много запросов, повторите через {{seconds}} с', { seconds: retryAfter })
        : t('tender.portal.rateTextLater', 'Слишком много запросов, повторите чуть позже')],
    unavailable: [<Ban key="u" className="h-10 w-10" />,
      t('tender.portal.unavailableTitle', 'Сервис временно недоступен'),
      t('tender.portal.unavailableText', 'Попробуйте открыть ссылку позже.')],
    network: [<WifiOff key="n" className="h-10 w-10" />,
      t('tender.portal.networkTitle', 'Нет связи с сервером'),
      t('tender.portal.networkText', 'Проверьте подключение к интернету и повторите.')],
    generic: [<Ban key="g" className="h-10 w-10" />,
      t('tender.portal.genericTitle', 'Не удалось открыть предложение'),
      t('tender.portal.genericText', 'Повторите попытку позже или обратитесь к закупщику.')],
  };
  const [icon, title, text] = texts[screen];
  const retryable = screen === 'rate' || screen === 'network' || screen === 'unavailable' || screen === 'generic';
  return (
    <PortalShell>
      <div className="space-y-3 rounded-2xl border bg-card p-6 text-center">
        <div className="mx-auto flex w-fit text-muted-foreground">{icon}</div>
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="text-base text-muted-foreground">{text}</p>
        {retryable && onRetry && (
          <Button type="button" variant="outline" size="lg" onClick={onRetry}>
            {t('tender.portal.retry', 'Повторить')}
          </Button>
        )}
      </div>
    </PortalShell>
  );
}

/** Промежуточная карточка: ничего не пишет, привязку делает кнопка. */
export function LandingCard({ card, pending, onOpen }: {
  card: PortalCard; pending: boolean; onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <PortalShell>
      <div className="space-y-4 rounded-2xl border bg-card p-6">
        <p className="text-sm text-muted-foreground">{t('tender.portal.inviteFrom', 'Приглашение к участию в тендере')}</p>
        <h1 className="text-2xl font-bold">{card.company_name}</h1>
        <p className="text-base">
          {t('tender.portal.tenderNumber', 'Тендер {{number}}', { number: card.tender_number })}
        </p>
        <p className="text-base">
          {card.intake_open
            ? t('tender.portal.deadline', 'Приём предложений до {{deadline}}', { deadline: formatDateTime(card.deadline_at) })
            : t('tender.portal.intakeOver', 'Приём предложений завершён — предложение можно только посмотреть.')}
        </p>
        <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40">
          {t('tender.portal.bindWarning',
            'Ссылка закрепится за этим устройством: продолжить работу с предложением на другом устройстве будет нельзя.')}
        </p>
        <Button type="button" size="lg" className="w-full" disabled={pending} onClick={onOpen}>
          {t('tender.portal.open', 'Открыть предложение')}
        </Button>
      </div>
    </PortalShell>
  );
}
