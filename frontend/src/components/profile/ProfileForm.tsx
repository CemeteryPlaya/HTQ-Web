import React from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslation } from 'react-i18next';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PhoneInput } from "@/components/ui/phone-input";
import { Textarea } from "@/components/ui/textarea";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { UserProfile, ProfileFormData } from '../../types/userProfile';

// Schema moved inside component for i18n

interface ProfileFormProps {
    profile: UserProfile;
    onSubmit: (data: ProfileFormData) => void;
    isLoading?: boolean;
}

export const ProfileForm: React.FC<ProfileFormProps> = ({ profile, onSubmit, isLoading }) => {
    const { t } = useTranslation();

    const profileSchema = z.object({
        firstName: z.string().max(100).optional(),
        lastName: z.string().max(100).optional(),
        patronymic: z.string().max(100).optional(),
        phone: z.string().max(30).optional(),
        display_name: z.string().min(2, t('profile.errors.nameMin')).max(100),
        bio: z.string().max(1000).optional(),
        settings: z.object({
            language: z.string().optional(),
            timezone: z.string().optional()
        }).optional()
    });

    const form = useForm<z.infer<typeof profileSchema>>({
        resolver: zodResolver(profileSchema),
        defaultValues: {
            firstName: profile.firstName || "",
            lastName: profile.lastName || "",
            patronymic: profile.patronymic || "",
            phone: profile.phone || "",
            display_name: profile.display_name || "",
            bio: profile.bio || "",
            settings: profile.settings || {}
        }
    });

    const handleSubmit = (data: z.infer<typeof profileSchema>) => {
        // Adapt to ProfileFormData which might include avatar file separately 
        // (but this form handles text fields only for now, avatar is separate or needs integration)
        onSubmit(data as ProfileFormData);
    };

    return (
        <Form {...form}>
            <form onSubmit={form.handleSubmit(handleSubmit)} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <FormField
                        control={form.control}
                        name="lastName"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>{t('profile.lastName')}</FormLabel>
                                <FormControl>
                                    <Input {...field} placeholder={t('profile.lastNamePlaceholder')} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="firstName"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>{t('profile.firstName')}</FormLabel>
                                <FormControl>
                                    <Input {...field} placeholder={t('profile.firstNamePlaceholder')} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="patronymic"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>{t('profile.patronymic')}</FormLabel>
                                <FormControl>
                                    <Input {...field} placeholder={t('profile.patronymicPlaceholder')} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField
                        control={form.control}
                        name="display_name"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>{t('profile.displayName')}</FormLabel>
                                <FormControl>
                                    <Input {...field} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="phone"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>Телефон</FormLabel>
                                <FormControl>
                                    <PhoneInput {...field} value={field.value || ''} />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                </div>

                <FormField
                    control={form.control}
                    name="bio"
                    render={({ field }) => (
                        <FormItem>
                            <FormLabel>{t('profile.bio')}</FormLabel>
                            <FormControl>
                                <Textarea {...field} className="min-h-[100px]" />
                            </FormControl>
                            <FormMessage />
                        </FormItem>
                    )}
                />

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <FormField
                        control={form.control}
                        name="settings.language"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>{t('profile.language')}</FormLabel>
                                <FormControl>
                                    <Input {...field} placeholder="en" />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                    <FormField
                        control={form.control}
                        name="settings.timezone"
                        render={({ field }) => (
                            <FormItem>
                                <FormLabel>{t('profile.timezone')}</FormLabel>
                                <FormControl>
                                    <Input {...field} placeholder="UTC" />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )}
                    />
                </div>

                <div className="flex justify-end gap-4">
                    <Button type="submit" disabled={isLoading}>
                        {isLoading ? t('profile.saving') : t('profile.save')}
                    </Button>
                </div>
            </form>
        </Form>
    );
};
