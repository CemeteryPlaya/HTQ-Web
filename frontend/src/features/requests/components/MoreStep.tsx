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
import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
  const bool = (k: keyof TemplateSettings) => Boolean(s[k]);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <Section title={t('requests.more.initiatorRights')}>
        <Row label={t('requests.more.allowWithdraw')}
             hint={t('requests.more.allowWithdrawHint')}>
          <Checkbox checked={bool('allow_revoke_pending')} onCheckedChange={(v) => onChange({ allow_revoke_pending: Boolean(v) })} />
        </Row>
        <div className="flex items-center gap-2">
          <Checkbox checked={bool('allow_revoke_within_days')} onCheckedChange={(v) => onChange({ allow_revoke_within_days: Boolean(v) })} />
          <span className="text-sm">{t('requests.more.withdrawWithin')}</span>
          <Input type="number" className="h-8 w-20" value={s.revoke_within_days ?? 31}
                 onChange={(e) => onChange({ revoke_within_days: Number(e.target.value) })} disabled={!s.allow_revoke_within_days} />
          <span className="text-sm">{t('requests.more.days')}</span>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox checked={bool('allow_modify_approved')} onCheckedChange={(v) => onChange({ allow_modify_approved: Boolean(v) })} />
          <span className="text-sm">{t('requests.more.editApprovedWithin')}</span>
          <Input type="number" className="h-8 w-20" value={s.modify_within_days ?? 31}
                 onChange={(e) => onChange({ modify_within_days: Number(e.target.value) })} disabled={!s.allow_modify_approved} />
          <span className="text-sm">{t('requests.more.days')}</span>
        </div>
        <Row label={t('requests.more.allowDelegated')}
             hint={t('requests.more.allowDelegatedHint')}>
          <Checkbox checked={bool('allow_delegate_submission')} onCheckedChange={(v) => onChange({ allow_delegate_submission: Boolean(v) })} />
        </Row>
      </Section>

      <Section title={t('requests.more.approverSettings')}>
        <Row label={t('requests.more.allowBatch')}
             hint={t('requests.more.allowBatchHint')}>
          <Checkbox checked={bool('allow_batch')} onCheckedChange={(v) => onChange({ allow_batch: Boolean(v) })} />
        </Row>
        <Row label={t('requests.more.allowUndo')}
             hint={t('requests.more.allowUndoHint')}>
          <Checkbox checked={bool('allow_recall_decision')} onCheckedChange={(v) => onChange({ allow_recall_decision: Boolean(v) })} />
        </Row>
        <Row label={t('requests.more.instantBadge')}
             hint={t('requests.more.instantBadgeHint')}>
          <Checkbox checked={bool('show_instant_approval')} onCheckedChange={(v) => onChange({ show_instant_approval: Boolean(v) })} />
        </Row>
        <Row label={t('requests.more.quickApproval')}
             hint={t('requests.more.quickApprovalHint')}>
          <Checkbox checked={bool('quick_approval_on_cards')} onCheckedChange={(v) => onChange({ quick_approval_on_cards: Boolean(v) })} />
        </Row>
      </Section>

      <Section title={t('requests.more.dedup')}>
        <RadioGroup value={s.dedup ?? 'once_auto'} onValueChange={(v) => onChange({ dedup: v as TemplateSettings['dedup'] })}>
          <Row label={t('requests.more.dedupOnce')}>
            <RadioGroupItem value="once_auto" />
          </Row>
          <Row label={t('requests.more.dedupConsecutive')}>
            <RadioGroupItem value="consecutive_auto" />
          </Row>
          <Row label={t('requests.more.dedupNone')}>
            <RadioGroupItem value="none" />
          </Row>
        </RadioGroup>
      </Section>

      <Section title={t('notifications.title')}>
        <RadioGroup value={s.notification_mode ?? 'default'} onValueChange={(v) => onChange({ notification_mode: v as TemplateSettings['notification_mode'] })}>
          <Row label={t('requests.more.notifyDefault')}><RadioGroupItem value="default" /></Row>
          <Row label={t('requests.more.notifyCustom')}><RadioGroupItem value="custom" /></Row>
        </RadioGroup>
      </Section>

      <Section title={t('requests.more.printTemplate')}>
        <RadioGroup value={s.print_mode ?? 'default'} onValueChange={(v) => onChange({ print_mode: v as TemplateSettings['print_mode'] })}>
          <Row label={t('requests.more.printDefault')}><RadioGroupItem value="default" /></Row>
          <Row label={t('requests.more.printCustom')}><RadioGroupItem value="custom" /></Row>
        </RadioGroup>
      </Section>

      <Section title={t('requests.more.forwarding')}>
        <Row label={t('requests.more.forwardRestricted')}
             hint={t('requests.more.forwardRestrictedHint')}>
          <Checkbox checked={bool('only_related_can_forward')} onCheckedChange={(v) => onChange({ only_related_can_forward: Boolean(v) })} />
        </Row>
      </Section>

      <Section title={t('requests.more.efficiency')}>
        <Row label={t('requests.more.excludeFromStats')}
             hint={t('requests.more.excludeFromStatsHint')}>
          <Checkbox checked={bool('exclude_efficiency')} onCheckedChange={(v) => onChange({ exclude_efficiency: Boolean(v) })} />
        </Row>
      </Section>
    </div>
  );
}
