import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import { toast } from "sonner";

// Schema definition moved inside component to support i18n

const Register = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const [isLoading, setIsLoading] = useState(false);

    const registerSchema = z.object({
        fullName: z.string().min(3, t('auth.errors.fullNameMin')),
        email: z.string().email(t('auth.errors.emailInvalid')),
        password: z.string().min(6, t('auth.errors.passwordMin')),
        confirmPassword: z.string()
    }).refine((data) => data.password === data.confirmPassword, {
        message: t('auth.errors.passwordMatch'),
        path: ["confirmPassword"],
    });

    type RegisterFormData = z.infer<typeof registerSchema>;

    const form = useForm<RegisterFormData>({
        resolver: zodResolver(registerSchema),
        defaultValues: {
            fullName: "",
            email: "",
            password: "",
            confirmPassword: ""
        }
    });

    const onSubmit = async (data: RegisterFormData) => {
        setIsLoading(true);
        try {
            await api.post('users/v1/register/', {
                full_name: data.fullName,
                email: data.email,
                password: data.password
            });
            toast.success(t('auth.pendingApproval'));
            navigate('/login');
        } catch (error) {
            console.error(error);
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const responseData = (error as any).response?.data || {};
            const msg =
                responseData.full_name?.[0] ||
                responseData.email?.[0] ||
                responseData.detail ||
                t('auth.failed');
            toast.error(msg);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8 flex items-center justify-center">
                <div className="w-full max-w-md">
                    <h1 className="text-3xl font-bold mb-6 text-center">{t('auth.register')}</h1>
                    <Form {...form}>
                        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                            <FormField
                                control={form.control}
                                name="fullName"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('auth.fullName')}</FormLabel>
                                        <FormControl>
                                            <Input {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="email"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('auth.email')}</FormLabel>
                                        <FormControl>
                                            <Input type="email" {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="password"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('auth.password')}</FormLabel>
                                        <FormControl>
                                            <Input type="password" {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="confirmPassword"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('auth.confirmPassword')}</FormLabel>
                                        <FormControl>
                                            <Input type="password" {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <Button type="submit" className="w-full" disabled={isLoading}>
                                {isLoading ? t('auth.registering') : t('auth.register')}
                            </Button>
                        </form>
                    </Form>
                    <p className="mt-4 text-center text-sm">
                        {t('auth.alreadyAccount')} <Link to="/login" className="text-primary hover:underline">{t('auth.loginHere')}</Link>
                    </p>
                </div>
            </main>
            <Footer />
        </div>
    );
};

export default Register;
