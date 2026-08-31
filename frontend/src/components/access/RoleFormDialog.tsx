import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import type { Role } from '@/types/access';

/**
 * Код и название роли — при копировании и при переименовании.
 *
 * Один диалог на две операции: поля те же, и разводить их в два компонента
 * значило бы дважды писать одну форму. Отличается только заголовок и то, с
 * какими значениями она открывается.
 *
 * **Код правится наравне с названием.** Без этого копия навсегда оставалась бы
 * `<исходный>-copy`, а вторая копия того же исходника не завелась бы вовсе:
 * код уникален на всей платформе.
 *
 * ⚠️ У системной роли код заблокирован — по нему её находят миграции. Поле
 * показывается, но недоступно, с объяснением: скрыть его значило бы оставить
 * человека гадать, почему у одной роли код правится, а у другой нет.
 */

export type RoleFormMode = 'copy' | 'rename';

export interface RoleFormDialogProps {
  role: Role | null;
  mode: RoleFormMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { code: string; title: string }) => void;
  isPending?: boolean;
}

export function RoleFormDialog({
  role,
  mode,
  open,
  onOpenChange,
  onSubmit,
  isPending = false,
}: RoleFormDialogProps) {
  const { t } = useTranslation();
  const [code, setCode] = useState('');
  const [title, setTitle] = useState('');

  // Значения подставляются при КАЖДОМ открытии: иначе следующая роль
  // открылась бы с полями предыдущей, и разница заметна далеко не сразу.
  useEffect(() => {
    if (!open || !role) return;
    if (mode === 'copy') {
      setCode(`${role.code}-copy`);
      setTitle(t('access.catalog.copyTitle', '{{title}} (копия)', { title: role.title }));
    } else {
      setCode(role.code);
      setTitle(role.title);
    }
  }, [open, role, mode, t]);

  const codeLocked = mode === 'rename' && Boolean(role?.is_system);
  const ready = code.trim().length > 0 && title.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {mode === 'copy'
              ? t('access.catalog.copyDialogTitle', 'Копия роли')
              : t('access.catalog.renameDialogTitle', 'Переименовать роль')}
          </DialogTitle>
          <DialogDescription>
            {mode === 'copy'
              ? t('access.catalog.copyDialogHint',
                'Права копируются целиком — их можно поправить после.')
              : t('access.catalog.renameDialogHint',
                'Права роли не меняются.')}
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (ready) onSubmit({ code: code.trim(), title: title.trim() });
          }}
        >
          <label className="grid gap-1.5 text-sm">
            {t('access.catalog.codeLabel', 'Код роли')}
            <Input
              value={code}
              disabled={codeLocked}
              onChange={(event) => setCode(event.target.value)}
              aria-label={t('access.catalog.codeLabel', 'Код роли')}
            />
            {codeLocked && (
              <span className="text-xs text-muted-foreground">
                {t('access.catalog.codeLocked',
                  'Код системной роли менять нельзя: по нему её находят миграции.')}
              </span>
            )}
          </label>

          <label className="grid gap-1.5 text-sm">
            {t('access.catalog.titleLabel', 'Название роли')}
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              aria-label={t('access.catalog.titleLabel', 'Название роли')}
            />
          </label>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button type="submit" disabled={!ready || isPending}>
              {mode === 'copy'
                ? t('access.catalog.create', 'Создать роль')
                : t('access.catalog.save', 'Сохранить')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default RoleFormDialog;
