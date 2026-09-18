/**
 * Связь договора / счёта с заявкой конструктора «Запросы».
 *
 * Заявка приходит двумя путями: из адреса (`?request_id=` — кнопка «Создать
 * договор» на самой заявке) или выбором из списка одобренных прямо в форме.
 * В обоих случаях дальше одно правило (`backend/apps/contracts/services/
 * request_link.py`): документ заключается на ТУ ЖЕ строку бюджета, под
 * которую заявку одобрили, — поэтому форма подставляет строку из заявки и
 * запирает каскад «администратор → программа», а не предлагает выбрать.
 *
 * Состояние связи (заявка из адреса, её строка бюджета) — в хуке
 * `useLinkedRequest` рядом; здесь только представление.
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ClipboardList, ExternalLink, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { contractsApi } from '@/api/contracts';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import type { LinkedRequest } from '@/types/contracts';

interface Props {
  value: LinkedRequest | null;
  onChange: (request: LinkedRequest | null) => void;
  /** Строка бюджета заявки не нашлась среди доступных форме. */
  missing?: boolean;
  /** Заявка из адреса не загрузилась (нет такой или раздел выключен). */
  presetFailed?: boolean;
}

export function LinkedRequestPicker({ value, onChange, missing, presetFailed }: Props) {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ['contracts', 'linked-requests'],
    queryFn: () => contractsApi.listLinkedRequests().then((r) => r.data),
    enabled: value == null,
    retry: false,
  });
  const options = list.data ?? [];

  if (value) {
    return (
      <div className="rounded-md border bg-muted/40 p-3 text-sm">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t('contracts.linkedRequest.linked')}
            </p>
            <p className="mt-0.5 font-medium">
              <span className="font-mono">{value.code}</span> — {value.title || value.template_name}
            </p>
            <p className="text-xs text-muted-foreground">{value.template_name}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button asChild type="button" variant="ghost" size="sm">
              <Link to={`/requests/${value.id}`} target="_blank" rel="noreferrer">
                <ExternalLink className="mr-1 h-3.5 w-3.5" />
                {t('contracts.linkedRequest.open')}
              </Link>
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)} aria-label={t('contracts.linkedRequest.unlink')}>
              <X className="mr-1 h-3.5 w-3.5" />
              {t('contracts.linkedRequest.unlink')}
            </Button>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t('contracts.linkedRequest.fundingLocked')}</p>
        {missing && (
          <p className="mt-1 text-xs text-destructive">{t('contracts.linkedRequest.lineMissing')}</p>
        )}
      </div>
    );
  }

  return (
    <div>
      <Label htmlFor="linked-request" className="flex items-center gap-1.5">
        <ClipboardList className="h-3.5 w-3.5 text-muted-foreground" />
        {t('contracts.linkedRequest.label')}
        <span className="font-normal text-muted-foreground">({t('contracts.linkedRequest.optional')})</span>
      </Label>
      <Select
        value=""
        onValueChange={(id) => onChange(options.find((row) => String(row.id) === id) ?? null)}
        disabled={list.isError || list.isLoading}
      >
        <SelectTrigger id="linked-request">
          <SelectValue placeholder={list.isLoading ? t('signoff.loadingEllipsis') : t('contracts.linkedRequest.pick')} />
        </SelectTrigger>
        <SelectContent>
          {options.length === 0 && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">{t('contracts.linkedRequest.none')}</div>
          )}
          {options.map((row) => (
            <SelectItem key={row.id} value={String(row.id)}>
              {row.code} — {row.title || row.template_name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {(list.isError || presetFailed) && (
        <p className="mt-1 text-xs text-muted-foreground">{t('contracts.linkedRequest.unavailable')}</p>
      )}
    </div>
  );
}

/** Строка «По заявке» в карточке документа: код заявки ссылкой. */
export function LinkedRequestBadge({ requestId }: { requestId: number | null }) {
  const { t } = useTranslation();
  const brief = useQuery({
    queryKey: ['contracts', 'linked-request', requestId],
    queryFn: () => contractsApi.getLinkedRequest(requestId as number).then((r) => r.data),
    enabled: requestId != null,
    retry: false,
  });
  if (requestId == null) return null;
  return (
    <Link to={`/requests/${requestId}`} className="text-primary hover:underline underline-offset-2">
      {brief.data ? `${brief.data.code} — ${brief.data.title || brief.data.template_name}` : `${t('contracts.linkedRequest.request')} #${requestId}`}
    </Link>
  );
}
