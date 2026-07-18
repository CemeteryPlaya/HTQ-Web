import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../api/client';
import { usersApi } from '../api/users';
import { setAuthTokens } from '@/lib/auth/profileStorage';
import { logUserAction } from '@/lib/telemetry';

function LoginForm({ onLogin }) {
    const { t } = useTranslation();
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');

    const requestToken = async (loginId, userPassword) => {
        return await usersApi.getToken(loginId, userPassword);
    };

    const login = async (e) => {
        e.preventDefault();
        setError('');

        const loginId = email.trim();
        if (!loginId || !password) {
            setError('Введите email/телефон и пароль.');
            return;
        }

        try {
            const res = await requestToken(loginId, password);
            const accessToken =
                res?.data?.access ||
                res?.data?.access_token ||
                res?.data?.token ||
                '';

            if (!accessToken) {
                throw new Error('Token response does not contain access token');
            }

            setAuthTokens({
                access: accessToken,
                refresh: res?.data?.refresh,
            });

            logUserAction({ action: 'login_success', meta: { login_id: loginId } });

            if (onLogin) onLogin();
        } catch (err) {
            console.error('[LoginForm] Ошибка входа:', err);
            logUserAction({
                action: 'login_failed',
                meta: {
                    login_id: loginId,
                    status: err?.response?.status ?? err?.status ?? null,
                },
            });

            // Interceptor уже извлёк сообщение из тела ответа для 5xx ошибок
            if (err?.isServerError) {
                setError(err.message || 'Ошибка сервера. Попробуйте позже.');
                return;
            }

            const status = err?.response?.status ?? err?.status;
            if (status === 401) {
                setError('Неверный логин или пароль. Проверьте введённые данные.');
                return;
            }

            if (!status) {
                setError('Нет соединения с сервером авторизации. Проверьте сеть.');
                return;
            }

            // Показываем сообщение из тела ответа, если есть
            const body = err?.response?.data;
            if (body?.detail) {
                setError(String(body.detail));
            } else if (typeof body === 'string' && body) {
                setError(body);
            } else {
                setError(err?.message || 'Ошибка входа. Попробуйте позже.');
            }
        }
    };

    return (
        <form onSubmit={login} className="p-4 border rounded shadow-md max-w-sm mx-auto mt-4">
            <h2 className="text-xl mb-4">{t('auth.login')}</h2>
            {error && <p className="text-red-500 mb-2">{error}</p>}
            <div className="mb-4">
                <label className="block mb-1">{t('auth.emailOrPhone')}</label>
                <input
                    type="text"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full p-2 border rounded"
                    placeholder="email@example.com / +7..."
                />
            </div>
            <div className="mb-4">
                <label className="block mb-1">{t('auth.password')}</label>
                <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full p-2 border rounded"
                />
            </div>
            <button type="submit" className="w-full bg-blue-500 text-white p-2 rounded hover:bg-blue-600">
                {t('auth.login')}
            </button>
        </form>
    );
}

export default LoginForm;
