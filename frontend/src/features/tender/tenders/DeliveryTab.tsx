/**
 * Вкладка «Поставка» карточки тендера (TND-040…TND-042; спека этапа 5,
 * §3 T5.5). Появляется после передачи выбора в БЗО.
 *
 * - По поставщику: стадия (считает сервер по документам БЗО и приёмкам),
 *   сумма и оплачено, документы БЗО ссылками (заменённый альтернативой —
 *   со ссылкой на замену), строки выбора: выбрано / принято.
 * - «Отметить получение» — у автора тендера (`receipt`) со стадии «В
 *   поставке»: товар отгружен, раньше принимать нечего.
 * - Приёмки поставщика: «Оригиналы переданы» (дата и кому — уходят на счёт
 *   БЗО), отмена с причиной от 10 символов, сканы и фото — панель файлов
 *   владельца `tender.receipt` (закрывающие видны не всем, T-17).
 */
import { useCallback, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { PackageCheck } from 'lucide-react';

import { FilesPanel } from '@/components/files/FilesPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { DocumentActionButton, type BppDocumentAction } from '@/features/bpp/core/DocumentActionButton';
import { StatusBadge } from '@/features/bpp/core/StatusBadge';
import { formatDate, formatMoney } from '@/features/bpp/format';
import { todayIso } from '@/lib/dates';

import { reportFormError } from '../core/fieldErrors';
import { tenderKeys, tendersApi } from './api';
import {
  RECEIPT_OWNER, RECEIVABLE, bppDocumentHref, remainingOf, type DeliverySupplier, type Receipt,
} from './delivery';
import { ReceiptDialog } from './ReceiptDialog';

const REASON_MIN = 10;
const noop = () => undefined;

interface Props {
  tenderId: string;
  /** Автор тендера может отмечать приёмку (`receipt` в действиях карточки). */
  canReceive: boolean;
  onChanged: () => void;
}

export function DeliveryTab({ tenderId, canReceive, onChanged }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const delivery = useQuery({ queryKey: tenderKeys.delivery(tenderId), queryFn: () => tendersApi.delivery(tenderId) });
  const receipts = useQuery({ queryKey: tenderKeys.receipts(tenderId), queryFn: () => tendersApi.receipts(tenderId) });
  const [receiving, setReceiving] = useState<DeliverySupplier | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const onPendingChange = useCallback((key: string, pending: boolean) => {
    setBusy((current) => (current[key] === pending ? current : { ...current, [key]: pending }));
  }, []);

  if (delivery.isLoading || receipts.isLoading) return <Skeleton className="h-48 w-full" />;
  if (!delivery.data) {
    return <p className="text-sm text-muted-foreground">{t('tender.delivery.loadFailed', 'Не удалось загрузить поставку.')}</p>;
  }

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: tenderKeys.delivery(tenderId) });
    void queryClient.invalidateQueries({ queryKey: tenderKeys.receipts(tenderId) });
    onChanged();
  };
  const fail = (failure: unknown) => reportFormError(
    failure,
    t('tender.tenders.actionFailed', 'Не удалось выполнить действие'),
    t('tender.common.invalidFormatToast', 'Сервер не принял формат некоторых полей — проверьте выделенные поля.'),
  );

  if (delivery.data.suppliers.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('tender.delivery.empty', 'Поставщиков по выбору нет.')}</p>;
  }

  return (
    <section className="space-y-4" data-testid="tender-delivery">
      {delivery.data.suppliers.map((supplier) => (
        <SupplierCard
          key={supplier.invitation_id}
          supplier={supplier}
          receipts={(receipts.data ?? []).filter((row) => row.invitation_id === supplier.invitation_id)}
          canReceive={canReceive}
          busy={busy}
          onPendingChange={onPendingChange}
          onReceive={() => setReceiving(supplier)}
          onOriginals={async (receipt, body) => {
            try {
              await tendersApi.setOriginals(tenderId, receipt.id, body);
              refresh();
              toast.success(t('tender.delivery.originalsSaved', 'Отметка об оригиналах сохранена'));
            } catch (failure) {
              fail(failure);
              throw failure;
            }
          }}
          cancelAction={(receipt) => ({
            label: t('tender.delivery.cancelReceipt', 'Отменить приёмку'),
            variant: 'outline',
            confirm: {
              title: t('tender.delivery.cancelConfirm', 'Отменить приёмку от {{date}}?', { date: formatDate(receipt.received_at) }),
              description: t('tender.delivery.cancelHint', 'Принятое количество вернётся к остатку, отметка на счёте БЗО пересчитается.'),
              commentMin: REASON_MIN,
            },
            run: async (key, comment) => {
              await tendersApi.cancelReceipt(tenderId, receipt.id, key, comment ?? '');
              refresh();
            },
          })}
        />
      ))}
      {receiving && (
        <ReceiptDialog
          supplier={receiving}
          onOpenChange={(open) => { if (!open) setReceiving(null); }}
          onError={fail}
          onSave={async (key, body) => {
            await tendersApi.addReceipt(tenderId, key, body);
            refresh();
            toast.success(t('tender.delivery.receiptSaved', 'Приёмка сохранена'));
          }}
        />
      )}
    </section>
  );
}

