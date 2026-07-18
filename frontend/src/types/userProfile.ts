export interface AvatarMeta {
    /** Media-service file id (UUID), or `null` for legacy/external avatars. */
    id: string | null;
    /** Canonical download URL for the original. */
    url: string;
    /**
     * Map of variant-name → URL (e.g., ``thumb_32`` / ``thumb_96`` / ``thumb_256``).
     * May be empty right after upload while the worker is generating variants —
     * fall back to ``url`` in that case.
     */
    variants: Record<string, string>;
}

export interface UserProfile {
    id: string;
    email: string;
    firstName?: string;
    lastName?: string;
    patronymic?: string;
    phone?: string;
    fio?: string;
    display_name: string;
    bio: string;
    avatarUrl?: string; // Legacy URL — kept for components that haven't migrated to `avatar`.
    /** Structured avatar block — preferred over avatarUrl for new code. */
    avatar?: AvatarMeta | null;
    /** For upload (mutation input only — never present on a fetched profile). */
    avatarUpload?: Blob | null;
    roles: string[];
    settings: {
        language?: string;
        timezone?: string;
    };
    department?: string;
    department_id?: number;
    position?: string;
    must_change_password?: boolean;
    created_at: string;
    updated_at: string;
}

export interface ProfileFormData {
    firstName?: string;
    lastName?: string;
    patronymic?: string;
    phone?: string;
    display_name: string;
    bio: string;
    settings: {
        language?: string;
        timezone?: string;
    };
    avatar?: FileList;
}
