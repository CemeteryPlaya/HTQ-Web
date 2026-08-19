import { useState } from 'react';
import { ArrowRight, Crown, ShieldAlert, UserRound, Users } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { OrgNode, RelationType } from '@/api/hr';

interface ConnectDialogProps {
  open: boolean;
  onClose: () => void;
  sourceNode: OrgNode | null;
  targetNode: OrgNode | null;
  currentSuperiorName?: string | null;
  onConfirm: (relationType: RelationType, note?: string) => void;
  isLoading?: boolean;
}

const RELATION_OPTIONS: { type: RelationType; title: string; subtitle: string; badge?: string }[] = [
  {
    type: 'direct',
    title: 'Прямое',
    subtitle: 'Основная иерархия',
    badge: 'Основной',
  },
  {
    type: 'functional',
    title: 'Функциональное',
    subtitle: 'Методическое',
  },
  {
    type: 'project',
    title: 'Проектное',
    subtitle: 'Временное',
  },
];

export function ConnectDialog({
  open,
  onClose,
  sourceNode,
  targetNode,
  currentSuperiorName,
  onConfirm,
  isLoading = false,
}: ConnectDialogProps) {
  const [relationType, setRelationType] = useState<RelationType>('direct');
  const [note, setNote] = useState('');

  if (!sourceNode || !targetNode) return null;

  const isEmployee = sourceNode.type === 'employee';
  const hasExistingSuperior = Boolean(currentSuperiorName);

  const handleConfirm = () => {
    onConfirm(relationType, note.trim() || undefined);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !isLoading && onClose()}>
      <DialogContent className="!max-w-[440px] !w-[calc(100vw-2rem)] p-4 sm:p-5 gap-3 max-h-[92vh] overflow-y-auto">
        <DialogHeader className="space-y-1 text-left sm:text-left pr-6">
          <DialogTitle className="flex items-center gap-2 text-sm sm:text-base font-bold text-foreground">
            <Users className="h-4 w-4 text-primary shrink-0" />
            <span className="truncate">Установка связи подчинения</span>
          </DialogTitle>
          <DialogDescription className="text-[11px] text-muted-foreground leading-tight">
            Выберите тип подчинения между выбранными узлами
          </DialogDescription>
        </DialogHeader>

        {/* Nodes connection preview */}
        <div className="rounded-xl border bg-muted/40 p-2.5 space-y-2 text-xs">
          <div className="grid grid-cols-[1fr,auto,1fr] items-center gap-2">
            {/* Source / Superior */}
            <div className="min-w-0">
              <div className="flex items-center gap-1 text-[10px] text-muted-foreground font-medium mb-0.5">
                <Crown className="h-3 w-3 text-amber-500 shrink-0" />
                <span className="truncate">Руководитель</span>
              </div>
              <div className="font-semibold text-xs text-foreground truncate" title={sourceNode.label}>
                {sourceNode.label}
              </div>
              {Boolean(sourceNode.meta?.department_name) && (
                <div className="text-[10px] text-muted-foreground truncate" title={String(sourceNode.meta?.department_name)}>
                  {String(sourceNode.meta?.department_name)}
                </div>
              )}
            </div>

            {/* Arrow */}
            <div className="flex items-center justify-center text-primary px-1">
              <ArrowRight className="h-4 w-4" />
            </div>

            {/* Target / Subordinate */}
            <div className="min-w-0 text-right">
              <div className="flex items-center justify-end gap-1 text-[10px] text-muted-foreground font-medium mb-0.5">
                <UserRound className="h-3 w-3 text-sky-500 shrink-0" />
                <span className="truncate">Подчинённый</span>
              </div>
              <div className="font-semibold text-xs text-foreground truncate" title={targetNode.label}>
                {targetNode.label}
              </div>
              {Boolean(targetNode.meta?.department_name) && (
                <div className="text-[10px] text-muted-foreground truncate" title={String(targetNode.meta?.department_name)}>
                  {String(targetNode.meta?.department_name)}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Warning if replacing existing supervisor */}
        {hasExistingSuperior && relationType === 'direct' && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-300/80 bg-amber-50/80 p-2 text-[11px] text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200">
            <ShieldAlert className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="min-w-0 leading-tight">
              <span className="font-semibold">Переназначение:</span> заменит текущего прямого руководителя (<span className="font-medium">{currentSuperiorName}</span>).
            </div>
          </div>
        )}

        {/* Relation type selector: 3 compact grid cards */}
        <div className="space-y-1.5">
          <label className="text-[11px] font-semibold text-muted-foreground">Тип подчинения:</label>
          <div className="grid grid-cols-3 gap-1.5">
            {RELATION_OPTIONS.map((opt) => {
              const isSelected = relationType === opt.type;
              return (
                <button
                  key={opt.type}
                  type="button"
                  onClick={() => setRelationType(opt.type)}
                  className={`flex flex-col items-center justify-center p-2 rounded-lg border text-center transition-all cursor-pointer ${
                    isSelected
                      ? 'border-primary bg-primary/10 text-primary font-bold shadow-xs ring-1 ring-primary'
                      : 'border-border bg-background hover:bg-muted/50 text-foreground/80'
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <span className="text-xs font-semibold">{opt.title}</span>
                  </div>
                  <span className="text-[10px] text-muted-foreground leading-tight mt-0.5">
                    {opt.subtitle}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Optional note for employees */}
        {isEmployee && (
          <div className="space-y-1">
            <label htmlFor="rel-note" className="text-[11px] text-muted-foreground">
              Примечание (опционально):
            </label>
            <input
              id="rel-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Например: проект, куратор..."
              className="flex h-7 w-full rounded-md border border-input bg-transparent px-2.5 py-1 text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        )}

        <DialogFooter className="flex-row items-center justify-end gap-2 pt-1 sm:space-x-0">
          <Button variant="outline" size="sm" onClick={onClose} disabled={isLoading} className="h-8 text-xs px-3">
            Отмена
          </Button>
          <Button size="sm" onClick={handleConfirm} disabled={isLoading} className="h-8 text-xs px-3">
            {isLoading ? 'Сохранение...' : 'Сохранить связь'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
