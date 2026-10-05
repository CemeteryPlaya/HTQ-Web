/**
 * Связь документа с альтернативой (B5.1, D-B51-3): сервер отдаёт её в
 * карточке счёта и договора полем `alternative` — основание нового документа
 * («Основание: альтернатива АП-…») и чем заменён исходный.
 */

export type SelectionDocType = 'invoice' | 'agreement';

export interface DocumentBrief {
  type: SelectionDocType;
  id: string;
  number: string;
}

export interface AlternativeLinks {
  basis: { offer_id: string; offer_number: string } | null;
  replaced_by: {
    offer_id: string;
    offer_number: string;
    result_type: SelectionDocType | null;
    result_id: string | null;
    result_number: string | null;
  } | null;
}

/** Ответ «Выбрать» (SelectAlternativeOffer): новый документ и черновик по остатку. */
export interface SelectionResult<Card> {
  invoice: Card;
  result: DocumentBrief;
  remainder: DocumentBrief | null;
  kpi_id: string;
}

const BASES: Record<SelectionDocType, string> = {
  invoice: '/bpp/invoices',
  agreement: '/bpp/agreements',
};

export const documentUrl = (type: SelectionDocType, id: string): string =>
  `${BASES[type]}/${id}`;

export const offerUrl = (offerId: string): string => `/bpp/alternatives/${offerId}`;
