import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import api from '@/api/client';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

interface ActionLog {
  id: number;
  user_name: string;
  action: string;
  target_type: string;
  target_repr: string;
  details: string;
  ip_address: string | null;
  url: string;
  module: string;
  created_at: string;
}

const MODULE_COLORS: Record<string, string> = {
  hr: 'bg-blue-100 text-blue-800',
  news: 'bg-green-100 text-green-800',
  profile: 'bg-purple-100 text-purple-800',
  contacts: 'bg-yellow-100 text-yellow-800',
  auth: 'bg-red-100 text-red-800',
  admin: 'bg-orange-100 text-orange-800',
  other: 'bg-gray-100 text-gray-800',
};

const HRLogs = () => {
  const { t } = useTranslation();
  const [moduleFilter, setModuleFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const { data: logs, isLoading, error } = useQuery({
    queryKey: ['hr-logs'],
    queryFn: async () => {
      const res = await api.get<ActionLog[]>('hr/v1/logs/');
      return res.data;
    },
  });

  const filtered = (logs || []).filter((log) => {
    if (moduleFilter !== 'all' && log.module !== moduleFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        log.user_name?.toLowerCase().includes(q) ||
        log.target_repr?.toLowerCase().includes(q) ||
        log.details?.toLowerCase().includes(q) ||
        log.action?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-2">{t('hr.pages.logs.title')}</h1>
        <p className="text-muted-foreground mb-6">{t('hr.pages.logs.subtitle')}</p>

        <div className="flex gap-4 mb-4 flex-wrap">
          <Input
            placeholder={t('hr.common.search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-sm"
          />
          <Select value={moduleFilter} onValueChange={setModuleFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('hr.pages.logs.allModules')}</SelectItem>
              <SelectItem value="hr">HR</SelectItem>
              <SelectItem value="news">{t('hr.pages.logs.modules.news')}</SelectItem>
              <SelectItem value="profile">{t('hr.pages.logs.modules.profile')}</SelectItem>
              <SelectItem value="contacts">{t('hr.pages.logs.modules.contacts')}</SelectItem>
              <SelectItem value="auth">{t('hr.pages.logs.modules.auth')}</SelectItem>
              <SelectItem value="admin">{t('hr.pages.logs.modules.admin')}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isLoading && (
          <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
        )}
        {error && (
          <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
            {t('hr.pages.logs.error')}
          </div>
        )}
        {!isLoading && !error && (
          <div className="bg-card rounded-2xl border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('hr.pages.logs.table.time')}</TableHead>
                  <TableHead>{t('hr.pages.logs.table.user')}</TableHead>
                  <TableHead>{t('hr.pages.logs.table.module')}</TableHead>
                  <TableHead>{t('hr.pages.logs.table.action')}</TableHead>
                  <TableHead>{t('hr.pages.logs.table.target')}</TableHead>
                  <TableHead>{t('hr.pages.logs.table.details')}</TableHead>
                  <TableHead>{t('hr.pages.logs.table.ip')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="whitespace-nowrap">{new Date(log.created_at).toLocaleString()}</TableCell>
                    <TableCell className="font-medium">{log.user_name}</TableCell>
                    <TableCell>
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${MODULE_COLORS[log.module] || MODULE_COLORS.other}`}>
                        {log.module?.toUpperCase()}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{log.action}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="text-xs text-muted-foreground">{log.target_type}</div>
                      <div>{log.target_repr}</div>
                    </TableCell>
                    <TableCell className="max-w-md truncate text-sm">{log.details}</TableCell>
                    <TableCell className="text-xs">{log.ip_address || '—'}</TableCell>
                  </TableRow>
                ))}
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                      {t('hr.common.noData')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
};

export default HRLogs;
