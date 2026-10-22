/**
 * Файлы КП поставщика (план этапа 3, T3.4): PDF, DOCX, XLSX, JPG, PNG до
 * 20 МБ, до 10 файлов. Проверка здесь — чтобы не гонять заведомый отказ;
 * сервер проверяет сам, плюс антивирус (без него загрузка — 503).
 */
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { FileText, Loader2, Paperclip, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';

import { PortalError, portalApi, portalKeys } from './client';
import type { PortalFile } from './types';

export const MAX_FILES = 10;
const MAX_BYTES = 20 * 1024 * 1024;
const ALLOWED = ['pdf', 'docx', 'xlsx', 'jpg', 'jpeg', 'png'];

const sizeText = (bytes: number) =>
  (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} МБ` : `${Math.max(1, Math.round(bytes / 1024))} КБ`);

interface Props {
  token: string;
  readOnly: boolean;
  /** Отказ, который страница разбирает сама (устройство, срок, лимит). */
  onFailure: (error: unknown) => boolean;
}

export function FilesSection({ token, readOnly, onFailure }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: portalKeys.files(token), queryFn: () => portalApi.files(token) });
  const files: PortalFile[] = data ?? [];

  const fail = (error: unknown) => {
    if (onFailure(error)) return;
    setProblem(error instanceof PortalError && error.detail
      ? error.detail : t('tender.portal.fileFailed', 'Не удалось загрузить файл. Повторите попытку.'));
  };

  const upload = async (file: File) => {
    setProblem(null);
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    if (!ALLOWED.includes(ext) || file.size > MAX_BYTES) {
      setProblem(t('tender.portal.fileRejected', 'Файл {{name}} не загружен: допустимы PDF, DOCX, XLSX, JPG, PNG до 20 МБ', { name: file.name }));
      return;
    }
    if (files.length >= MAX_FILES) {
      setProblem(t('tender.portal.fileLimit', 'Не больше {{max}} файлов', { max: MAX_FILES }));
      return;
    }
    setBusy(true);
    try {
      await portalApi.uploadFile(token, file);
      await queryClient.invalidateQueries({ queryKey: portalKeys.files(token) });
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  };

  const remove = async (doc: PortalFile) => {
    setBusy(true);
    try {
      await portalApi.removeFile(token, doc.id);
      await queryClient.invalidateQueries({ queryKey: portalKeys.files(token) });
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="space-y-3 rounded-2xl border bg-card p-4">
      <h2 className="text-lg font-semibold">{t('tender.portal.files', 'Файлы коммерческого предложения')}</h2>
      {files.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('tender.portal.noFiles', 'Файлов пока нет')}</p>
      ) : (
        <ul className="space-y-2">
          {files.map((doc) => (
            <li key={doc.id} className="flex items-center gap-2 text-sm">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate">{doc.name}</span>
              <span className="text-muted-foreground">{sizeText(doc.size)}</span>
              {!readOnly && (
                <Button
                  type="button" size="icon" variant="ghost" disabled={busy}
                  aria-label={t('tender.portal.removeFile', 'Удалить {{name}}', { name: doc.name })}
                  onClick={() => { void remove(doc); }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <div>
          <Label
            htmlFor="portal-offer-file"
            className="inline-flex h-11 cursor-pointer items-center gap-2 rounded-md border px-4 text-base font-normal hover:bg-muted"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
            {t('tender.portal.addFile', 'Добавить файл КП')}
          </Label>
          <input
            ref={input} id="portal-offer-file" type="file" className="sr-only" disabled={busy}
            accept=".pdf,.docx,.xlsx,.jpg,.jpeg,.png"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
            }}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {t('tender.portal.fileHint', 'PDF, DOCX, XLSX, JPG, PNG до 20 МБ, не больше {{max}} файлов', { max: MAX_FILES })}
          </p>
        </div>
      )}
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </section>
  );
}
