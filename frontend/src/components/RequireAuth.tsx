import { Navigate, useLocation } from "react-router-dom";
import type { AxiosError } from "axios";
import { ForcePasswordChange } from "./ForcePasswordChange";
import { Loader2 } from "lucide-react";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { hasAnyRole, HR_ROLES, EDITOR_ROLES } from "@/lib/auth/roles";
import type { RouteRole } from "@/app/routing/types";
import { useTranslation } from 'react-i18next';

// Admin/superuser is always allowed everywhere; staff is admin-equivalent on
// the user-service side (every admin endpoint accepts ``is_staff OR is_superuser``),
// so we mirror that here. Each bucket explicitly includes ``admin`` /
// ``superuser`` / ``staff`` so the gate stays self-evident — no clever
// fallbacks needed.
const ALWAYS_ALLOWED = ['admin', 'superuser', 'staff'] as const;

const ROLE_BUCKETS: Record<RouteRole, readonly string[]> = {
    admin: ALWAYS_ALLOWED,
    hr: [...ALWAYS_ALLOWED, ...HR_ROLES.filter((r) => !ALWAYS_ALLOWED.includes(r as any))],
    editor: [...ALWAYS_ALLOWED, ...EDITOR_ROLES.filter((r) => !ALWAYS_ALLOWED.includes(r as any))],
};

interface RequireAuthProps {
    children: JSX.Element;
    requiredRole?: RouteRole;
}

const RequireAuth = ({ children, requiredRole }: RequireAuthProps) => {
    const { t } = useTranslation();
    const location = useLocation();
    const { activeProfile, isLoading, error, isLoggedIn, clearAuthStorage, refetch } = useActiveProfile({
        retry: false,
    });

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

    // Role gate. This is a UX guard — the backend enforces the same checks
    // on every API call, so a brief stale-cache window can't actually leak
    // privileged data. Re-render fires automatically when the fresh profile
    // fetch resolves and demotes a user.
    if (requiredRole) {
        const allowed = ROLE_BUCKETS[requiredRole];
        const profileRoles = activeProfile?.roles ?? [];
        if (!hasAnyRole(profileRoles, allowed)) {
            // Send them somewhere safe instead of looping on /login. Profile
            // is the universal "you're logged in" landing.
            return <Navigate to="/myprofile" replace state={{ from: location, accessDenied: true }} />;
        }
    }

    return children;
};

export default RequireAuth;
