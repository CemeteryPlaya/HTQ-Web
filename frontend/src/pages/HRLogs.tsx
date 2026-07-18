import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { fetchActionLogs, fetchEmployees, fetchDepartments, fetchPositions } from '@/api/hr';
import type { HRActionLog, HRActionType, HRTargetType } from '@/types/hr';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Search, ScrollText, RefreshCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

const ACTION_COLORS: Record<HRActionType, string> = {
  create: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  update: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  delete: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
  approve: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  reject: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
  status_change: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
};

const TARGET_ICONS: Record<HRTargetType, string> = {
  employee: '👤',
  department: '🏢',
  position: '💼',
  vacancy: '📋',
  application: '📨',
  time_tracking: '🕐',
  document: '📄',
};

const HRLogs: React.FC = () => {
  const { t } = useTranslation();
  const [actionFilter, setActionFilter] = useState('all');
  const [targetFilter, setTargetFilter] = useState('all');
  const [employeeFilter, setEmployeeFilter] = useState('all');
  const [departmentFilter, setDepartmentFilter] = useState('all');
  const [positionFilter, setPositionFilter] = useState('all');
  const [search, setSearch] = useState('');

  const { data: employees = [] } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: () => fetchEmployees(),
  });

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: () => fetchDepartments(),
  });

  const { data: positions = [] } = useQuery({
    queryKey: ['hr-positions'],
    queryFn: () => fetchPositions(),
  });

  const params: Record<string, string> = {};
  if (actionFilter !== 'all') params.action = actionFilter;
  if (targetFilter !== 'all') params.target_type = targetFilter;
  if (employeeFilter !== 'all') params.employee = employeeFilter;
  if (departmentFilter !== 'all') params.department = departmentFilter;
  if (positionFilter !== 'all') params.position = positionFilter;
  if (search.trim()) params.search = search.trim();

  const { data: logs = [], isLoading, refetch } = useQuery({
    queryKey: ['hr-logs', params],
    queryFn: () => fetchActionLogs(params),
    refetchInterval: 30_000, // Авто-обновление каждые 30 сек
  });

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto px-4 py-8">
        <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <ScrollText className="h-5 w-5" />
                {t('hr.logs.title')}
              </CardTitle>
              <CardDescription>{t('hr.logs.subtitle')}</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => refetch()}>
              <RefreshCcw className="h-4 w-4 mr-1" />
              {t('hr.logs.refresh')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {/* Filters */}
          <div className="flex flex-wrap gap-3 mb-4">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('hr.logs.searchPlaceholder')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>

            <Select value={actionFilter} onValueChange={setActionFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.logs.allActions')}</SelectItem>
                <SelectItem value="create">{t('hr.logs.actionCreate')}</SelectItem>
                <SelectItem value="update">{t('hr.logs.actionUpdate')}</SelectItem>
                <SelectItem value="delete">{t('hr.logs.actionDelete')}</SelectItem>
                <SelectItem value="approve">{t('hr.logs.actionApprove')}</SelectItem>
                <SelectItem value="reject">{t('hr.logs.actionReject')}</SelectItem>
                <SelectItem value="status_change">{t('hr.logs.actionStatusChange')}</SelectItem>
              </SelectContent>
            </Select>

            <Select value={targetFilter} onValueChange={setTargetFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.logs.allTargets')}</SelectItem>
                <SelectItem value="employee">{t('hr.logs.targetEmployee')}</SelectItem>
                <SelectItem value="department">{t('hr.logs.targetDepartment')}</SelectItem>
                <SelectItem value="position">{t('hr.logs.targetPosition')}</SelectItem>
                <SelectItem value="vacancy">{t('hr.logs.targetVacancy')}</SelectItem>
                <SelectItem value="application">{t('hr.logs.targetApplication')}</SelectItem>
                <SelectItem value="time_tracking">{t('hr.logs.targetTimeTracking')}</SelectItem>
                <SelectItem value="document">{t('hr.logs.targetDocument')}</SelectItem>
              </SelectContent>
            </Select>

            <Select value={employeeFilter} onValueChange={setEmployeeFilter}>
              <SelectTrigger className="w-[220px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.logs.allEmployees')}</SelectItem>
                {employees.map((emp) => (
                  <SelectItem key={emp.id} value={String(emp.id)}>
                    {emp.full_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={departmentFilter} onValueChange={setDepartmentFilter}>
              <SelectTrigger className="w-[200px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.logs.allDepartments')}</SelectItem>
                {departments.map((dept) => (
                  <SelectItem key={dept.id} value={String(dept.id)}>
                    {dept.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={positionFilter} onValueChange={setPositionFilter}>
              <SelectTrigger className="w-[200px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.logs.allPositions')}</SelectItem>
                {positions.map((pos) => (
                  <SelectItem key={pos.id} value={String(pos.id)}>
                    {pos.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Table */}
          <ScrollArea className="h-[600px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[170px]">{t('hr.logs.col.date')}</TableHead>
                  <TableHead>{t('hr.logs.col.user')}</TableHead>
                  <TableHead>{t('hr.logs.col.action')}</TableHead>
                  <TableHead>{t('hr.logs.col.target')}</TableHead>
                  <TableHead>{t('hr.logs.col.object')}</TableHead>
                  <TableHead className="hidden md:table-cell">{t('hr.logs.col.details')}</TableHead>
                  <TableHead className="hidden lg:table-cell">{t('hr.logs.col.ip')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                      {t('hr.logs.loading')}
                    </TableCell>
                  </TableRow>
                ) : logs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-12 text-muted-foreground">
                      {t('hr.logs.empty')}
                    </TableCell>
                  </TableRow>
                ) : (
                  logs.map((log: HRActionLog) => (
                    <TableRow key={log.id}>
                      <TableCell className="text-xs whitespace-nowrap">
                        {formatDate(log.created_at)}
                      </TableCell>
                      <TableCell className="font-medium">{log.user_name}</TableCell>
                      <TableCell>
                        <Badge variant="secondary" className={ACTION_COLORS[log.action]}>
                          {t(`hr.logs.action_${log.action}`)}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span className="mr-1">{TARGET_ICONS[log.target_type]}</span>
                        {t(`hr.logs.target_${log.target_type}`)}
                      </TableCell>
                      <TableCell className="max-w-[200px] truncate" title={log.target_repr}>
                        {log.target_repr}
                      </TableCell>
                      <TableCell className="hidden md:table-cell max-w-[250px] truncate text-muted-foreground text-xs" title={log.details}>
                        {log.details}
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">
                        {log.ip_address || '—'}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </ScrollArea>

          {!isLoading && logs.length > 0 && (
            <p className="text-xs text-muted-foreground mt-2 text-right">
              {t('hr.logs.showing', { count: logs.length })}
            </p>
          )}
        </CardContent>
        </Card>
      </main>
      <Footer />
    </div>
  );
};

export default HRLogs;
