import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { Copy, Globe2, Loader2, Lock, Plus, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { accessApi } from '@/api/access';
import { RolePermissionMatrix } from '@/components/access/RolePermissionMatrix';
import { BackToProfile } from '@/components/BackToProfile';
import { Footer } from '@/components/Footer';
import { Header } from '@/components/Header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { isPlatformAdmin } from '@/lib/auth/roles';
import type { Role, RolePermission } from '@/types/access';

/**
 * Каталог ролей (§4.1, §4.2 спеки стадии 2).
 *
 * Экран ПЛОСКИЙ и без диаграммы — у роли нет ни веса, ни родителя: иерархию
 * несёт должность (§1.1). Диаграмма здесь означала бы, что связь между ролями
 * что-то передаёт, а она не передаёт ничего.
 *
 * Каталог ОБЩИЙ для всех компаний, поэтому правка роли меняет доступ везде
 * сразу и обратной силы у ошибки нет. Отсюда два решения интерфейса:
 * предупреждение стоит над списком постоянно, а не всплывает при сохранении,
 * и мутирующие действия видны только платформенному администратору — тому же,
 * кого пустит бэкенд (`is_superuser`, 403 иначе).
 */

interface InUseDetail {
  detail: string;
  positions: number;
  users: number;
}

const RoleCatalog = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { activeProfile } = useActiveProfile({ retry: false });
  const canEdit = isPlatformAdmin(activeProfile?.roles);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<RolePermission[] | null>(null);
  const [newCode, setNewCode] = useState('');
  const [newTitle, setNewTitle] = useState('');

  // Реестр функций — справочник, общий для всех ролей: грузится один раз.
  const functionsQuery = useQuery({
    queryKey: ['access', 'functions'],
    queryFn: async () => (await accessApi.getFunctions()).data,
  });

  const rolesQuery = useQuery({
    queryKey: ['access', 'roles'],
    queryFn: async () => (await accessApi.listRoles()).data,
  });

  const permissionsQuery = useQuery({
    queryKey: ['access', 'roles', selectedId, 'permissions'],
    queryFn: async () => (await accessApi.getRolePermissions(selectedId as number)).data,
    enabled: selectedId !== null,
  });

  // Черновик держится отдельно от загруженного набора: матрица правится
  // целиком и сохраняется одним PUT, поэтому промежуточное состояние не
  // должно затираться фоновым перезапросом.
  useEffect(() => {
    if (permissionsQuery.data) setDraft(permissionsQuery.data);
  }, [permissionsQuery.data]);

  const roles: Role[] = rolesQuery.data ?? [];
  const selected = roles.find((role) => role.id === selectedId) ?? null;

  const invalidateRoles = () => queryClient.invalidateQueries({ queryKey: ['access', 'roles'] });

  const createMutation = useMutation({
    mutationFn: () => accessApi.createRole({ code: newCode.trim(), title: newTitle.trim() }),
    onSuccess: async () => {
      setNewCode('');
      setNewTitle('');
      await invalidateRoles();
      toast.success(t('access.catalog.created', 'Роль создана'));
    },
    onError: (error: AxiosError) => {
      toast.error(
        error.response?.status === 422
          ? t('access.catalog.codeTaken', 'Код роли уже занят — он уникален на всей платформе')
          : t('access.catalog.saveFailed', 'Не удалось сохранить'),
      );
    },
  });

  const copyMutation = useMutation({
    mutationFn: (role: Role) => accessApi.copyRole(role.id, {
      // Код обязан быть уникален на всей платформе, поэтому предлагаем
      // производный и сразу занятый проверяем на сервере: угадывать свободный
      // в цикле — плодить роли-призраки при каждой неудаче.
      code: `${role.code}-copy`,
      title: t('access.catalog.copyTitle', '{{title}} (копия)', { title: role.title }),
    }),
    onSuccess: async () => {
      await invalidateRoles();
      toast.success(t('access.catalog.copied', 'Роль скопирована'));
    },
    onError: (error: AxiosError) => {
      toast.error(
        error.response?.status === 422
          ? t('access.catalog.copyCodeTaken',
            'Код для копии уже занят — переименуйте существующую копию или '
            + 'создайте роль вручную.')
          : t('access.catalog.saveFailed', 'Не удалось сохранить'),
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => accessApi.deleteRole(id),
    onSuccess: async (_data, id) => {
      if (selectedId === id) setSelectedId(null);
      await invalidateRoles();
      toast.success(t('access.catalog.deleted', 'Роль удалена'));
    },
    onError: (error: AxiosError<InUseDetail>) => {
      const body = error.response?.data;
      if (error.response?.status === 409 && body?.detail === 'in_use') {
        // Отказ без чисел выглядел бы произволом: человек должен видеть, у
        // скольких должностей и людей роль отнялась бы.
        toast.error(
          t('access.catalog.inUse', {
            positions: body.positions,
            users: body.users,
            defaultValue:
              'Роль назначена: должностей — {{positions}}, пользователей — {{users}}. '
              + 'Сначала снимите её, иначе права пропадут у всех сразу.',
          }),
        );
        return;
      }
      if (error.response?.status === 409) {
        toast.error(t('access.catalog.systemRole', 'Служебную роль удалить нельзя'));
        return;
      }
      toast.error(t('access.catalog.deleteFailed', 'Не удалось удалить роль'));
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => accessApi.putRolePermissions(
      selectedId as number,
      // Наружу уходят только узлы с собственной строкой: отсутствие узла и
      // есть «наследует от предка».
      (draft ?? []).map((row) => (row.preset
        ? { node: row.node, preset: row.preset }
        : { node: row.node, flags: row.flags })),
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['access', 'roles', selectedId, 'permissions'],
      });
      toast.success(t('access.catalog.permissionsSaved', 'Права роли сохранены'));
    },
    onError: () => toast.error(t('access.catalog.saveFailed', 'Не удалось сохранить')),
  });

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main className="container mx-auto w-full max-w-6xl flex-1 space-y-4 px-4 py-8">
        <BackToProfile />
      <div>
        <h1 className="text-2xl font-bold">
          {t('access.catalog.title', 'Каталог ролей')}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t(
            'access.catalog.subtitle',
            'Роль — набор прав: на каждую функцию задаётся глубина. Кому роль '
            + 'достанется, решает должность.',
          )}
        </p>
      </div>

      {/* Предупреждение постоянное, а не по факту сохранения: человек должен
          знать об области действия ДО того, как что-то поменяет. */}
      <div className="flex items-start gap-2 rounded-lg border border-amber-300/70 bg-amber-50/70 px-4 py-3 text-sm text-amber-900 dark:border-amber-800/70 dark:bg-amber-950/30 dark:text-amber-200">
        <Globe2 className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          {t(
            'access.catalog.globalWarning',
            'Каталог общий для всех компаний группы: правка роли меняет доступ везде сразу, '
            + 'а не только в текущей компании. Различия между компаниями задаются набором '
            + 'ролей у должности, а не правкой самой роли.',
          )}
        </p>
      </div>

      {!canEdit && (
        <div className="rounded-lg border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          {t(
            'access.catalog.readOnly',
            'Просмотр. Менять общий каталог может только администратор платформы.',
          )}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <section className="rounded-lg border">
          <header className="border-b px-4 py-3 text-sm font-medium">
            {t('access.catalog.rolesHeader', 'Роли')}
            {rolesQuery.isLoading && <Loader2 className="ml-2 inline h-3.5 w-3.5 animate-spin" />}
          </header>

          <ul className="max-h-[420px] divide-y overflow-y-auto">
            {roles.map((role) => (
              <li key={role.id}>
                <div
                  className={`flex items-center gap-2 px-3 py-2 ${
                    role.id === selectedId ? 'bg-muted/60' : ''
                  }`}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setSelectedId(role.id)}
                  >
                    <span className="block truncate text-sm font-medium">{role.title}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {role.code}
                    </span>
                  </button>
                  {role.is_system && (
                    <Badge variant="secondary" className="gap-1 text-[10px]">
                      <Lock className="h-3 w-3" />
                      {t('access.catalog.system', 'служебная')}
                    </Badge>
                  )}
                  {canEdit && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={t('access.catalog.copyRole', 'Копировать роль')}
                      disabled={copyMutation.isPending}
                      onClick={() => copyMutation.mutate(role)}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  )}
                  {canEdit && !role.is_system && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:text-destructive"
                      aria-label={t('access.catalog.deleteRole', 'Удалить роль')}
                      disabled={deleteMutation.isPending}
                      onClick={() => deleteMutation.mutate(role.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
            {!rolesQuery.isLoading && roles.length === 0 && (
              <li className="px-4 py-6 text-center text-sm text-muted-foreground">
                {t('access.catalog.empty', 'Ролей пока нет')}
              </li>
            )}
          </ul>

          {canEdit && (
            <form
              className="space-y-2 border-t p-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (newCode.trim() && newTitle.trim()) createMutation.mutate();
              }}
            >
              <Input
                value={newCode}
                onChange={(event) => setNewCode(event.target.value)}
                placeholder={t('access.catalog.codePlaceholder', 'код, например hr-admin')}
                aria-label={t('access.catalog.codeLabel', 'Код роли')}
              />
              <Input
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder={t('access.catalog.titlePlaceholder', 'название')}
                aria-label={t('access.catalog.titleLabel', 'Название роли')}
              />
              <Button
                type="submit"
                size="sm"
                className="w-full gap-1.5"
                disabled={!newCode.trim() || !newTitle.trim() || createMutation.isPending}
              >
                <Plus className="h-4 w-4" />
                {t('access.catalog.create', 'Создать роль')}
              </Button>
            </form>
          )}
        </section>

        <section className="rounded-lg border">
          {selected ? (
            <>
              <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{selected.title}</div>
                  <div className="truncate text-xs text-muted-foreground">{selected.code}</div>
                </div>
                {canEdit && (
                  <Button
                    size="sm"
                    className="gap-1.5"
                    disabled={saveMutation.isPending || draft === null}
                    onClick={() => saveMutation.mutate()}
                  >
                    <Save className="h-4 w-4" />
                    {t('access.catalog.save', 'Сохранить права')}
                  </Button>
                )}
              </header>

              <div className="p-4">
                {permissionsQuery.isLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('common.loading', 'Загрузка…')}
                  </div>
                ) : functionsQuery.data ? (
                  <RolePermissionMatrix
                    registry={functionsQuery.data}
                    value={draft ?? []}
                    onChange={setDraft}
                    disabled={!canEdit}
                  />
                ) : (
                  <div className="text-sm text-muted-foreground">
                    {t('access.catalog.registryUnavailable',
                      'Не удалось загрузить реестр функций — редактировать права нечем.')}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex h-full min-h-[240px] items-center justify-center p-6 text-center text-sm text-muted-foreground">
              {t('access.catalog.pickRole', 'Выберите роль, чтобы увидеть её права')}
            </div>
          )}
        </section>
      </div>
      </main>
      <Footer />
    </div>
  );
};

export default RoleCatalog;
