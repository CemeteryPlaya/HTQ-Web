/**
 * Оболочка формы документа модуля БЗО — «общие элементы всех форм» ТЗ §05.
 *
 * - **Шапка:** системный номер, цветной бейдж статуса (`StatusBadge`),
 *   автор, дата создания (`ДД.ММ.ГГГГ ЧЧ:ММ` по Алматы), кнопки действий
 *   справа.
 * - **Кнопки — только из `allowedActions`.** Режим формы («Создание»,
 *   «Редактирование», «Просмотр», «Согласование») определяет сервер и
 *   возвращает список разрешённых действий; фронт рисует ровно их. Действие
 *   из `actions`, которого нет в `allowedActions`, не рисуется, а ключ из
 *   `allowedActions` без описания в `actions` — тоже (подписи ему взять
 *   неоткуда). Пустой `allowedActions` — режим «только чтение»: он же
 *   отдаётся телу формы и закрывает правку файлов.
 * - **Кнопки защищены от двойного нажатия** (`DocumentActionButton` поверх
 *   `useIdempotentAction`), и пока идёт одно действие, остальные тоже
 *   заблокированы: два перехода статуса одновременно не шлём.
 * - **Вкладки внизу:** «Согласование» (компоненты движка signoff), «Файлы»
 *   (`FilesPanel` поверх `apps.files`), «История изменений» — `HistoryTab`
 *   по `historyType`/`documentId`, либо своё содержимое слотом `history`.
 *   Тип объекта журнала — НЕ `subjectType`: журнал `AuditLog` и проверка
 *   доступа к нему (`audit.register_history_access`) ключуются
 *   `_meta.label_lower` модели (`bpp.purchaserequest`), а предмет signoff —
 *   своим именем (`bpp.purchase_request`). Подставь форма один вместо
 *   другого — ручка истории ответит 404, и вкладка всегда показывала бы
 *   «История недоступна». Поэтому одно из двух — `historyType` или
 *   `history` — обязательно на уровне типа, а `history={null}` явно убирает
 *   вкладку. У нового, ещё не сохранённого документа вкладок нет —
 *   показывать в них нечего.
 * - **Черновик и уход со страницы** — при переданном `draft`: автосохранение
 *   в `localStorage` каждые 30 с (`useDraftAutosave`, ключ
 *   `bpp:draft:<subjectType>:<id|new>`), плашка «Найден несохранённый
 *   черновик от …» с «Восстановить»/«Удалить», диалог несохранённых
 *   изменений (`useUnsavedChangesGuard`). Успешное действие стирает
 *   черновик: состояние документа теперь на сервере.
 */
