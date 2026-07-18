import React from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import LoginForm from '../components/LoginForm';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';

const Login = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const location = useLocation();
    const from = location.state?.from?.pathname || "/myprofile";

    const handleLogin = () => {
        navigate(from, { replace: true });
    };

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8 flex items-center justify-center">
                <div className="w-full max-w-md">
                    <h1 className="text-3xl font-bold mb-6 text-center">{t('auth.signIn')}</h1>
                    <LoginForm onLogin={handleLogin} />
                    <p className="mt-4 text-center text-sm">
                        {t('auth.noAccount')} <Link to="/register" className="text-primary hover:underline">{t('auth.registerHere')}</Link>
                    </p>
                </div>
            </main>
            <Footer />
        </div>
    );
};

export default Login;
