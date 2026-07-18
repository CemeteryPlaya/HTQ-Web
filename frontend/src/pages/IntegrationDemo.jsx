import React, { useState, useEffect } from 'react';
import LoginForm from '../components/LoginForm';
import ItemsList from '../components/ItemsList';
import ItemCreate from '../components/ItemCreate';
import { Header } from '../components/Header';
import { useLanguageTransition } from '../hooks/use-language-transition';
import { clearAuthStorage, getAccessToken } from '@/lib/auth/profileStorage';

const IntegrationDemo = () => {
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const isChanging = useLanguageTransition();

    useEffect(() => {
        const token = getAccessToken();
        if (token) {
            setIsLoggedIn(true);
        }
    }, []);

    const handleLogin = () => {
        setIsLoggedIn(true);
    };

    const handleLogout = () => {
        clearAuthStorage();
        setIsLoggedIn(false);
    };

    return (
        <div className={`min-h-screen language-transition ${isChanging ? 'language-changing' : ''}`}>
            <Header />
            <div className="container mx-auto p-4 pt-24">
                <h1 className="text-3xl font-bold mb-6 text-center">FastAPI + React Integration Demo</h1>

                {!isLoggedIn ? (
                    <LoginForm onLogin={handleLogin} />
                ) : (
                    <div>
                        <div className="flex justify-between items-center mb-6">
                            <h2 className="text-2xl">Welcome!</h2>
                            <button
                                onClick={handleLogout}
                                className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600"
                            >
                                Logout
                            </button>
                        </div>
                        <div className="grid md:grid-cols-2 gap-8">
                            <ItemCreate onItemCreated={() => window.location.reload()} />
                            <ItemsList />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default IntegrationDemo;
