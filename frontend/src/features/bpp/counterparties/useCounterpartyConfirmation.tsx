/**
 * Подтверждение контрагента перед отправкой документа этапа 3 — одним
 * вызовом (D-20):
 *
 * ```tsx
 * const { confirm, dialog } = useCounterpartyConfirmation();
 * const onSubmit = async () => {
 *   if (!(await confirm(counterparty))) return;   // отмена или непригоден
 *   await send();
 * };
 * return <>{…}{dialog}</>;
 * ```
 *
 * Проверенный и действующий — `true` сразу, окна нет; непроверенный —
 * окно `ConfirmCounterpartyDialog`, ответ по кнопке; заблокированный или
 * архивный — окно с причиной и `false` по закрытию.
 */
import { useCallback, useRef, useState, type ReactElement } from 'react';

import { ConfirmCounterpartyDialog } from './ConfirmCounterpartyDialog';
import { counterpartyGate, type CounterpartyForConfirm } from './counterpartyGate';

export interface CounterpartyConfirmation {
  confirm: (counterparty: CounterpartyForConfirm) => Promise<boolean>;
  dialog: ReactElement;
}

export function useCounterpartyConfirmation(): CounterpartyConfirmation {
  const [current, setCurrent] = useState<CounterpartyForConfirm | null>(null);
  const resolver = useRef<((answer: boolean) => void) | null>(null);

  const settle = useCallback((answer: boolean) => {
    resolver.current?.(answer);
    resolver.current = null;
    setCurrent(null);
  }, []);

  const confirm = useCallback((counterparty: CounterpartyForConfirm) => {
    if (counterpartyGate(counterparty) === 'ok') return Promise.resolve(true);
    // Прежний незавершённый вопрос закрывается отказом: ответ на него уже
    // никто не ждёт по-настоящему.
    resolver.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
      setCurrent(counterparty);
    });
  }, []);

  const dialog = (
    <ConfirmCounterpartyDialog
      counterparty={current}
      open={current !== null}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  );

  return { confirm, dialog };
}
