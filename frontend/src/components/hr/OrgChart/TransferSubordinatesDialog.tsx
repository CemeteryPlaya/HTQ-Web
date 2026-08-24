import { useState, useMemo } from 'react';
import { Crown, Users, UserCheck } from 'lucide-react';
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
import { Checkbox } from '@/components/ui/checkbox';
import { EntityCombobox, type EntityOption } from './EntityCombobox';
import type { OrgEdge, OrgNode } from '@/api/hr';
import { useTranslation } from 'react-i18next';

interface TransferSubordinatesDialogProps {
  open: boolean;
  onClose: () => void;
  currentNode: OrgNode | null;
  reports: OrgEdge[];
  candidateOptions: EntityOption[];
  nodeNames: Map<string, string>;
  onTransfer: (targetManagerId: string, subordinateIds: string[]) => Promise<void> | void;
  isLoading?: boolean;
}

export function TransferSubordinatesDialog({
  open,
  onClose,
  currentNode,
  reports,
  candidateOptions,
  nodeNames,
  onTransfer,
  isLoading = false,
}: TransferSubordinatesDialogProps) {
  const { t } = useTranslation();
  const [selectedReports, setSelectedReports] = useState<string[]>([]);
  const [targetManagerId, setTargetManagerId] = useState('');

  const reportNodeIds = useMemo(() => reports.map((r) => r.target), [reports]);

  const filteredCandidates = useMemo(() => {
    if (!currentNode) return candidateOptions;
    const currentNumId = Number(currentNode.id.split('_').pop());
    return candidateOptions.filter((c) => c.id !== currentNumId);
  }, [candidateOptions, currentNode]);

  const handleOpenChange = (isOpen: boolean) => {
    if (isOpen) {
      setSelectedReports(reportNodeIds);
      setTargetManagerId('');
    } else {
      if (!isLoading) onClose();
    }
  };

  const handleToggleReport = (nodeId: string) => {
    setSelectedReports((prev) =>
      prev.includes(nodeId) ? prev.filter((id) => id !== nodeId) : [...prev, nodeId]
    );
  };

  const handleToggleAll = () => {
    if (selectedReports.length === reportNodeIds.length) {
      setSelectedReports([]);
    } else {
      setSelectedReports(reportNodeIds);
    }
  };

  const handleConfirm = async () => {
    if (!targetManagerId || selectedReports.length === 0) return;
    const prefix = currentNode?.type === 'employee' ? 'emp_' : 'pos_';
    const fullTargetId = targetManagerId.startsWith('pos_') || targetManagerId.startsWith('emp_')
      ? targetManagerId
      : `${prefix}${targetManagerId}`;
    await onTransfer(fullTargetId, selectedReports);
    onClose();
  };

  if (!currentNode) return null;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="!max-w-[450px] !w-[calc(100vw-2rem)] p-4 sm:p-5 gap-3 max-h-[92vh] overflow-y-auto">
        <DialogHeader className="space-y-1 text-left pr-6">
          <DialogTitle className="flex items-center gap-2 text-sm sm:text-base font-bold text-foreground">
            <Users className="h-4 w-4 text-primary shrink-0" />
            <span className="truncate">{t('hr.orgChart.transfer.title')}</span>
          </DialogTitle>
          <DialogDescription className="text-[11px] text-muted-foreground leading-tight">
            {t('hr.orgChart.transfer.subtitle')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 my-1">
          {/* Current Manager & Target selection */}
          <div className="space-y-2.5 rounded-xl border bg-muted/40 p-2.5 text-xs">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground text-[11px]">{t('hr.orgChart.transfer.currentManager')}</span>
              <span className="font-semibold text-foreground truncate max-w-[200px]" title={currentNode.label}>
                {currentNode.label}
              </span>
            </div>

            <div className="space-y-1 pt-1.5 border-t">
              <label className="text-[11px] font-semibold text-foreground flex items-center gap-1">
                <Crown className="h-3 w-3 text-amber-500" />
                {t('hr.orgChart.newManager')}
              </label>
              <EntityCombobox
                mode="single"
                value={targetManagerId}
                onChange={setTargetManagerId}
                options={filteredCandidates}
                placeholder={t('hr.orgChart.transfer.pickManager')}
                searchPlaceholder={t('hr.orgChart.searchManager')}
                className="h-8 text-xs"
              />
            </div>
          </div>

          {/* Subordinates to transfer selection */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-semibold text-foreground">{t('hr.orgChart.transfer.reportsToMove')}</span>
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4">
                  {t('hr.orgChart.transfer.counter', { selected: selectedReports.length, total: reportNodeIds.length })}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 px-1.5 text-[10px] text-muted-foreground hover:text-foreground"
                onClick={handleToggleAll}
              >
                {selectedReports.length === reportNodeIds.length ? t('hr.orgChart.transfer.clearAll') : t('hr.orgChart.transfer.selectAll')}
              </Button>
            </div>

            <div className="max-h-[160px] overflow-y-auto rounded-lg border p-1 space-y-0.5 bg-background/60">
              {reports.length === 0 ? (
                <div className="py-4 text-center text-xs text-muted-foreground">
                  {t('hr.orgChart.transfer.noReports')}
                </div>
              ) : (
                reports.map((r) => {
                  const label = nodeNames.get(r.target) ?? r.target;
                  const isChecked = selectedReports.includes(r.target);
                  return (
                    <div
                      key={r.target}
                      onClick={() => handleToggleReport(r.target)}
                      className={`flex items-center justify-between gap-2 rounded-md px-2 py-1 text-xs cursor-pointer transition-colors ${
                        isChecked ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted/50'
                      }`}
                    >
                      <div className="flex items-center gap-2 min-w-0 flex-1">
                        <Checkbox
                          checked={isChecked}
                          onCheckedChange={() => handleToggleReport(r.target)}
                          className="shrink-0"
                        />
                        <span className="truncate text-xs">{label}</span>
                      </div>
                      <Badge variant="outline" className="text-[9px] px-1 py-0 h-3.5 shrink-0 font-normal">
                        {r.relation_type}
                      </Badge>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        <DialogFooter className="flex-row items-center justify-end gap-2 pt-1 sm:space-x-0">
          <Button variant="outline" size="sm" onClick={onClose} disabled={isLoading} className="h-8 text-xs px-3">
            {t('common.cancel')}
          </Button>
          <Button
            size="sm"
            onClick={handleConfirm}
            disabled={!targetManagerId || selectedReports.length === 0 || isLoading}
            className="h-8 text-xs px-3 gap-1"
          >
            <UserCheck className="h-3.5 w-3.5" />
            {isLoading ? t('hr.orgChart.transfer.inProgress') : t('hr.orgChart.transfer.submit', { count: selectedReports.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