function stageLabel(stage: string, t: (key: string, fallback: string) => string): string {
  switch (stage) {
    case 'awaiting_documents': return t('tender.delivery.stage.awaiting_documents', 'Ждёт документов в БЗО');
    case 'awaiting_shipment_payment': return t('tender.delivery.stage.awaiting_shipment_payment', 'Ждёт оплаты до отгрузки');
    case 'in_delivery': return t('tender.delivery.stage.in_delivery', 'В поставке');
    case 'partially_received': return t('tender.delivery.stage.partially_received', 'Принято частично');
    case 'received': return t('tender.delivery.stage.received', 'Принято');
    case 'awaiting_final_payment': return t('tender.delivery.stage.awaiting_final_payment', 'Ждёт оплаты остатка');
    case 'closed': return t('tender.delivery.stage.closed', 'Закрыто');
    default: return stage;
  }
}

function SupplierCard({
  supplier, receipts, canReceive, busy, onPendingChange, onReceive, onOriginals, cancelAction,
}: {
  supplier: DeliverySupplier;
  receipts: Receipt[];
  canReceive: boolean;
  busy: Record<string, boolean>;
  onPendingChange: (key: string, pending: boolean) => void;
  onReceive: () => void;
  onOriginals: (receipt: Receipt, body: { originals_at: string | null; originals_to: string }) => Promise<void>;
  cancelAction: (receipt: Receipt) => BppDocumentAction;
}) {
  const { t } = useTranslation();
  const names = new Map(supplier.awards.map((award) => [award.award_id, award.name]));
  const leftToReceive = supplier.awards.some((award) => award.needs_receipt && remainingOf(award) > 0);
  const mayReceive = canReceive && RECEIVABLE.includes(supplier.stage) && leftToReceive;
  return (
    <article className="space-y-3 rounded-2xl border bg-card p-4" data-testid={`delivery-${supplier.invitation_id}`}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h4 className="font-semibold">{supplier.supplier}</h4>
          <Badge variant="outline">{stageLabel(supplier.stage, t)}</Badge>
        </div>
        <span className="text-sm text-muted-foreground">
          {t('tender.delivery.paidOf', 'оплачено {{paid}} из {{total}}', {
            paid: formatMoney(supplier.paid, supplier.currency_code),
            total: formatMoney(supplier.total, supplier.currency_code),
          })}
        </span>
      </header>

      {supplier.documents.length > 0 && (
        <ul className="space-y-1 text-sm">
          {supplier.documents.map((doc) => (
            <li key={doc.doc_id} className="flex flex-wrap items-center gap-2">
              <Link to={bppDocumentHref(doc.doc_type, doc.doc_id)} className="text-primary hover:underline">{doc.number}</Link>
              <StatusBadge kind={doc.doc_type === 'agreement' ? 'contract' : 'invoice'} status={doc.status} />
              {doc.amount && <span className="text-muted-foreground">{formatMoney(doc.amount, supplier.currency_code)}</span>}
              {doc.replaced_by && (
                <span className="text-muted-foreground">
                  {t('tender.delivery.replacedBy', 'заменён по {{offer}}:', { offer: doc.replaced_by.offer_number })}{' '}
                  <Link to={bppDocumentHref(doc.replaced_by.doc_type, doc.replaced_by.doc_id)} className="text-primary hover:underline">
                    {doc.replaced_by.number}
                  </Link>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      <ul className="space-y-0.5 text-sm">
        {supplier.awards.map((award) => (
          <li key={award.award_id}>
            {award.name}: {award.needs_receipt
              ? t('tender.delivery.receivedOf', 'принято {{received}} из {{qty}}', { received: award.received, qty: award.qty })
              : t('tender.delivery.withGoods', 'принимается вместе с товаром')}
          </li>
        ))}
      </ul>

      {mayReceive && (
        <Button type="button" onClick={onReceive}>
          <PackageCheck className="mr-1.5 h-4 w-4" />
          {t('tender.delivery.receive', 'Отметить получение')}
        </Button>
      )}

      {receipts.length > 0 && (
        <div className="space-y-2">
          <h5 className="text-sm font-semibold">{t('tender.delivery.receipts', 'Приёмки')}</h5>
          {receipts.map((receipt) => (
            <ReceiptRow
              key={receipt.id} receipt={receipt} names={names} canEdit={canReceive}
              busy={busy} onPendingChange={onPendingChange}
              onOriginals={(body) => onOriginals(receipt, body)}
              cancel={cancelAction(receipt)}
            />
          ))}
        </div>
      )}
    </article>
  );
}

function ReceiptRow({ receipt, names, canEdit, busy, onPendingChange, onOriginals, cancel }: {
  receipt: Receipt;
  names: Map<string, string>;
  canEdit: boolean;
  busy: Record<string, boolean>;
  onPendingChange: (key: string, pending: boolean) => void;
  onOriginals: (body: { originals_at: string | null; originals_to: string }) => Promise<void>;
  cancel: BppDocumentAction;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [at, setAt] = useState(receipt.originals_at ?? todayIso());
  const [to, setTo] = useState(receipt.originals_to);
  const [saving, setSaving] = useState(false);
  const cancelled = Boolean(receipt.cancelled_at);
  const key = `cancel:${receipt.id}`;
  return (
    <div className={`space-y-2 rounded-xl border p-3 text-sm ${cancelled ? 'opacity-60' : ''}`} data-testid={`receipt-${receipt.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          {receipt.kind === 'works'
            ? t('tender.delivery.worksAt', 'Работы приняты {{date}}', { date: formatDate(receipt.received_at) })
            : t('tender.delivery.goodsAt', 'Товар получен {{date}}', { date: formatDate(receipt.received_at) })}
          {cancelled && ` · ${t('tender.delivery.cancelled', 'отменена')}`}
        </span>
        {canEdit && !cancelled && (
          <div className="flex flex-wrap gap-1.5">
            <Button type="button" size="sm" variant="outline" onClick={() => setEditing((value) => !value)}>
              {t('tender.delivery.originalsButton', 'Оригиналы переданы')}
            </Button>
            <DocumentActionButton
              actionKey={key} action={cancel} disabled={Object.values(busy).some(Boolean) && !busy[key]}
              onPendingChange={onPendingChange} onDone={noop}
            />
          </div>
        )}
      </div>
      <ul className="text-muted-foreground">
        {receipt.lines.map((line) => <li key={line.award_id}>{names.get(line.award_id) ?? line.award_id}: {line.qty}</li>)}
      </ul>
      {receipt.comment && <p className="whitespace-pre-wrap">{receipt.comment}</p>}
      {receipt.originals_at && (
        <p>
          {t('tender.delivery.originalsDone', 'Оригиналы переданы {{date}}', { date: formatDate(receipt.originals_at) })}
          {receipt.originals_to ? ` — ${receipt.originals_to}` : ''}
        </p>
      )}
      {editing && (
        <div className="grid gap-2 sm:grid-cols-[10rem_1fr_auto] sm:items-end">
          <div className="space-y-1">
            <Label htmlFor={`originals-at-${receipt.id}`}>{t('tender.delivery.originalsAt', 'Оригиналы переданы')}</Label>
            <DateInput id={`originals-at-${receipt.id}`} value={at} max={todayIso()} onChange={setAt} />
          </div>
          <div className="space-y-1">
            <Label htmlFor={`originals-to-${receipt.id}`}>{t('tender.delivery.originalsTo', 'Кому')}</Label>
            <Input id={`originals-to-${receipt.id}`} value={to} maxLength={255} onChange={(event) => setTo(event.target.value)} />
          </div>
          <Button
            type="button" size="sm" disabled={saving || !at}
            onClick={() => {
              setSaving(true);
              onOriginals({ originals_at: at, originals_to: to.trim() })
                .then(() => setEditing(false), () => undefined)
                .finally(() => setSaving(false));
            }}
          >
            {t('tender.tenders.save', 'Сохранить')}
          </Button>
        </div>
      )}
      {!cancelled && (
        <FilesPanel ownerType={RECEIPT_OWNER} ownerId={receipt.id}
          title={t('tender.delivery.files', 'Сканы и фото')} readOnly={!canEdit} />
      )}
    </div>
  );
}

export default DeliveryTab;
