import React, { useState } from 'react';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Button } from '@/components/ui/button';
import api from '@/api/client';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';

const AdminProjects = () => {
  const [message, setMessage] = useState<string | null>(null);
  const { t } = useTranslation();

  // Placeholder: backend projects API not implemented in this repo.
  // Provide simple UI to create a local placeholder entry or explain next steps.
  const handleCreatePlaceholder = async () => {
    try {
      // If you have an API endpoint, replace this with api.post('projects/', data)
      setMessage('Создание проекта не настроено на бэкенде. Добавьте endpoint /api/projects/ чтобы управлять проектами.');
    } catch (err) {
      console.error(err);
      setMessage('Ошибка при запросе к API. Проверьте права и токен.');
    }
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Header />
      <main className="flex-1 container mx-auto px-4 py-8">
        <div className="mb-6 flex flex-col gap-4">
          <Link
            to="/myprofile"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
          >
            <ArrowLeft className="h-4 w-4" />
            {t('hr.backToMain', 'Назад в профиль')}
          </Link>
          <h1 className="text-3xl font-bold">Управление проектами (скелет)</h1>
        </div>
        <div className="bg-card rounded-lg border p-6">
          <p className="mb-4">На этом сервере пока не реализован API для управления проектами.</p>
          <div className="flex gap-2">
            <Button onClick={handleCreatePlaceholder}>Создать тестовый placeholder</Button>
          </div>
          {message && <div className="mt-4 text-sm text-muted-foreground">{message}</div>}
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default AdminProjects;
