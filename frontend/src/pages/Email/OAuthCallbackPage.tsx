import React, { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { emailService } from '@/services/emailService';
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';

export default function OAuthCallbackPage() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [searchParams] = useSearchParams();
    const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
    const [errorMessage, setErrorMessage] = useState<string | null>(null);
    // The OAuth `code` is single-use — guard against StrictMode double-mount.
    const startedRef = useRef(false);

    useEffect(() => {
        if (startedRef.current) return;
        startedRef.current = true;

        const handleCallback = async () => {
            const code = searchParams.get('code');
            const state = searchParams.get('state');
            const error = searchParams.get('error');

            if (error) {
                setStatus('error');
                setErrorMessage(t('email.oauth.providerError', { error }));
                return;
            }

            if (!code || !state) {
                setStatus('error');
                setErrorMessage(t('email.oauth.missingParams'));
                return;
            }

            try {
                const result = await emailService.handleOAuthCallback(code, state);
                // Refresh the account selector so the new mailbox appears at once.
                await queryClient.invalidateQueries({ queryKey: ['email', 'accounts'] });
                setStatus('success');
                setTimeout(() => {
                    navigate(`/email?account=${result.account_id}`);
                }, 1500);
            } catch (err: any) {
                console.error('OAuth callback failed', err);
                setStatus('error');
                setErrorMessage(
                    err.response?.data?.detail ||
                        err.response?.data?.error ||
                        t('email.oauth.failed'),
                );
            }
        };

        handleCallback();
    }, [searchParams, navigate, queryClient, t]);

    return (
        <div className="min-h-screen flex items-center justify-center bg-muted/20">
            <div className="max-w-md w-full bg-background border rounded-2xl shadow-xl p-8 text-center space-y-6 animate-in fade-in zoom-in duration-300">
                {status === 'loading' && (
                    <>
                        <div className="flex justify-center">
                            <Loader2 className="h-16 w-16 text-primary animate-spin" />
                        </div>
                        <h1 className="text-2xl font-bold">{t('email.oauth.authorizing')}</h1>
                        <p className="text-muted-foreground">
                            {t('email.oauth.contacting')}
                        </p>
                    </>
                )}

                {status === 'success' && (
                    <>
                        <div className="flex justify-center">
                            <div className="bg-green-100 text-green-600 p-4 rounded-full">
                                <CheckCircle2 className="h-12 w-12" />
                            </div>
                        </div>
                        <h1 className="text-2xl font-bold">{t('email.oauth.connected')}</h1>
                        <p className="text-muted-foreground">
                            {t('email.oauth.connectedHint')}
                        </p>
                        <p className="text-xs text-muted-foreground pt-4">
                            {t('email.oauth.redirecting')}
                        </p>
                    </>
                )}

                {status === 'error' && (
                    <>
                        <div className="flex justify-center">
                            <div className="bg-destructive/10 text-destructive p-4 rounded-full">
                                <XCircle className="h-12 w-12" />
                            </div>
                        </div>
                        <h1 className="text-2xl font-bold">{t('email.oauth.errorTitle')}</h1>
                        <p className="text-destructive font-medium">{errorMessage}</p>
                        <div className="pt-4">
                            <Button onClick={() => navigate('/email')} className="w-full">
                                {t('email.oauth.backToMail')}
                            </Button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}
