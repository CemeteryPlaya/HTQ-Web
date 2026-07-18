import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogOut, Settings as SettingsIcon } from 'lucide-react';
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ProfileAvatar } from './ProfileAvatar';
import { UserProfile } from '../../types/userProfile';

interface ProfileHeaderProps {
    profile: UserProfile;
    onAvatarChange?: (file: Blob) => void;
    onLogout?: () => void;
}

export const ProfileHeader: React.FC<ProfileHeaderProps> = ({ profile, onAvatarChange, onLogout }) => {
    const { t } = useTranslation();
    const isStaff = Boolean(
        (profile as any).user?.is_staff || profile.roles?.includes('staff') || profile.roles?.includes('admin'),
    );

    return (
        <Card className="mb-6">
            <CardContent className="pt-6 flex flex-col md:flex-row items-center gap-6">
                <ProfileAvatar
                    avatarUrl={profile.avatarUrl}
                    firstName={profile.fio || profile.display_name || profile.firstName}
                    onAvatarChange={onAvatarChange ?? (() => {})}
                />
                <div className="text-center md:text-left flex-1 space-y-2">
                    <h2 className="text-2xl font-bold">{profile.fio || profile.display_name || profile.email}</h2>
                    <p className="text-muted-foreground">{profile.email}</p>
                    <div className="flex flex-wrap gap-2 justify-center md:justify-start">
                        {(profile.roles ?? []).map(role => (
                            <Badge key={role} variant="secondary">{role}</Badge>
                        ))}
                        <Badge variant={isStaff ? 'default' : 'outline'}>
                            {t('profile.staffLabel')}: {isStaff ? t('profile.yes') : t('profile.no')}
                        </Badge>
                    </div>
                </div>
                <div className="flex flex-col gap-2 w-full md:w-auto">
                    <Button asChild variant="outline" size="sm">
                        <Link to="/settings" className="flex items-center gap-2">
                            <SettingsIcon className="h-4 w-4" />
                            {t('profile.sidebar.settings')}
                        </Link>
                    </Button>
                    {onLogout && (
                        <Button variant="destructive" size="sm" onClick={onLogout} className="flex items-center gap-2">
                            <LogOut className="h-4 w-4" />
                            {t('profile.logout')}
                        </Button>
                    )}
                </div>
            </CardContent>
        </Card>
    );
};
