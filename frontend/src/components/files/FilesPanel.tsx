/**
 * «Документы» объекта — файловая подсистема ТЗ §21 (apps.files), общая для
 * всех владельцев: заявки, договора, …
 *
 * Версии — по ТЗ: номер присваивается при загрузке и больше не меняется,
 * новая версия грузится поверх действующей и помечает её «Заменён», история
 * остаётся целиком. Если действующую уже заменил кто-то другой, сервер
 * отвечает 409 E-CON-01 — панель показывает его текст и перечитывает папку.
 *
 * Правил здесь нет намеренно: какие типы есть, их форматы и размеры (из
 * справочника «Типы файлов»), можно ли что-то добавить (`can_add`), можно ли
 * вообще менять файлы (`can_modify` — статус владельца, права) и удаляется
 * ли документ насовсем (`delete_is_physical`) — решает сервер. Панель только
 * следует ему и заранее отсекает то, что сервер всё равно отвергнет
 * (расширение и размер), — чтобы не гнать 20 МБ по сети ради отказа.
 *
 * Готовых ссылок на файлы в папке нет: скачивание журналируется (ТЗ §25.2),
 * поэтому ссылку панель просит у сервера на каждый клик (`filesApi.link`).
 */

import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { isValid, parseISO } from 'date-fns';
import type { TFunction } from 'i18next';
import { ChevronDown, ChevronUp, Loader2, Paperclip, Trash2, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { downloadFileUrl } from '@/api/fileManager';
import { filesApi } from '@/api/files';
import { acceptableFile, formatsLabel } from '@/components/files/fileChecks';
import {
  useFileFolder, useRemoveFile, useUploadFile, useUploadFileVersion,
} from '@/hooks/useFiles';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';
import type { FileDocument, FileTypeInfo, FileVersion, OwnerId } from '@/types/files';

const MB = 1024 * 1024;

/** Что нужно контролам загрузки о типе: из папки владельца или, где владельца
 *  ещё нет, из справочника (`useFileTypes`). */
export interface UploadType {
  code: string;
  name: string;
  formats: string[];
  max_mb: number;
  can_add?: boolean;
  reason?: string | null;
}

/** Время — по Алматы (ТЗ стр. 11), как и в текстах сервера («Документ изменён
 *  … в 14:32»): у сотрудника в другом поясе иначе разошлись бы подпись у
 *  версии и время в сообщении о конфликте. */
const DISPLAY_TZ = 'Asia/Almaty';
const displayParts = new Intl.DateTimeFormat('en-GB', {
  timeZone: DISPLAY_TZ, year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
});

/** Дата с секундами; `precise` — ещё миллисекунды и пояс (для подсказки).
 *  `parseISO`, а не `new Date`: сервер отдаёт микросекунды, которых
 *  стандартный разбор дат не обещает понимать. */
function formatMoment(iso: string, precise = false): string {
  const date = parseISO(iso);
  if (!isValid(date)) return iso;
  const p = Object.fromEntries(displayParts.formatToParts(date).map((part) => [part.type, part.value]));
  const text = `${p.day}.${p.month}.${p.year} ${p.hour}:${p.minute}:${p.second}`;
  return precise
    ? `${text}.${String(date.getMilliseconds()).padStart(3, '0')} (${DISPLAY_TZ})`
    : text;
}

function formatSize(t: TFunction, language: string, bytes: number): string {
  const number = (value: number) => value.toLocaleString(language, { maximumFractionDigits: 1 });
  if (bytes < 1024) return `${bytes} ${t('files.unitB')}`;
  if (bytes < MB) return `${number(bytes / 1024)} ${t('files.unitKB')}`;
  return `${number(bytes / MB)} ${t('files.unitMB')}`;
}

function uploaderOf(version: FileVersion): string {
  const name = version.uploaded_by_name || `#${version.uploaded_by_id}`;
  return version.uploaded_by_department_name
    ? `${name} (${version.uploaded_by_department_name})`
    : name;
}

/* ─── Выбор типа и файла — общий для панели и страницы создания ───────── */

interface UploadControlsProps {
  types: UploadType[];
  /** Идёт загрузка именно отсюда — крутится значок на кнопке. */
  busy?: boolean;
  disabled?: boolean;
  /** Почему приложить нельзя вовсе — показывается вместо подсказки. */
  disabledReason?: string | null;
  onPick: (file: File, fileType: string) => void;
}

/**
 * Тип документа выбирается ДО файла и сбрасывается после каждого: иначе
 * второй файл молча лёг бы в тип первого, а поменять тип у приложенного
 * документа нельзя — только удалить и приложить заново. Тип, в который
 * добавить нельзя (предел, «уже приложен»), виден, но выключен.
 */
export function FileUploadControls({
  types, busy = false, disabled = false, disabledReason = null, onPick,
}: UploadControlsProps) {
  const { t, i18n } = useTranslation();
  const [code, setCode] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const addable = types.filter((type) => type.can_add !== false);
  const reasonAll = disabledReason
    ?? (types.length > 0 && addable.length === 0 ? types[0].reason ?? null : null);
  const off = disabled || busy || Boolean(reasonAll);
  const selected = types.find((type) => type.code === code) ?? null;

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Сброс — чтобы тот же файл можно было выбрать ещё раз.
    event.target.value = '';
    if (!file || !selected || !acceptableFile(t, file, selected)) return;
    onPick(file, selected.code);
    setCode('');
  };

  const hint = reasonAll
    ?? (selected
      ? t('attachments.allowed', { types: formatsLabel(selected.formats), mb: selected.max_mb })
      : t('attachments.pickTypeFirst'));

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <Select value={code} onValueChange={setCode} disabled={off}>
          <SelectTrigger className="w-full sm:w-56" aria-label={t('attachments.typeLabel')}>
            <SelectValue placeholder={t('attachments.typeLabel')} />
          </SelectTrigger>
          <SelectContent>
            {types.map((type) => (
              <SelectItem
                key={type.code}
                value={type.code}
                disabled={type.can_add === false}
                title={type.can_add === false ? type.reason ?? undefined : undefined}
              >
                {type.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={selected ? selected.formats.join(',') : undefined}
          disabled={off || !selected}
          onChange={onFile}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={off || !selected}
          onClick={() => inputRef.current?.click()}
        >
          {busy
            ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            : <Paperclip className="mr-2 h-4 w-4" />}
          {t('attachments.attach')}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

/* ─── Документ и его версии ───────────────────────────────────────────── */

/** Владелец папки — нужен строкам, чтобы попросить ссылку на скачивание. */
interface OwnerProps {
  ownerType: string;
  ownerId: OwnerId;
}

/** Что браузер показывает сам (media отдаёт это `inline`) — открывается в
 *  новой вкладке. Остальное скачивается, не уводя со страницы. */
const VIEWABLE_MIME = new Set(['application/pdf', 'image/png', 'image/jpeg']);

function FileLink({ ownerType, ownerId, version }: OwnerProps & { version: FileVersion }) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);

  const open = async () => {
    // Вкладка открывается синхронно, прямо в обработчике клика: окно,
    // открытое после await, блокировщик всплывающих окон счёл бы непрошеным.
    const tab = VIEWABLE_MIME.has(version.mime) ? window.open('', '_blank') : null;
    setPending(true);
    try {
      const { url } = await filesApi.link(ownerType, ownerId, version.document_id, version.id);
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        // Сюда же PDF, если вкладку не дал открыть блокировщик окон:
        // скачать лучше, чем увести пользователя со страницы.
        downloadFileUrl(url);
      }
    } catch (err) {
      tab?.close();
      reportApiError(err, t('attachments.downloadError'));
    } finally {
      setPending(false);
    }
  };

  return (
    <button
      type="button"
      onClick={open}
      disabled={pending}
      title={t('attachments.download')}
      className="min-w-0 break-all text-left font-medium text-primary underline-offset-2 hover:underline disabled:cursor-wait disabled:opacity-60"
    >
      {version.name}
    </button>
  );
}

function Moment({ iso }: { iso: string }) {
  // В подсказке — те же часы, но с миллисекундами и поясом: сырое ISO
  // сервера (UTC) показало бы другой час, чем подпись рядом.
  return <time dateTime={iso} title={formatMoment(iso, true)}>{formatMoment(iso)}</time>;
}

function VersionRow({ ownerType, ownerId, version }: OwnerProps & { version: FileVersion }) {
  const { t, i18n } = useTranslation();
  // «Заменён» и «Удалён» — независимые признаки: у удалённого после отправки
  // документа история версий хранится ради аудита, и заменённость в ней
  // должна оставаться видна.
  return (
    <li className="space-y-0.5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline">v{version.version_no}</Badge>
        <FileLink ownerType={ownerType} ownerId={ownerId} version={version} />
        {version.is_replaced && (
          <Badge variant="secondary">{t('attachments.replaced')}</Badge>
        )}
        {!version.is_replaced && !version.deleted_at && (
          <Badge>{t('attachments.current')}</Badge>
        )}
        {version.deleted_at && (
          <Badge variant="outline">{t('attachments.deletedBadge')}</Badge>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        <Moment iso={version.uploaded_at} />
        {' · '}{uploaderOf(version)}
        {' · '}{formatSize(t, i18n.language, version.size)}
        {version.sha256 && (
          <>
            {' · '}
            <span className="font-mono" title={version.sha256}>
              SHA-256 {version.sha256.slice(0, 12)}
            </span>
          </>
        )}
      </p>
    </li>
  );
}

interface DocumentItemProps extends OwnerProps {
  doc: FileDocument;
  type: UploadType | undefined;
  canModify: boolean;
  deleteIsPhysical: boolean;
  /** Идёт любая правка папки — остальные действия ждут. */
  busy: boolean;
  versionPending: boolean;
  removePending: boolean;
  onNewVersion: (file: File) => void;
  onRemove: () => void;
}

function DocumentItem({
  ownerType, ownerId, doc, type, canModify, deleteIsPhysical, busy,
  versionPending, removePending, onNewVersion, onRemove,
}: DocumentItemProps) {
  const { t, i18n } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const current = doc.current;
  const deleted = doc.deleted_at != null;

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file && (!type || acceptableFile(t, file, type))) onNewVersion(file);
  };

  return (
    <li className={cn('space-y-2 rounded-lg border p-3', deleted && 'bg-muted/40 opacity-70')}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{doc.file_type_name}</Badge>
            <FileLink ownerType={ownerType} ownerId={ownerId} version={current} />
            <Badge variant="outline">v{current.version_no}</Badge>
            {deleted
              ? <Badge variant="destructive">{t('attachments.deletedBadge')}</Badge>
              : <Badge>{t('attachments.current')}</Badge>}
          </div>
          <p className="text-xs text-muted-foreground">
            {formatSize(t, i18n.language, current.size)}
            {' · '}<Moment iso={current.uploaded_at} />
            {' · '}{uploaderOf(current)}
          </p>
          {doc.deleted_at && (
            <p className="text-xs text-muted-foreground">
              {t('attachments.deletedAt', { time: formatMoment(doc.deleted_at) })}
            </p>
          )}
        </div>

        {canModify && !deleted && (
          <div className="flex shrink-0 flex-wrap gap-2">
            <input
              ref={inputRef}
              type="file"
              className="hidden"
              accept={type ? type.formats.join(',') : undefined}
              disabled={busy}
              onChange={onFile}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              aria-label={`${t('attachments.newVersion')}: ${current.name}`}
              onClick={() => inputRef.current?.click()}
            >
              {versionPending
                ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                : <Upload className="mr-2 h-4 w-4" />}
              {t('attachments.newVersion')}
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="text-destructive"
                  disabled={busy}
                  aria-label={`${t('attachments.delete')}: ${current.name}`}
                >
                  {removePending
                    ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    : <Trash2 className="mr-2 h-4 w-4" />}
                  {t('attachments.delete')}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t('attachments.deleteTitle', { name: current.name })}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {deleteIsPhysical
                      ? t('attachments.deletePhysical')
                      : t('attachments.deleteSoft')}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t('attachments.cancel')}</AlertDialogCancel>
                  <AlertDialogAction
                    className={buttonVariants({ variant: 'destructive' })}
                    onClick={onRemove}
                  >
                    {t('attachments.delete')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        )}
      </div>

      {doc.versions.length > 1 && (
        <div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded
              ? <ChevronUp className="mr-1 h-4 w-4" />
              : <ChevronDown className="mr-1 h-4 w-4" />}
            {t('attachments.versions', { n: doc.versions.length })}
          </Button>
          {expanded && (
            <ol className="mt-2 space-y-2 border-l pl-3">
              {doc.versions.map((version) => (
                <VersionRow key={version.id} ownerType={ownerType} ownerId={ownerId} version={version} />
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  );
}

/* ─── Панель ──────────────────────────────────────────────────────────── */

interface Props {
  /** Ключ владельца в подсистеме: `approvals.request`, … */
  ownerType: string;
  ownerId: OwnerId;
  title?: string;
  /** Только просмотр, что бы ни ответил сервер (карточка согласования). */
  readOnly?: boolean;
}

export function FilesPanel({ ownerType, ownerId, title, readOnly = false }: Props) {
  const { t } = useTranslation();
  const folder = useFileFolder(ownerType, ownerId);
  const upload = useUploadFile(ownerType, ownerId);
  const uploadVersion = useUploadFileVersion(ownerType, ownerId);
  const remove = useRemoveFile(ownerType, ownerId);

  const data = folder.data;
  const canModify = Boolean(data?.can_modify) && !readOnly;
  const busy = upload.isPending || uploadVersion.isPending || remove.isPending;
  const typesByCode = new Map<string, FileTypeInfo>((data?.types ?? []).map((type) => [type.code, type]));

  const addDocument = (file: File, fileType: string) => upload.mutate(
    { file, fileType },
    {
      onSuccess: () => toast.success(t('attachments.uploaded')),
      onError: (err) => reportApiError(err, t('attachments.uploadError')),
    },
  );
  // 409 E-CON-01 («Документ изменён пользователем … Обновите страницу») —
  // сервер уже объяснил, что случилось; папку хук перечитывает сам.
  const addVersion = (doc: FileDocument, file: File) => uploadVersion.mutate(
    { documentId: doc.document_id, file, baseFileId: doc.current.id },
    {
      onSuccess: () => toast.success(t('attachments.versionUploaded')),
      onError: (err) => reportApiError(err, t('attachments.uploadError')),
    },
  );
  const removeDocument = (documentId: string, physical: boolean) => remove.mutate(documentId, {
    onSuccess: () => toast.success(
      physical ? t('attachments.removed') : t('attachments.markedDeleted'),
    ),
    onError: (err) => reportApiError(err, t('attachments.deleteError')),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>{title ?? t('attachments.title')}</CardTitle>
          {data?.quotas.map((quota) => (
            <Badge key={quota.group} variant="outline">
              {t('attachments.counter', { n: quota.used, max: quota.max })}
            </Badge>
          ))}
        </div>
        <CardDescription>{t('attachments.versionHint')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {folder.isLoading && <Skeleton className="h-16" />}
        {folder.isError && (
          <p className="text-sm text-destructive">{t('attachments.loadError')}</p>
        )}

        {data && canModify && (
          <FileUploadControls
            types={data.types}
            busy={upload.isPending}
            disabled={busy}
            onPick={addDocument}
          />
        )}
        {data && !data.can_modify && !readOnly && data.modify_reason && (
          <p className="text-xs text-muted-foreground">{data.modify_reason}</p>
        )}

        {data && data.documents.length === 0 && (
          <p className="text-sm text-muted-foreground">{t('attachments.empty')}</p>
        )}
        {data && data.documents.length > 0 && (
          <ul className="space-y-3">
            {data.documents.map((doc) => (
              <DocumentItem
                key={doc.document_id}
                ownerType={ownerType}
                ownerId={ownerId}
                doc={doc}
                type={typesByCode.get(doc.file_type)}
                canModify={canModify}
                deleteIsPhysical={data.delete_is_physical}
                busy={busy}
                versionPending={uploadVersion.isPending
                  && uploadVersion.variables?.documentId === doc.document_id}
                removePending={remove.isPending && remove.variables === doc.document_id}
                onNewVersion={(file) => addVersion(doc, file)}
                onRemove={() => removeDocument(doc.document_id, data.delete_is_physical)}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default FilesPanel;