import { useCallback, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { History } from 'lucide-react';

import { FilesPanel } from '@/components/files/FilesPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { formatDateTime } from '../format';
import { ApprovalTab } from './ApprovalTab';
import { DocumentActionButton, type BppDocumentAction } from './DocumentActionButton';
import { HistoryTab } from './HistoryTab';
import { StatusBadge } from './StatusBadge';
import type { StatusKind } from './statusDictionaries';
import { useDraftAutosave } from './useDraftAutosave';
import { useUnsavedChangesGuard } from './useUnsavedChangesGuard';

export type { BppDocumentAction } from './DocumentActionButton';

/** Черновик формы: значение, признак правки и что делать при восстановлении. */
export interface BppDocumentDraft<T> {
  value: T;
  dirty: boolean;
  onRestore: (value: T) => void;
  /** «Сохранить черновик» в диалоге ухода со страницы. */
  onSaveDraft: () => void | Promise<unknown>;
}

export interface BppDocumentShellBaseProps<T> {
  /** Тип предмета signoff (`bpp.purchase_request`) — адрес процесса. */
  subjectType: string;
  /** `null` — документ ещё не создан (режим «Создание»). */
  documentId: string | null;
  number?: string | null;
  status?: { kind: StatusKind; code: string } | null;
  authorName?: string | null;
  createdAt?: string | null;
  allowedActions: string[];
  actions: Record<string, BppDocumentAction>;
  /** Владелец в `apps.files`, если не совпадает с `subjectType`. */
  fileOwnerType?: string;
  /** У документа есть согласование (ТЗ §05: «где есть»). */
  withApproval?: boolean;
  /** У документа есть файлы; `false` — вкладки «Файлы» нет (бюджет). */
  withFiles?: boolean;
  /**
   * Режим «только просмотр» явно. По умолчанию — пустой `allowedActions`,
   * но у части документов в нём всегда есть действия, не меняющие документ
   * («Печать», «Экспорт», «Копировать»): тогда режим задаёт форма.
   */
  readOnly?: boolean;
  /** Свои вкладки документа после «Файлов» («Версии» бюджета, «Исполнение»). */
  extraTabs?: { key: string; label: string; content: ReactNode }[];
  draft?: BppDocumentDraft<T>;
  children: ReactNode | ((ctx: { readOnly: boolean }) => ReactNode);
}

/**
 * Источник вкладки «История изменений» — ровно один из двух:
 * - `historyType` — тип объекта журнала (`_meta.label_lower` модели:
 *   `bpp.purchaserequest`, `bpp.accountablefundsrequest`, `bpp.budget`),
 *   вкладка — `HistoryTab` по нему и `documentId`;
 * - `history` — своё содержимое вкладки; `null` — вкладки нет.
 */
export type BppDocumentHistorySource =
  | { historyType: string; history?: undefined }
  | { history: ReactNode; historyType?: undefined };

export type BppDocumentShellProps<T> = BppDocumentShellBaseProps<T> & BppDocumentHistorySource;

const NO_SAVE = () => undefined;

const draftStorageKey = (subjectType: string, documentId: string | null) =>
  `bpp:draft:${subjectType}:${documentId ?? 'new'}`;

export function BppDocumentShell<T>({
  subjectType,
  documentId,
  number,
  status,
  authorName,
  createdAt,
  allowedActions,
  actions,
  fileOwnerType,
  withApproval = true,
  withFiles = true,
  readOnly: readOnlyProp,
  extraTabs = [],
  history,
  historyType,
  draft,
  children,
}: BppDocumentShellProps<T>) {
  const { t } = useTranslation();
  const readOnly = readOnlyProp ?? allowedActions.length === 0;
  const dirty = Boolean(draft?.dirty) && !readOnly;

  const stored = useDraftAutosave<T | null>(
    draftStorageKey(subjectType, documentId),
    draft ? draft.value : null,
    { enabled: dirty },
  );
  const [draftOffered, setDraftOffered] = useState(true);
  const guard = useUnsavedChangesGuard({ dirty, onSaveDraft: draft?.onSaveDraft ?? NO_SAVE });

  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const onPendingChange = useCallback((key: string, pending: boolean) => {
    setBusy((current) => (current[key] === pending ? current : { ...current, [key]: pending }));
  }, []);
  const { discard } = stored;
  const onDone = useCallback(() => { discard(); }, [discard]);

  const visibleActions = allowedActions.filter((key) => key in actions);
  const anyBusy = Object.values(busy).some(Boolean);

  const showDraftBanner = Boolean(draft && stored.draft && draftOffered && !readOnly);
  const historyContent = documentId === null
    ? null
    : historyType !== undefined
      ? <HistoryTab objectType={historyType} objectId={documentId} />
      : (history ?? null);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-bold tracking-tight">
              {number || t('bpp.document.new', 'Новый документ')}
            </h2>
            {status && <StatusBadge kind={status.kind} status={status.code} />}
            {readOnly && (
              <Badge variant="outline">{t('bpp.document.readOnly', 'Только просмотр')}</Badge>
            )}
            {dirty && (
              <Badge
                variant="outline"
                className="border-amber-300 text-amber-800 dark:text-amber-300"
              >
                {t('bpp.document.unsaved', 'Есть несохранённые изменения')}
              </Badge>
            )}
          </div>
          {(authorName || createdAt) && (
            <p className="text-sm text-muted-foreground">
              {authorName && (
                <span>{t('bpp.document.author', 'Автор: {{name}}', { name: authorName })}</span>
              )}
              {authorName && createdAt && ' · '}
              {createdAt && (
                <span>
                  {t('bpp.document.createdAt', 'Создан {{date}}', {
                    date: formatDateTime(createdAt),
                  })}
                </span>
              )}
            </p>
          )}
        </div>

        {visibleActions.length > 0 && (
          <div className="flex flex-wrap gap-2 sm:justify-end">
            {visibleActions.map((key) => (
              <DocumentActionButton
                key={key}
                actionKey={key}
                action={actions[key]}
                disabled={anyBusy && !busy[key]}
                onPendingChange={onPendingChange}
                onDone={onDone}
              />
            ))}
          </div>
        )}
      </header>

      {showDraftBanner && stored.draft && draft && (
        <div
          role="status"
          className="flex flex-col gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40 sm:flex-row sm:items-center sm:justify-between"
        >
          <span className="flex items-center gap-2">
            <History className="h-4 w-4 shrink-0" />
            {t('bpp.document.draftFound', 'Найден несохранённый черновик от {{date}}', {
              date: formatDateTime(stored.draft.savedAt),
            })}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => {
                const saved = stored.draft;
                setDraftOffered(false);
                if (saved) draft.onRestore(saved.value as T);
              }}
            >
              {t('bpp.document.draftRestore', 'Восстановить')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setDraftOffered(false);
                stored.discard();
              }}
            >
              {t('bpp.document.draftDiscard', 'Удалить')}
            </Button>
          </div>
        </div>
      )}

      <div>{typeof children === 'function' ? children({ readOnly }) : children}</div>

      {documentId !== null && (
        <Tabs
          defaultValue={withApproval
            ? 'approval'
            : withFiles ? 'files' : (extraTabs[0]?.key ?? 'history')}
        >
          <TabsList>
            {withApproval && (
              <TabsTrigger value="approval">{t('bpp.document.tabApproval', 'Согласование')}</TabsTrigger>
            )}
            {withFiles && (
              <TabsTrigger value="files">{t('bpp.document.tabFiles', 'Файлы')}</TabsTrigger>
            )}
            {extraTabs.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.key}>{tab.label}</TabsTrigger>
            ))}
            {historyContent && (
              <TabsTrigger value="history">{t('bpp.document.tabHistory', 'История изменений')}</TabsTrigger>
            )}
          </TabsList>
          {withApproval && (
            <TabsContent value="approval">
              <ApprovalTab subjectType={subjectType} subjectId={documentId} />
            </TabsContent>
          )}
          {withFiles && (
            <TabsContent value="files">
              <FilesPanel
                ownerType={fileOwnerType ?? subjectType}
                ownerId={documentId}
                readOnly={readOnly}
              />
            </TabsContent>
          )}
          {extraTabs.map((tab) => (
            <TabsContent key={tab.key} value={tab.key}>{tab.content}</TabsContent>
          ))}
          {historyContent && <TabsContent value="history">{historyContent}</TabsContent>}
        </Tabs>
      )}

      {guard}
    </div>
  );
}

export default BppDocumentShell;
