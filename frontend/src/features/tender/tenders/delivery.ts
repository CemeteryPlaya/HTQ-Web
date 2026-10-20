/**
 * Передача в БЗО, стадии поставки и приёмка (этап 5; ручки
 * `tenders/<id>/handover`, `…/delivery`, `…/receipts`; спека этапа 5, §3 T5.5).
 *
 * Стадию поставщика считает сервер по документам БЗО и приёмкам; здесь —
 * только подписи и то, что из стадии следует для кнопок.
 */

export type DeliveryStage =
  | 'awaiting_documents' | 'awaiting_shipment_payment' | 'in_delivery'
  | 'partially_received' | 'received' | 'awaiting_final_payment' | 'closed';

export interface DeliveryDocument {
  doc_type: 'invoice' | 'agreement' | string;
  doc_id: string;
  number: string;
  status: string;
  amount: string | null;
  paid_amount: string;
  received_at: string | null;
  replaced_by: { doc_type: string; doc_id: string; number: string; offer_number: string } | null;
}

export interface DeliveryAward {
  award_id: string;
  /** `line` — позиция; `delivery`, `works` — доставка и СМР. */
  kind: 'line' | 'delivery' | 'works' | string;
  name: string;
  qty: string;
  received: string;
  needs_receipt: boolean;
}

export interface DeliverySupplier {
  invitation_id: string;
  supplier: string;
  currency_code: string;
  stage: DeliveryStage | string;
  total: string;
  paid: string;
  shipment_share: string;
  documents: DeliveryDocument[];
  awards: DeliveryAward[];
}

export interface Delivery {
  tender_id: string;
  status: string;
  suppliers: DeliverySupplier[];
}

export type ReceiptKind = 'goods' | 'works';

export interface Receipt {
  id: string;
  invitation_id: string;
  received_at: string;
  kind: ReceiptKind | string;
  comment: string;
  originals_at: string | null;
  originals_to: string;
  version: number;
  cancelled_at: string | null;
  lines: { award_id: string; qty: string }[];
}

export interface ReceiptInput {
  invitation_id: string;
  received_at: string;
  kind: ReceiptKind;
  lines: { award_id: string; qty: string }[];
  comment?: string;
  originals_at?: string | null;
  originals_to?: string;
}

export interface HandoverResult {
  tender_id: string;
  status: string;
  documents: { invitation_id: string; supplier: string; part_id: string; doc_type: string; doc_id: string; number: string }[];
}

/** Владелец файлов приёмки в подсистеме файлов (сканы закрывающих, фото). */
export const RECEIPT_OWNER = 'tender.receipt';

/** Стадии, с которых закупщик отмечает получение (товар отгружен). */
export const RECEIVABLE: string[] = [
  'in_delivery', 'partially_received', 'received', 'awaiting_final_payment',
];

/** Карточка документа БЗО: счёт или договор. */
export const bppDocumentHref = (docType: string, docId: string) =>
  (docType === 'agreement' ? `/bpp/agreements/${docId}` : `/bpp/invoices/${docId}`);

/** Остаток к приёмке строки выбора: выбрано − принято, не меньше нуля. */
export function remainingOf(award: DeliveryAward): number {
  return Math.max(Number(award.qty) - Number(award.received), 0);
}
