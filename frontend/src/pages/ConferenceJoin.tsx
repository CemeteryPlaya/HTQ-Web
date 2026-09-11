/**
 * Вход в конференцию по ссылке-приглашению — `/join/:token`.
 *
 * Единственная страница платформы, которая работает без учётки, и вся её
 * задача — превратить «человека со ссылкой» в участника звонка: показать,
 * куда его позвали, спросить имя и обменять приглашение на гостевой токен.
 *
 * Сотрудника здесь не задерживаем: если в браузере есть рабочая сессия,
 * сервер вернёт вместе с описанием встречи и комнату, и мы сразу отправим
 * его в звонок под своим именем.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, LogIn, Video } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { fetchInviteInfo, requestGuestToken } from '@/api/conference';
import { getAccessToken } from '@/lib/auth/profileStorage';
import {
  applyGuestLocale, normalizeConferenceLocale, saveGuestSession,
} from '@/lib/conference/guestSession';

const ConferenceJoin: React.FC = () => {
  const { token = '' } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  // Пока язык приглашения не применён (или не нужен), форму для гостя не
  // показываем — иначе она на мгновение отрисуется в текущем языке браузера
  // и тут же переключится на язык из ссылки. Тому, для кого и делалась эта
  // функциональность (иностранный гость), такой скачок виден лучше всего.
  const [localeReady, setLocaleReady] = useState(false);

  const isEmployee = Boolean(getAccessToken());

  const { data: invite, isLoading, isError, error: loadError } = useQuery({
    queryKey: ['conference-invite', token],
    queryFn: () => fetchInviteInfo(token),
    enabled: Boolean(token),
    retry: false,
  });

  // Сотрудник представляться не должен — он и так известен платформе.
  useEffect(() => {
    if (invite?.room_id) navigate(`/room/${encodeURIComponent(invite.room_id)}`, { replace: true });
  }, [invite?.room_id, navigate]);

  // Язык приглашения — только для гостя. Сотрудника, открывшего ту же
  // ссылку, эффект выше уже уводит в комнату под своей учёткой и своим
  // языком — до этой строки он не доходит, а значит, навязывать ему чужой
  // выбор языка здесь и не получится: осознанно, а не по недосмотру.
  useEffect(() => {
    if (!invite || invite.room_id) return;
    const target = normalizeConferenceLocale(invite.locale);
    if (!target) {
      setLocaleReady(true);
      return;
    }
    let cancelled = false;
    applyGuestLocale(target).finally(() => { if (!cancelled) setLocaleReady(true); });
    return () => { cancelled = true; };
  }, [invite]);

  const join = useMutation({
    mutationFn: () => requestGuestToken(token, name.trim()),
    onSuccess: (data) => {
      saveGuestSession({
        token: data.access_token,
        roomId: data.room_id,
        displayName: data.display_name,
        title: data.title,
        expiresAt: Date.now() + data.expires_in * 1000,
        conference: data.conference,
        // Тот же язык, что уже применён на этой странице, — чтобы при
        // переходе в комнату (и тем более при обновлении вкладки в ней) он
        // не откатился на язык браузера.
        locale: normalizeConferenceLocale(data.locale),
      });
      navigate(`/room/${encodeURIComponent(data.room_id)}`, { replace: true });
    },
    onError: (err: Error) => setError(err.message),
  });

  // Показываем форму, только когда и данные приглашения, и (если нужно)
  // язык интерфейса уже готовы — см. комментарий у localeReady выше.
  const pending = isLoading || (Boolean(invite) && !invite.room_id && !localeReady);

  const canJoin = name.trim().length > 0 && !join.isPending;

  return (
    <div className="min-h-screen flex items-center justify-center bg-muted/30 px-4 py-10">
      <Card className="w-full max-w-md rounded-3xl shadow-elevated">
        <CardHeader className="text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-600/10">
            <Video className="h-7 w-7 text-emerald-600" />
          </div>
          <CardTitle className="text-xl">
            {pending
              ? <Skeleton className="mx-auto h-6 w-40" />
              : (invite?.title || t('conference.join.defaultTitle', 'Видеоконференция'))}
          </CardTitle>
          <CardDescription>
            {pending
              ? <Skeleton className="mx-auto mt-1 h-4 w-56" />
              : t('conference.join.subtitle', 'Вас пригласили присоединиться к звонку')}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {pending && !isError && <Skeleton className="h-24 w-full rounded-2xl" />}

          {isError && (
            <div className="flex items-start gap-3 rounded-2xl border border-destructive/40 p-4 text-sm">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
              <div>
                <p className="font-medium">
                  {t('conference.join.invalid', 'Ссылка не работает')}
                </p>
                <p className="text-muted-foreground">
                  {(loadError as Error)?.message}
                </p>
              </div>
            </div>
          )}

          {!pending && invite && !invite.room_id && !invite.allow_guests && (
            // Ссылка «только для своих»: гостевой токен по ней не выдаётся,
            // и единственный честный выход — обычный вход в платформу.
            <div className="space-y-3 text-center">
              <p className="text-sm text-muted-foreground">
                {t('conference.join.staffOnly',
                  'По этой ссылке входят только сотрудники. Войдите в платформу под своей учётной записью.')}
              </p>
              <Button className="w-full rounded-xl" onClick={() => navigate('/login')}>
                <LogIn className="mr-2 h-4 w-4" /> {t('auth.loginHere')}
              </Button>
            </div>
          )}

          {!pending && invite && !invite.room_id && invite.allow_guests && (
            <form
              className="space-y-3"
              onSubmit={(e) => { e.preventDefault(); if (canJoin) join.mutate(); }}
            >
              <label className="block text-sm font-medium" htmlFor="guest-name">
                {t('conference.join.nameLabel', 'Как вас представить участникам')}
              </label>
              <Input
                id="guest-name"
                autoFocus
                maxLength={80}
                value={name}
                onChange={(e) => { setName(e.target.value); setError(null); }}
                placeholder={t('conference.join.namePlaceholder', 'Имя и компания')}
              />
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full rounded-xl" disabled={!canJoin}>
                {join.isPending
                  ? t('conference.join.entering', 'Входим…')
                  : t('conference.join.enter', 'Войти в конференцию')}
              </Button>
              {isEmployee && (
                <p className="text-xs text-muted-foreground">
                  {t('conference.join.employeeHint',
                    'Вы вошли как сотрудник — можно присоединиться под своей учётной записью.')}
                </p>
              )}
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default ConferenceJoin;
