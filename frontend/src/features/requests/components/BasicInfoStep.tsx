/** Builder Step 1 — Basic Info (Lark parity, screenshot 10):
 *  icon, name, description, document group, who-can-submit, workplace toggle,
 *  admin-management toggle, and process administrators. */

import {
  Briefcase, Calendar, ClipboardList, DollarSign, FileText, FolderKanban,
  ShoppingCart, Users,
} from 'lucide-react';

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';

import { EmployeePicker } from '@/features/requests/components/EmployeePicker';
import type { TemplateConfig } from '@/features/requests/types';

export interface BasicInfoValue {
  name: string;
  description: string;
  icon: string;
  color: string;
  config: TemplateConfig;
}

const ICONS: { key: string; Icon: typeof FileText }[] = [
  { key: 'file', Icon: FileText },
  { key: 'briefcase', Icon: Briefcase },
  { key: 'dollar', Icon: DollarSign },
  { key: 'clipboard', Icon: ClipboardList },
  { key: 'cart', Icon: ShoppingCart },
  { key: 'users', Icon: Users },
  { key: 'calendar', Icon: Calendar },
  { key: 'folder', Icon: FolderKanban },
];

const COLORS = ['#3b82f6', '#f97316', '#ec4899', '#10b981', '#a855f7', '#ef4444', '#64748b'];

const KNOWN_GROUPS = [
  'Документы для снабжения',
  'Документы для проектного менеджера',
  'Финансы/Бюджет',
  'План закупок',
  'Проектная документация',
];

interface Props {
  value: BasicInfoValue;
  onChange: (patch: Partial<BasicInfoValue>) => void;
  createdBy: number | null;
}

export function BasicInfoStep({ value, onChange, createdBy }: Props) {
  const cfg = value.config ?? {};
  const patchCfg = (p: Partial<TemplateConfig>) => onChange({ config: { ...cfg, ...p } });
  const scope = cfg.who_can_submit ?? 'all';

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      {/* Icon */}
      <div className="space-y-2">
        <Label>Иконка *</Label>
        <div className="flex flex-wrap items-center gap-2">
          {ICONS.map(({ key, Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => onChange({ icon: key })}
              className={`flex h-10 w-10 items-center justify-center rounded-lg text-white ring-offset-2 ${value.icon === key ? 'ring-2 ring-primary' : ''}`}
              style={{ backgroundColor: value.color || '#3b82f6' }}
              aria-label={`Иконка ${key}`}
            >
              <Icon className="h-5 w-5" />
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 pt-1">
          {COLORS.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => onChange({ color: c })}
              className={`h-6 w-6 rounded-full ${value.color === c ? 'ring-2 ring-offset-2 ring-foreground' : ''}`}
              style={{ backgroundColor: c }}
              aria-label={`Цвет ${c}`}
            />
          ))}
        </div>
      </div>

      {/* Name */}
      <div className="space-y-1.5">
        <Label htmlFor="bi-name">Название *</Label>
        <Input id="bi-name" value={value.name} onChange={(e) => onChange({ name: e.target.value })} placeholder="Счёт на оплату KZ" />
      </div>

      {/* Description */}
      <div className="space-y-1.5">
        <Label htmlFor="bi-desc">Описание</Label>
        <Input id="bi-desc" value={value.description} onChange={(e) => onChange({ description: e.target.value })} placeholder="Короткое описание" />
      </div>

      {/* Group */}
      <div className="space-y-1.5">
        <Label htmlFor="bi-group">Группа документов *</Label>
        <Input
          id="bi-group"
          list="bi-group-list"
          value={cfg.group ?? ''}
          onChange={(e) => patchCfg({ group: e.target.value })}
          placeholder="Выберите или введите группу"
        />
        <datalist id="bi-group-list">
          {KNOWN_GROUPS.map((g) => <option key={g} value={g} />)}
        </datalist>
      </div>

      {/* Who can submit */}
      <div className="space-y-2">
        <Label>Кто может подавать этот запрос *</Label>
        <RadioGroup value={scope} onValueChange={(v) => patchCfg({ who_can_submit: v as TemplateConfig['who_can_submit'] })}>
          <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="all" /> Все</label>
          <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="selected" /> Выбранные пользователи</label>
          <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="none" /> Никто</label>
        </RadioGroup>
        {scope === 'selected' && (
          <EmployeePicker
            value={cfg.submit_user_ids ?? []}
            onChange={(ids) => patchCfg({ submit_user_ids: ids })}
          />
        )}
      </div>

      {/* Toggles */}
      <label className="flex items-start gap-2 text-sm">
        <Checkbox checked={cfg.show_on_workplace ?? false} onCheckedChange={(v) => patchCfg({ show_on_workplace: Boolean(v) })} />
        <span>Показывать в формах для заполнения (каталог «Отправить запрос»)</span>
      </label>
      <label className="flex items-start gap-2 text-sm">
        <Checkbox checked={cfg.prohibit_admin_manage ?? false} onCheckedChange={(v) => patchCfg({ prohibit_admin_manage: Boolean(v) })} />
        <span>Запретить администраторам и субадминистраторам компании управлять процессами и данными</span>
      </label>

      {/* Process administrators */}
      <div className="space-y-1.5">
        <Label>Администраторы процесса * <span className="text-xs font-normal text-muted-foreground">(до 5)</span></Label>
        <EmployeePicker
          value={cfg.process_admin_ids ?? (createdBy != null ? [createdBy] : [])}
          onChange={(ids) => patchCfg({ process_admin_ids: ids })}
          max={5}
        />
        <p className="text-xs text-muted-foreground">По умолчанию — создатель шаблона. Можно убрать себя и указать другого.</p>
      </div>
    </div>
  );
}
