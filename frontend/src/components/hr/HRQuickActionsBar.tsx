import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  UserPlus,
  Building2,
  Briefcase,
  Sparkles,
  ChevronDown,
  Users,
  BriefcaseBusiness,
  FileCheck,
  PlusCircle,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useHRLevel } from '@/hooks/useHRLevel';
import api from '@/api/client';

export const HRQuickActionsBar: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { canCreateEmployee, isSenior } = useHRLevel();

  // Quick stats query for HR overview
  const { data: stats } = useQuery({
    queryKey: ['hr-quick-stats'],
    queryFn: async () => {
      try {
        const [empRes, deptRes, posRes] = await Promise.allSettled([
          api.get('hr/v1/employees/'),
          api.get('hr/v1/departments/'),
          api.get('hr/v1/positions/'),
        ]);
        const employeesCount = empRes.status === 'fulfilled' && Array.isArray(empRes.value.data) ? empRes.value.data.length : 0;
        const departmentsCount = deptRes.status === 'fulfilled' && Array.isArray(deptRes.value.data) ? deptRes.value.data.length : 0;
        const positionsCount = posRes.status === 'fulfilled' && Array.isArray(posRes.value.data) ? posRes.value.data.length : 0;

        return { employeesCount, departmentsCount, positionsCount };
      } catch {
        return { employeesCount: 0, departmentsCount: 0, positionsCount: 0 };
      }
    },
    staleTime: 60000,
  });

  return (
    <div className="rounded-3xl border bg-card/90 p-4 shadow-2xs transition-all mb-6">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Left: HR Quick Stats & Badges */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 pr-2 border-r border-border/60">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Быстрые действия
            </span>
          </div>

          {stats && (
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="flex items-center gap-1.5 bg-muted/60 px-2.5 py-1 rounded-lg font-medium text-foreground">
                <Users className="h-3.5 w-3.5 text-primary" />
                Сотрудников: <strong className="font-semibold">{stats.employeesCount}</strong>
              </span>
              <span className="flex items-center gap-1.5 bg-muted/60 px-2.5 py-1 rounded-lg font-medium text-foreground">
                <Building2 className="h-3.5 w-3.5 text-primary" />
                Отделов: <strong className="font-semibold">{stats.departmentsCount}</strong>
              </span>
              <span className="flex items-center gap-1.5 bg-muted/60 px-2.5 py-1 rounded-lg font-medium text-foreground">
                <BriefcaseBusiness className="h-3.5 w-3.5 text-primary" />
                Должностей: <strong className="font-semibold">{stats.positionsCount}</strong>
              </span>
            </div>
          )}
        </div>

        {/* Right: Action Buttons Group */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Main Primary Action Button */}
          {canCreateEmployee && (
            <Button
              size="sm"
              className="gap-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 shadow-2xs font-semibold"
              onClick={() => navigate('/hr/employees?action=new')}
            >
              <UserPlus className="h-4 w-4" />
              Добавить сотрудника
            </Button>
          )}

          {/* Create Department */}
          <Button
            size="sm"
            variant="outline"
            className="gap-2 rounded-xl border-muted hover:border-primary/40"
            onClick={() => navigate('/hr/departments?action=new')}
          >
            <Building2 className="h-4 w-4 text-primary" />
            Новый отдел
          </Button>

          {/* Quick Dropdown with More Actions */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost" className="gap-1.5 rounded-xl border border-muted">
                <PlusCircle className="h-4 w-4 text-muted-foreground" />
                <span>Ещё действие</span>
                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56 rounded-2xl p-2">
              <DropdownMenuLabel className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                Создание сущностей
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="gap-2.5 cursor-pointer rounded-xl"
                onClick={() => navigate('/hr/positions')}
              >
                <Briefcase className="h-4 w-4 text-primary" />
                <span>Новая должность</span>
              </DropdownMenuItem>
              <DropdownMenuItem
                className="gap-2.5 cursor-pointer rounded-xl"
                onClick={() => navigate('/hr/recruitment?tab=vacancies')}
              >
                <FileCheck className="h-4 w-4 text-emerald-600" />
                <span>Открыть вакансию</span>
              </DropdownMenuItem>
              <DropdownMenuItem
                className="gap-2.5 cursor-pointer rounded-xl"
                onClick={() => navigate('/hr/recruitment?tab=offers')}
              >
                <UserPlus className="h-4 w-4 text-purple-600" />
                <span>Сформировать оффер</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </div>
  );
};
