/**
 * Добавление участника тендера (план §4.2):
 * - контрагент БЗО — поиском (`counterparties?q=`); пригласить можно только
 *   действующего (иначе сервер ответит 422 `E-TND-02`, поэтому прочие видны,
 *   но закрыты). Адрес — действующий контакт поставщика (`contacts`) или
 *   e-mail карточки контрагента (тогда `contact_id` не передаётся);
 * - потенциальный поставщик — из справочника `/tender/prospects`.
 * Ответ после публикации несёт `link` — его показывает карточка.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { useIdempotentAction } from '@/features/bpp/core/useIdempotentAction';

import { prospectKeys, prospectsApi } from '../prospects/api';
import {
  tenderKeys, tendersApi, type Counterparty, type InvitationInput,
} from './api';

const SEARCH_DELAY_MS = 250;
/** Выбор «e-mail из карточки контрагента» — без `contact_id`. */
const CARD_EMAIL = '__card__';

function useDebounced(value: string): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [value]);
  return debounced;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Запрос приглашения; ошибку показывает вызывающий. */
  onInvite: (key: string, body: InvitationInput) => Promise<unknown>;
  onError: (error: unknown) => void;
}

export function AddParticipantDialog({ open, onOpenChange, onInvite, onError }: Props) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'counterparty' | 'prospect'>('counterparty');
  const [search, setSearch] = useState('');
  const [picked, setPicked] = useState<Counterparty | null>(null);
  const [contact, setContact] = useState('');
  const [prospect, setProspect] = useState('');
  const query = useDebounced(search);

  const counterparties = useQuery({
    queryKey: tenderKeys.counterparties(query),
    queryFn: () => tendersApi.counterparties(query),
    enabled: open && mode === 'counterparty' && query.length >= 2 && !picked,
  });
  const contacts = useQuery({
    queryKey: tenderKeys.contacts(picked?.id ?? ''),
    queryFn: () => tendersApi.contacts(picked!.id),
    enabled: open && Boolean(picked),
  });
  const prospects = useQuery({
    queryKey: prospectKeys.list(query),
    queryFn: () => prospectsApi.list(query),
    enabled: open && mode === 'prospect',
  });

  const body: InvitationInput | null = mode === 'prospect'
    ? (prospect ? { prospect_id: prospect } : null)
    : picked && contact
      ? (contact === CARD_EMAIL ? { counterparty_id: picked.id } : { counterparty_id: picked.id, contact_id: contact })
      : null;
  const action = useIdempotentAction((key) => onInvite(key, body as InvitationInput));

  const reset = () => {
    setSearch('');
    setPicked(null);
    setContact('');
    setProspect('');
  };
  const switchMode = (next: 'counterparty' | 'prospect') => {
    setMode(next);
    reset();
  };

  const activeContacts = (contacts.data ?? []).filter((row) => row.is_active);
  const cardEmail = picked?.email && !activeContacts.some((row) => row.email === picked.email)
    ? picked.email : '';

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!action.pending) { onOpenChange(next); if (!next) reset(); } }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('tender.tenders.addParticipant', 'Добавить участника')}</DialogTitle>
          <DialogDescription>
            {t('tender.tenders.addParticipantHint',
              'Контрагент из реестра БЗО или потенциальный поставщик из справочника.')}
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2">
          {([
            ['counterparty', t('tender.tenders.modeCounterparty', 'Контрагент')],
            ['prospect', t('tender.tenders.modeProspect', 'Потенциальный поставщик')],
          ] as const).map(([value, label]) => (
            <Button
              key={value} type="button" size="sm"
              variant={mode === value ? 'default' : 'outline'}
              aria-pressed={mode === value}
              onClick={() => switchMode(value)}
            >
              {label}
            </Button>
          ))}
        </div>

        {mode === 'counterparty' && !picked && (
          <div className="space-y-2">
            <Label htmlFor="tender-participant-search">
              {t('tender.tenders.searchCounterparty', 'Поиск контрагента')}
            </Label>
            <Input
              id="tender-participant-search" value={search}
              placeholder={t('tender.tenders.searchCounterpartyHint', 'Название или БИН, от 2 знаков')}
              onChange={(event) => setSearch(event.target.value)}
            />
            {counterparties.isFetching && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            {query.length >= 2 && counterparties.data?.length === 0 && (
              <p className="text-sm text-muted-foreground">
                {t('tender.tenders.nothingFound', 'Ничего не найдено')}
              </p>
            )}
            <div className="flex flex-col gap-1">
              {(counterparties.data ?? []).map((row) => {
                const active = row.status === 'active';
                return (
                  <Button
                    key={row.id} type="button" variant="outline" disabled={!active}
                    className="h-auto justify-start whitespace-normal py-2 text-left"
                    onClick={() => setPicked(row)}
                  >
                    <span>
                      <span className="font-medium">{row.name}</span>
                      {row.reg_number && <span className="text-muted-foreground"> · {row.reg_number}</span>}
                      {!active && (
                        <span className="block text-xs text-muted-foreground">
                          {t('tender.tenders.counterpartyInactive', 'Не действует — пригласить нельзя')}
                        </span>
                      )}
                    </span>
                  </Button>
                );
              })}
            </div>
          </div>
        )}

        {mode === 'counterparty' && picked && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="font-medium">{picked.name}</span>
              <Button type="button" size="sm" variant="ghost" onClick={() => { setPicked(null); setContact(''); }}>
                {t('tender.tenders.otherCounterparty', 'Другой контрагент')}
              </Button>
            </div>
            <Label>{t('tender.tenders.pickEmail', 'Куда отправить ссылку')}</Label>
            {contacts.isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : activeContacts.length === 0 && !cardEmail ? (
              <p className="text-sm text-muted-foreground">
                {t('tender.tenders.noEmails', 'У контрагента нет e-mail. Добавьте контакт в карточке контрагента.')}
              </p>
            ) : (
              <RadioGroup value={contact} onValueChange={setContact} className="grid gap-1.5">
                {activeContacts.map((row) => (
                  <label key={row.id} className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value={row.id} />
                    <span>
                      {row.email}
                      {row.name && <span className="text-muted-foreground"> — {row.name}</span>}
                    </span>
                  </label>
                ))}
                {cardEmail && (
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value={CARD_EMAIL} />
                    <span>
                      {cardEmail}
                      <span className="text-muted-foreground">
                        {' — '}{t('tender.tenders.cardEmail', 'из карточки контрагента')}
                      </span>
                    </span>
                  </label>
                )}
              </RadioGroup>
            )}
          </div>
        )}

        {mode === 'prospect' && (
          <div className="space-y-2">
            <Label htmlFor="tender-prospect-search">{t('tender.tenders.searchProspect', 'Поиск поставщика')}</Label>
            <Input id="tender-prospect-search" value={search} onChange={(event) => setSearch(event.target.value)} />
            {prospects.data?.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('tender.tenders.noProspects', 'Не нашли — заведите поставщика в справочнике «Потенциальные поставщики».')}
              </p>
            ) : (
              <RadioGroup value={prospect} onValueChange={setProspect} className="grid gap-1.5">
                {(prospects.data ?? []).map((row) => (
                  <label key={row.id} className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value={row.id} />
                    <span>
                      {row.name}
                      <span className="text-muted-foreground"> · {row.email}</span>
                    </span>
                  </label>
                ))}
              </RadioGroup>
            )}
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="outline" disabled={action.pending} onClick={() => { onOpenChange(false); reset(); }}>
            {t('tender.common.cancel', 'Отмена')}
          </Button>
          <Button
            type="button" disabled={!body || action.pending}
            onClick={() => action.run().then(() => { onOpenChange(false); reset(); }, onError)}
          >
            {action.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('tender.tenders.invite', 'Пригласить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
