import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { LogOut, Settings as SettingsIcon, Shield, Building, Briefcase } from 'lucide-react';
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

    const displayName = profile.fio || profile.display_name || profile.firstName || profile.email;

    return (
        <Card className="relative overflow-hidden rounded-3xl border bg-card shadow-sm transition-all duration-300 hover:shadow-md">
            {/* Subtle header accent banner */}
            <div className="h-24 bg-linear-to-r from-primary/15 via-primary/5 to-accent/20 border-b border-border/40" />

            <CardContent className="px-6 pb-6 pt-0">
                <div className="flex flex-col md:flex-row items-center md:items-end gap-6 -mt-12">
                    {/* Avatar with wrapper */}
                    <div className="shrink-0 relative">
                        <ProfileAvatar
                            avatarUrl={profile.avatarUrl}
                            firstName={displayName}
                            onAvatarChange={onAvatarChange ?? (() => {})}
                        />
                    </div>

                    {/* User Info */}
                    <div className="text-center md:text-left flex-1 space-y-2 pb-1">
                        <div className="flex flex-col md:flex-row md:items-center justify-center md:justify-start gap-2">
                            <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground">{displayName}</h2>
                            {isStaff && (
                                <Badge variant="default" className="w-fit mx-auto md:mx-0 gap-1 text-[11px] font-semibold bg-primary/90">
                                    <Shield className="h-3 w-3" />
                                    Staff
                                </Badge>
                            )}
                        </div>

                        <p className="text-sm text-muted-foreground font-medium">{profile.email}</p>

                        {/* Department & Position if available */}
                        {(profile.department || profile.position) && (
                            <div className="flex flex-wrap items-center justify-center md:justify-start gap-2 text-xs text-muted-foreground pt-1">
                                {profile.department && (
                                    <span className="flex items-center gap-1.5 bg-muted/60 px-2.5 py-1 rounded-md font-medium">
                                        <Building className="h-3.5 w-3.5 text-primary shrink-0" />
                                        <span>{profile.department}</span>
                                    </span>
                                )}
                                {profile.position && (
                                    <span className="flex items-center gap-1.5 bg-muted/60 px-2.5 py-1 rounded-md font-medium">
                                        <Briefcase className="h-3.5 w-3.5 text-primary shrink-0" />
                                        <span>{profile.position}</span>
                                    </span>
                                )}
                            </div>
                        )}

                        {/* Roles Badges */}
                        {profile.roles && profile.roles.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 justify-center md:justify-start pt-1">
                                {profile.roles.map(role => (
                                    <Badge key={role} variant="outline" className="text-[10px] font-mono capitalize">
                                        {role}
                                    </Badge>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Actions */}
                    <div className="flex flex-row md:flex-col gap-2.5 w-full md:w-auto shrink-0 pt-3 md:pt-0">
                        <Button asChild variant="outline" size="sm" className="flex-1 md:flex-initial gap-2 rounded-xl h-10 active:scale-95 transition-all">
                            <Link to="/settings">
                                <SettingsIcon className="h-4 w-4 text-muted-foreground" />
                                <span>{t('profile.sidebar.settings')}</span>
                            </Link>
                        </Button>
                        {onLogout && (
                            <Button variant="ghost" size="sm" onClick={onLogout} className="flex-1 md:flex-initial gap-2 text-destructive hover:text-destructive hover:bg-destructive/10 rounded-xl h-10 active:scale-95 transition-all">
                                <LogOut className="h-4 w-4" />
                                <span>{t('profile.logout')}</span>
                            </Button>
                        )}
                    </div>
                </div>
            </CardContent>
        </Card>
    );
};
