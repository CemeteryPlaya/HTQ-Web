/** Builder Step 4 — More (advanced settings, Lark screenshot 13). Edits
 *  template.config_json.settings; autosaved by the wizard like Basic Info.
 *  The UI is complete here; runtime enforcement of each toggle (revoke/modify
 *  windows, deduplication, batch, efficiency exclusion) is wired separately in
 *  the backend. */

import type { ReactNode } from 'react';

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

import type { TemplateSettings } from '@/features/requests/types';

interface Props {
  value: TemplateSettings;
  onChange: (patch: Partial<TemplateSettings>) => void;
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex items-start gap-3">
      {children}
      <span>
        <span className="text-sm text-foreground">{label}</span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </label>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-3 border-b pb-5 last:border-b-0 md:grid-cols-[220px_minmax(0,1fr)]">
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

export function MoreStep({ value: s, onChange }: Props) {
  const bool = (k: keyof TemplateSettings) => Boolean(s[k]);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Section title="Права заявителя">
        <Row label="Разрешить отзыв запроса, ожидающего согласования"
             hint="Запрос можно отозвать, даже если он прошёл первый шаг.">
          <Checkbox checked={bool('allow_revoke_pending')} onCheckedChange={(v) => onChange({ allow_revoke_pending: Boolean(v) })} />
        </Row>
        <div className="flex items-center gap-2">
          <Checkbox checked={bool('allow_revoke_within_days')} onCheckedChange={(v) => onChange({ allow_revoke_within_days: Boolean(v) })} />
          <span className="text-sm">Разрешить отзыв в течение</span>
          <Input type="number" className="h-8 w-20" value={s.revoke_within_days ?? 31}
                 onChange={(e) => onChange({ revoke_within_days: Number(e.target.value) })} disabled={!s.allow_revoke_within_days} />
          <span className="text-sm">дней</span>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox checked={bool('allow_modify_approved')} onCheckedChange={(v) => onChange({ allow_modify_approved: Boolean(v) })} />
          <span className="text-sm">Разрешить правку одобренного в течение</span>
          <Input type="number" className="h-8 w-20" value={s.modify_within_days ?? 31}
                 onChange={(e) => onChange({ modify_within_days: Number(e.target.value) })} disabled={!s.allow_modify_approved} />
          <span className="text-sm">дней</span>
        </div>
        <Row label="Разрешить делегированную подачу"
             hint="Делегат и делегирующий должны иметь одинаковые права на согласование.">
          <Checkbox checked={bool('allow_delegate_submission')} onCheckedChange={(v) => onChange({ allow_delegate_submission: Boolean(v) })} />
        </Row>
      </Section>

      <Section title="Настройки согласующего">
        <Row label="Разрешить пакетную обработку"
             hint="Согласующие смогут обрабатывать несколько задач сразу.">
          <Checkbox checked={bool('allow_batch')} onCheckedChange={(v) => onChange({ allow_batch: Boolean(v) })} />
        </Row>
        <Row label="Разрешить согласующим отзывать своё решение"
             hint="Пока следующий согласующий ещё не рассмотрел запрос.">
          <Checkbox checked={bool('allow_recall_decision')} onCheckedChange={(v) => onChange({ allow_recall_decision: Boolean(v) })} />
        </Row>
        <Row label="Показывать статус «Мгновенное согласование»"
             hint="Если запрос рассмотрен менее чем за 3 секунды.">
          <Checkbox checked={bool('show_instant_approval')} onCheckedChange={(v) => onChange({ show_instant_approval: Boolean(v) })} />
        </Row>
        <Row label="Быстрое согласование на карточке"
             hint="Согласовать прямо в списке/уведомлении, не открывая деталь.">
          <Checkbox checked={bool('quick_approval_on_cards')} onCheckedChange={(v) => onChange({ quick_approval_on_cards: Boolean(v) })} />
        </Row>
      </Section>

      <Section title="Дедупликация согласующих">
        <RadioGroup value={s.dedup ?? 'once_auto'} onValueChange={(v) => onChange({ dedup: v as TemplateSettings['dedup'] })}>
          <Row label="Согласующему достаточно одобрить один раз — последующие шаги авто-одобряются">
            <RadioGroupItem value="once_auto" />
          </Row>
          <Row label="Авто-одобрять только на подряд идущих шагах">
            <RadioGroupItem value="consecutive_auto" />
          </Row>
          <Row label="Без авто-одобрения — все шаги требуют согласования">
            <RadioGroupItem value="none" />
          </Row>
        </RadioGroup>
      </Section>

      <Section title="Уведомления">
        <RadioGroup value={s.notification_mode ?? 'default'} onValueChange={(v) => onChange({ notification_mode: v as TemplateSettings['notification_mode'] })}>
          <Row label="По умолчанию — показывать только первые три поля"><RadioGroupItem value="default" /></Row>
          <Row label="Настраиваемые"><RadioGroupItem value="custom" /></Row>
        </RadioGroup>
      </Section>

      <Section title="Шаблон печати">
        <RadioGroup value={s.print_mode ?? 'default'} onValueChange={(v) => onChange({ print_mode: v as TemplateSettings['print_mode'] })}>
          <Row label="По умолчанию"><RadioGroupItem value="default" /></Row>
          <Row label="Настраиваемый"><RadioGroupItem value="custom" /></Row>
        </RadioGroup>
      </Section>

      <Section title="Передача">
        <Row label="Только связанные с запросом лица могут его пересылать"
             hint="Пересылать можно только заявителям, согласующим и получателям копий.">
          <Checkbox checked={bool('only_related_can_forward')} onCheckedChange={(v) => onChange({ only_related_can_forward: Boolean(v) })} />
        </Row>
      </Section>

      <Section title="Статистика эффективности">
        <Row label="Не учитывать данные этого процесса в статистике эффективности"
             hint="Диагностика эффективности не будет считать время по этим шагам.">
          <Checkbox checked={bool('exclude_efficiency')} onCheckedChange={(v) => onChange({ exclude_efficiency: Boolean(v) })} />
        </Row>
      </Section>
    </div>
  );
}
