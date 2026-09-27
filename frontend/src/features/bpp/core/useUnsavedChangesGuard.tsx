/**
 * Диалог «Есть несохранённые изменения» (ТЗ §05 «Общие элементы всех
 * форм»): «Сохранить черновик / Уйти без сохранения / Отмена».
 *
 * Роутер приложения — `BrowserRouter`, а `useBlocker` работает только с
 * data-роутером, поэтому уход перехватывается двумя путями:
 * - закрытие вкладки, перезагрузка, переход на чужой адрес — `beforeunload`
 *   (браузер показывает свой диалог, текст задать нельзя);
 * - клик по ВНУТРЕННЕЙ ссылке — слушатель на `document` в фазе захвата: он
 *   срабатывает раньше обработчика `<Link>` (React слушает корень
 *   приложения, а `document` выше него), отменяет переход и открывает наш
 *   диалог. Переход после решения — `useNavigate`.
 *
 * Кнопку «Назад» браузера так не поймать — её закрывает автосохранение
 * черновика (`useDraftAutosave`, ТЗ §26.2).
 *
 * Хук возвращает элемент диалога — форма рендерит его у себя:
 * `const guard = useUnsavedChangesGuard({ dirty, onSaveDraft }); … {guard}`.
 */
import { useEffect, useRef, useState, type ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { reportApiError } from '@/lib/apiError';

export interface UnsavedChangesGuardOptions {
  /** Есть несохранённые изменения — только тогда уход перехватывается. */
  dirty: boolean;
  /** «Сохранить черновик»: после успеха — переход, при ошибке — остаёмся. */
  onSaveDraft: () => void | Promise<unknown>;
}

/**
 * Куда ведёт клик, если его надо перехватить; `null` — пропустить как есть.
 * Пропускаются: не левая кнопка, клик с модификатором (новая вкладка),
 * `target` кроме `_self`, `download`, чужой origin и ссылка на ту же
 * страницу (якорь внутри формы — не уход).
 */
export function interceptedDestination(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const origin = event.target instanceof Element ? event.target : null;
  const anchor = origin?.closest('a[href]');
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  const target = anchor.getAttribute('target');
  if (target && target !== '_self') return null;
  if (anchor.hasAttribute('download')) return null;

  const url = new URL(anchor.href, window.location.href);
  if (url.origin !== window.location.origin) return null;
  const here = window.location;
  if (url.pathname === here.pathname && url.search === here.search) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

export function useUnsavedChangesGuard({
  dirty,
  onSaveDraft,
}: UnsavedChangesGuardOptions): ReactElement {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [destination, setDestination] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const latestSave = useRef(onSaveDraft);
  latestSave.current = onSaveDraft;

  useEffect(() => {
    if (!dirty) return undefined;

    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Старые браузеры показывают диалог только при непустом returnValue.
      event.returnValue = '';
    };
    const onClick = (event: MouseEvent) => {
      const to = interceptedDestination(event);
      if (to === null) return;
      event.preventDefault();
      event.stopPropagation();
      setDestination(to);
    };

    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('click', onClick, true);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      document.removeEventListener('click', onClick, true);
    };
  }, [dirty]);

  const leave = () => {
    const to = destination;
    setDestination(null);
    if (to) navigate(to);
  };

  const saveAndLeave = async () => {
    setSaving(true);
    try {
      await latestSave.current();
    } catch (error) {
      reportApiError(error, t('bpp.unsaved.saveFailed', 'Не удалось сохранить черновик'));
      return;
    } finally {
      setSaving(false);
    }
    leave();
  };

  return (
    <AlertDialog
      open={destination !== null}
      onOpenChange={(open) => { if (!open && !saving) setDestination(null); }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('bpp.unsaved.title', 'Есть несохранённые изменения')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(
              'bpp.unsaved.description',
              'Сохраните черновик, чтобы вернуться к документу позже, или уйдите без сохранения.',
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={saving}>
            {t('bpp.unsaved.cancel', 'Отмена')}
          </AlertDialogCancel>
          <Button variant="outline" disabled={saving} onClick={leave}>
            {t('bpp.unsaved.leave', 'Уйти без сохранения')}
          </Button>
          <Button disabled={saving} onClick={() => { void saveAndLeave(); }}>
            {t('bpp.unsaved.saveDraft', 'Сохранить черновик')}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
