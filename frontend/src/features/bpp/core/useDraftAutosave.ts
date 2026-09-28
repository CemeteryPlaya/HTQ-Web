/**
 * Черновик формы в `localStorage` (ТЗ §26.2): «каждые 30 с черновик формы
 * сохраняется в localStorage и предлагается к восстановлению при повторном
 * открытии». Это же закрывает кнопку «Назад» браузера и истёкшую сессию:
 * с `BrowserRouter` уход по истории не перехватить (`useBlocker` нужен
 * data-роутер), поэтому страховка — не диалог, а сохранённый черновик.
 *
 * - `draft` — то, что лежало в хранилище на момент открытия формы (или смены
 *   `storageKey`): его форма предлагает восстановить. Последующие
 *   автосохранения `draft` не меняют — предложение не «уезжает» из-под
 *   человека, пока он решает.
 * - Пока `enabled` (обычно — «есть несохранённые изменения»), каждые
 *   `intervalMs` в хранилище пишется ПОСЛЕДНЕЕ значение формы; одинаковое
 *   дважды не пишется.
 * - `discard()` стирает черновик — после успешного сохранения документа или
 *   когда человек отказался восстанавливать.
 *
 * Хранилище может отказать (приватный режим, переполнение, запрет сайта) —
 * каждое обращение в try/catch: без черновика форма работает, просто без
 * страховки. Это штатная деградация, а не подмена данных, поэтому мимо
 * `lib/fallback` (см. «Что через него НЕ проходит» в CLAUDE.md).
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface StoredDraft<T> {
  /** Момент сохранения, ISO 8601 — «черновик от 28.09.2026 01:30». */
  savedAt: string;
  value: T;
}

export interface DraftAutosaveOptions {
  enabled: boolean;
  intervalMs?: number;
}

export const DRAFT_INTERVAL_MS = 30_000;

function readDraft<T>(storageKey: string): StoredDraft<T> | null {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredDraft<T>> | null;
    if (!parsed || typeof parsed.savedAt !== 'string' || !('value' in parsed)) return null;
    return { savedAt: parsed.savedAt, value: parsed.value as T };
  } catch {
    return null;
  }
}

export function useDraftAutosave<T>(
  storageKey: string,
  value: T,
  { enabled, intervalMs = DRAFT_INTERVAL_MS }: DraftAutosaveOptions,
): { draft: StoredDraft<T> | null; discard: () => void } {
  const [draft, setDraft] = useState<StoredDraft<T> | null>(() => readDraft<T>(storageKey));

  // Таймер не перезапускается на каждое нажатие клавиши: значение читается
  // из ref в момент срабатывания.
  const latestValue = useRef(value);
  latestValue.current = value;
  const lastWritten = useRef<string | null>(null);

  // Смена ключа (другой документ в той же форме) — перечитать черновик.
  const shownKey = useRef(storageKey);
  useEffect(() => {
    if (shownKey.current === storageKey) return;
    shownKey.current = storageKey;
    lastWritten.current = null;
    setDraft(readDraft<T>(storageKey));
  }, [storageKey]);

  useEffect(() => {
    if (!enabled) return undefined;
    const timer = window.setInterval(() => {
      let serialized: string | undefined;
      try {
        serialized = JSON.stringify(latestValue.current);
      } catch {
        return;
      }
      if (serialized === undefined || serialized === lastWritten.current) return;
      try {
        const payload = `{"savedAt":${JSON.stringify(new Date().toISOString())},"value":${serialized}}`;
        window.localStorage.setItem(storageKey, payload);
        lastWritten.current = serialized;
      } catch {
        // Хранилище недоступно — форма работает без черновика.
      }
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [enabled, intervalMs, storageKey]);

  const discard = useCallback(() => {
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      // Недоступное хранилище и так пусто для этой формы.
    }
    lastWritten.current = null;
    setDraft(null);
  }, [storageKey]);

  return { draft, discard };
}
