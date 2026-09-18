import { Navigate, useLocation } from "react-router-dom";
import type { AxiosError } from "axios";
import { ForcePasswordChange } from "./ForcePasswordChange";
import { Loader2 } from "lucide-react";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { usePermissions } from "@/hooks/usePermissions";
import type { RouteRequirement } from "@/app/routing/types";
import { useTranslation } from 'react-i18next';

interface RequireAuthProps {
    children: JSX.Element;
    /** Путь маршрута — для проверки, не закрыта ли страница ролью. */
    page?: string;
    /** Гейт по модулю и уровню (§4 контракта стадии 2). */
    requires?: RouteRequirement;
}

const RequireAuth = ({ children, requires, page }: RequireAuthProps) => {
    const { t } = useTranslation();
    const location = useLocation();
    const { activeProfile, isLoading, error, isLoggedIn, clearAuthStorage, refetch } = useActiveProfile({
        retry: false,
    });
    const permissions = usePermissions();

    if (!isLoggedIn) {
        return <Navigate to="/login" state={{ from: location }} replace />;
    }

    // Distinguish "your session is invalid" from "the backend is unreachable".
    // Only a real auth rejection (401/403) should log the user out; a hung or
    // down backend (timeout / network / 5xx) must NOT nuke the session — that
    // used to strand the user on an infinite spinner or bounce them to /login.
    if (error) {
        const status = (error as AxiosError)?.response?.status;
        if (status === 401 || status === 403) {
            clearAuthStorage();
            return <Navigate to="/login" state={{ from: location }} replace />;
        }
        if (!activeProfile) {
            return (
                <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-4 px-6 text-center">
                    <p className="text-muted-foreground">
                        {t('auth.errors.serverUnreachable')}
                    </p>
                    <button
                        onClick={() => refetch()}
                        className="rounded-full border px-5 py-2 text-sm font-medium transition-colors hover:bg-accent"
                    >
                        {t('common.retry')}
                    </button>
                </div>
            );
        }
        // else: fall through and render with the cached profile (best-effort).
    }

    if (isLoading && !activeProfile) {
        return (
            <div className="min-h-screen bg-background flex flex-col items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-primary opacity-50" />
            </div>
        );
    }

    if (activeProfile?.must_change_password) {
        return <ForcePasswordChange />;
    }

    // Страница — слой ВЫШЕ глубины: закрытая отменяет всё, что разрешено
    // модулями. Проверяется первой именно поэтому, а не для скорости.
    if (page && !permissions.isLoading && permissions.pageHidden(page)) {
        return <Navigate to="/myprofile" replace state={{ from: location, accessDenied: true }} />;
    }

    // Гейт по модулю и уровню. Это UX-рубеж — настоящий отказ выдаёт бэкенд на
    // каждом вызове API, поэтому недолгое окно устаревшего кеша ничего не
    // раскрывает. Перерисовка происходит сама, когда приедут свежие права.
    if (requires) {
        // Пока права неизвестны — ЖДЁМ, а не отвергаем. Редирект на этом шаге
        // выбрасывал бы на профиль при каждом заходе на защищённую страницу,
        // раньше чем сервер успеет ответить.
        if (permissions.isLoading) {
            return (
                <div className="min-h-screen bg-background flex flex-col items-center justify-center">
                    <Loader2 className="h-8 w-8 animate-spin text-primary opacity-50" />
                </div>
            );
        }
        // Права НЕ ЗАГРУЗИЛИСЬ — это не «прав нет», и путать их нельзя.
        // Доступ всё равно закрыт (отказ в закрытую), но человек должен
        // видеть причину: пустая карта из-за недоступной ручки выглядит ровно
        // как отсутствие прав, и разбираться идут не туда — искать роли
        // вместо того, чтобы чинить запрос.
        if (permissions.isError) {
            return (
                <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-4 px-6 text-center">
                    <p className="max-w-prose text-muted-foreground">
                        {t(
                            'auth.errors.permissionsUnavailable',
                            'Не удалось получить права доступа. Раздел закрыт не потому, что прав нет, '
                            + 'а потому, что их не удалось спросить у сервера.',
                        )}
                    </p>
                    <button
                        onClick={() => permissions.refetch()}
                        className="rounded-full border px-5 py-2 text-sm font-medium transition-colors hover:bg-accent"
                    >
                        {t('common.retry')}
                    </button>
                </div>
            );
        }
        if (!permissions.atLeast(requires.module, requires.level)) {
            // Отправляем в безопасное место, а не по кругу на /login: профиль —
            // универсальная посадочная страница «вы вошли».
            return <Navigate to="/myprofile" replace state={{ from: location, accessDenied: true }} />;
        }
    }

    return children;
};

export default RequireAuth;
