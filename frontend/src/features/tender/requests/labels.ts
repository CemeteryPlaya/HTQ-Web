/**
 * Подписи значений заявки на тендер: ключ i18n и запасной текст (в проекте
 * всюду `t(key, fallback)`).
 */
export interface LabelDef {
  key: string;
  fallback: string;
}

const l = (key: string, fallback: string): LabelDef => ({ key: `tender.requests.${key}`, fallback });

export const PURCHASE_TYPE_LABELS: Record<string, LabelDef> = {
  goods: l('purchaseTypeGoods', 'ТМЦ'),
  works: l('purchaseTypeWorks', 'Работы и услуги'),
};

export const PART_KIND_LABELS: Record<string, LabelDef> = {
  goods: l('partGoods', 'ТМЦ'),
  delivery: l('partDelivery', 'Доставка'),
  works: l('partWorks', 'СМР'),
};

export const ROLE_LABELS: Record<string, LabelDef> = {
  sn: l('roleSn', 'Снабженец'),
  pm: l('rolePm', 'Руководитель проекта'),
};

/** Статус заявки, в котором её ещё можно выбрать фильтром реестра. */
export const STATUS_FILTER = [
  'draft', 'in_approval', 'approved', 'rework', 'rejected', 'in_tender', 'handed_over', 'closed',
  'cancelled',
] as const;
