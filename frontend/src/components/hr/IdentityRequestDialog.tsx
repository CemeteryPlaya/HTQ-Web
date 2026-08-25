import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { AlertTriangle } from 'lucide-react';

import {
  decideIdentityRequest,
  fetchIdentityRequest,
  type IdentityDecision,
} from '@/api/identity';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { errorDetail } from '@/lib/apiError';

/** Человеческие названия полей. Ключи — те же, что в FIELD_MAP на бэкенде. */
const FIELD_LABEL: Record<string, string> = {
  first_name: 'Имя',
  last_name: 'Фамилия',
  middle_name: 'Отчество',
  phone: 'Телефон',
  bio: 'О себе',
  avatar_url: 'Аватар',
};

interface Props {
  requestId: number | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Окно подтверждения заявки на изменение профиля.
 *
 * Показывает обе стороны и, если значение аккаунта уехало с момента подачи, —
 * третью колонку «было при подаче». Это единственный настоящий конфликт в
 * схеме: подтверждающий не должен вслепую откатить чужую свежую правку.
 *
 * «Применить» неактивна, пока не решена каждая строка: частичное применение
 * оставило бы заявку подвешенной, а её смысл в том, чтобы закрыться целиком.
 */
export function IdentityRequestDialog({ requestId, onOpenChange }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [decisions, setDecisions] = useState<Record<string, IdentityDecision>>({});
  const [note, setNote] = useState('');

  const { data: request } = useQuery({
    queryKey: ['identity-request', requestId],
    queryFn: () => fetchIdentityRequest(requestId!),
    enabled: requestId !== null,
  });

  // Новая заявка — чистое состояние: решения от предыдущей не должны
  // «протечь» в другую карточку.
  useEffect(() => {
    setDecisions({});
    setNote('');
  }, [requestId]);

  const decide = useMutation({
    mutationFn: () => decideIdentityRequest(requestId!, decisions, note || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['identity-requests'] });
      queryClient.invalidateQueries({ queryKey: ['hr-employees'] });
      onOpenChange(false);
    },
    onError: (err: unknown) => toast.error(
      errorDetail(err) ?? t('hr.pages.identity.decideError', 'Не удалось применить решение'),
    ),
  });

  const fields = request?.fields ?? [];
  const allDecided = fields.length > 0 && fields.every((f) => decisions[f.field]);

  return (
    <Dialog open={requestId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('hr.pages.identity.dialogTitle', 'Изменение данных аккаунта')}
            {request ? ` — ${request.employee_name}` : ''}
          </DialogTitle>
        </DialogHeader>

        {request?.source === 'nightly' && (
          <p className="text-sm text-muted-foreground">
            {t(
              'hr.pages.identity.nightlyHint',
              'Найдено ночной сверкой: значение попало в карточку в обход API. Копия уже восстановлена из аккаунта — решите, нужно ли перенести найденное значение в аккаунт.',
            )}
          </p>
        )}

        <div className="grid gap-3">
          {fields.map((field) => (
            <div key={field.field} className="rounded-md border p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="font-medium">{FIELD_LABEL[field.field] ?? field.field}</span>
                {field.is_stale && (
                  <Badge variant="destructive" className="gap-1">
                    <AlertTriangle className="h-3 w-3" />
                    {t('hr.pages.identity.stale', 'Аккаунт изменился')}
                  </Badge>
                )}
              </div>

              <div className={cn('grid gap-3', field.is_stale ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}>
                {field.is_stale && (
                  <div className="text-sm">
                    <div className="text-xs text-muted-foreground">
                      {t('hr.pages.identity.atRequest', 'Было при подаче')}
                    </div>
                    <div className="break-words">{field.account_value_at_request || '—'}</div>
                  </div>
                )}
                <div className="text-sm">
                  <div className="text-xs text-muted-foreground">
                    {t('hr.pages.identity.accountNow', 'Сейчас в аккаунте')}
                  </div>
                  <div className="break-words">{field.account_value_now || '—'}</div>
                </div>
                <div className="text-sm">
                  <div className="text-xs text-muted-foreground">
                    {t('hr.pages.identity.proposed', 'Предложено кадрами')}
                  </div>
                  <div className="break-words">{field.proposed_value || '—'}</div>
                </div>
              </div>

              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  variant={decisions[field.field] === 'apply' ? 'default' : 'outline'}
                  onClick={() => setDecisions((prev) => ({ ...prev, [field.field]: 'apply' }))}
                >
                  {t('hr.pages.identity.apply', 'Перенести в аккаунт')}
                </Button>
                <Button
                  size="sm"
                  variant={decisions[field.field] === 'reject' ? 'default' : 'outline'}
                  onClick={() => setDecisions((prev) => ({ ...prev, [field.field]: 'reject' }))}
                >
                  {t('hr.pages.identity.reject', 'Оставить как есть')}
                </Button>
              </div>
            </div>
          ))}
        </div>

        <Textarea
          value={note}
          placeholder={t('hr.pages.identity.notePlaceholder', 'Комментарий к решению (необязательно)')}
          onChange={(e) => setNote(e.target.value)}
        />

        <div className="flex items-center justify-end gap-2">
          {!allDecided && (
            <span className="text-xs text-muted-foreground">
              {t('hr.pages.identity.decideAll', 'Решите каждую строку')}
            </span>
          )}
          <Button onClick={() => decide.mutate()} disabled={!allDecided || decide.isPending}>
            {t('hr.pages.identity.submit', 'Применить решение')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
