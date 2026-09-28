/**
 * Окно подтверждения контрагента для документов этапа 3 — договора и счёта
 * (D-20, ТЗ §18). Как пользоваться:
 *
 * ```tsx
 * const gate = counterpartyGate(cp);          // 'ok' | 'confirm' | 'unusable'
 * if (gate === 'ok') submit(); else setOpen(true);
 * <ConfirmCounterpartyDialog counterparty={cp} open={open}
 *   onConfirm={() => { setOpen(false); submit({ counterparty_confirmed: true }); }}
 *   onCancel={() => setOpen(false)} />
 * ```
 *
 * либо хуком `useCounterpartyConfirmation` — он сам пропускает
 * проверенного и возвращает `Promise<boolean>`.
 *
 * - **Проверенный и действующий** — окна нет: компонент ничего не рисует
 *   даже при `open`, подтверждать нечего.
 * - **Непроверенный** — предупреждение и явное подтверждение: кнопка
 *   «Подтвердить и продолжить» неактивна, пока автор не отметил, что
 *   проверил реквизиты. Подтверждение метку «Проверенный» не ставит —
 *   его пишет в аудит документа сервер.
 * - **Заблокированный или архивный** — продолжить нельзя вовсе: окно
 *   объясняет причину текстом E-CTR-01 (ТЗ §26.1) и предлагает только
 *   закрыть его. Сервер всё равно отвергнет такой документ.
 */
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

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
import { Checkbox } from '@/components/ui/checkbox';

import { formatDateTime } from '../format';

import {
  counterpartyDisplayName, counterpartyGate, type CounterpartyForConfirm,
} from './counterpartyGate';

interface Props {
  counterparty: CounterpartyForConfirm | null;
  open: boolean;
  /** Автор подтвердил непроверенного контрагента — можно отправлять. */
  onConfirm: () => void;
  /** Закрыл окно или контрагент непригоден — документ не отправляется. */
  onCancel: () => void;
}

export function ConfirmCounterpartyDialog({ counterparty, open, onConfirm, onCancel }: Props) {
  const { t } = useTranslation();
  const checkboxId = useId();
  const [checked, setChecked] = useState(false);

  // Каждое открытие — с чистой отметкой: подтверждение относится к этому
  // документу, а не переносится с прошлого раза.
  useEffect(() => {
    if (open) setChecked(false);
  }, [open, counterparty?.id]);

  if (!counterparty) return null;
  const gate = counterpartyGate(counterparty);
  if (gate === 'ok') return null;

  const name = counterpartyDisplayName(counterparty);
  const onOpenChange = (next: boolean) => { if (!next) onCancel(); };

  if (gate === 'unusable') {
    const blocked = counterparty.status === 'blocked';
    const when = counterparty.blocked_at ? formatDateTime(counterparty.blocked_at).slice(0, 10) : '—';
    return (
      <AlertDialog open={open} onOpenChange={onOpenChange}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {blocked
                ? t('bpp.counterparties.confirm.blockedTitle', 'Контрагент заблокирован')
                : t('bpp.counterparties.confirm.archivedTitle', 'Контрагент в архиве')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {blocked
                ? t(
                  'bpp.counterparties.confirm.blocked',
                  'Контрагент {{name}} заблокирован {{date}}: „{{reason}}“. Выберите другого контрагента или обратитесь к финансовому директору.',
                  { name, date: when, reason: counterparty.block_reason ?? '' },
                )
                : t(
                  'bpp.counterparties.confirm.archived',
                  'Контрагент {{name}} переведён в архив и в новых документах не используется. Выберите другого контрагента или обратитесь к финансовому директору.',
                  { name },
                )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('bpp.counterparties.confirm.close', 'Закрыть')}</AlertDialogCancel>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    );
  }

  const progress = counterparty.successful_documents !== undefined
    && counterparty.verified_threshold !== undefined
    ? t(
      'bpp.counterparties.confirm.progress',
      ' Удачных документов с ним: {{count}} из {{threshold}}, нужных для метки.',
      { count: counterparty.successful_documents, threshold: counterparty.verified_threshold },
    )
    : '';

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {t('bpp.counterparties.confirm.title', 'Контрагент не проверен')}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t(
              'bpp.counterparties.confirm.description',
              'У контрагента {{name}} нет метки «Проверенный»: с ним ещё не было нескольких удачных договоров или счетов, либо финансовый директор снял метку. Сверьте реквизиты с документами контрагента, прежде чем продолжить.',
              { name },
            )}
            {progress}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <label htmlFor={checkboxId} className="flex items-start gap-2 text-sm">
          <Checkbox
            id={checkboxId}
            checked={checked}
            onCheckedChange={(value) => setChecked(value === true)}
          />
          {t(
            'bpp.counterparties.confirm.checkbox',
            'Я проверил(а) реквизиты и подтверждаю выбор контрагента',
          )}
        </label>
        <AlertDialogFooter>
          <AlertDialogCancel>{t('bpp.document.cancel', 'Отмена')}</AlertDialogCancel>
          <Button disabled={!checked} onClick={onConfirm}>
            {t('bpp.counterparties.confirm.submit', 'Подтвердить и продолжить')}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export default ConfirmCounterpartyDialog;
