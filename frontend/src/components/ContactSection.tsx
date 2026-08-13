import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight, Mail, MapPin, Phone } from 'lucide-react';
import { Button } from './ui/button';
import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import { useToast } from '@/hooks/use-toast';

export const ContactSection = () => {
  const { t } = useTranslation();

  return (
    <section id="contact" className="section-padding bg-primary relative overflow-hidden">
      {/* Background decoration */}
      <div className="absolute inset-0 opacity-10">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full border border-primary-foreground" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full border border-primary-foreground" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[400px] h-[400px] rounded-full border border-primary-foreground" />
      </div>

      <div className="container-custom relative z-10">
        <div className="grid lg:grid-cols-2 gap-8 sm:gap-12 lg:gap-20 items-center">
          {/* Left Content */}
          {/* `min-w-0`: без него grid-элемент растягивается до max-content строк
              с контактами (иконка 48px + нередуцируемый текст), и весь столбец
              вылезает за экран — `truncate` внутри при этом не срабатывает. */}
          <div className="min-w-0">
            <span className="text-secondary font-semibold text-xs sm:text-sm uppercase tracking-wider">{t('contact.tag')}</span>
            <h2 className="font-display text-3xl sm:text-4xl md:text-5xl lg:text-6xl font-bold text-primary-foreground mt-2 mb-4 sm:mb-6">
              {t('contact.title')}
            </h2>
            <p className="text-primary-foreground/80 text-base sm:text-lg leading-relaxed mb-6 sm:mb-8">
              {t('contact.desc')}
            </p>

            {/* Contact Info */}
            <div className="space-y-4">
              <div className="flex items-center gap-4 p-4 rounded-xl bg-primary-foreground/10 backdrop-blur">
                <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center shrink-0">
                  <MapPin className="text-secondary-foreground" size={20} />
                </div>
                <div className="min-w-0">
                  <p className="text-primary-foreground/60 text-xs sm:text-sm">{t('contact.info.address')}</p>
                  <p className="text-primary-foreground font-medium text-sm sm:text-base truncate">{t('contact.info.location')}</p>
                </div>
              </div>
              <a href="mailto:info@hi-techkz.com" className="flex items-center gap-4 p-4 rounded-xl bg-primary-foreground/10 backdrop-blur hover:bg-primary-foreground/20 transition-colors">
                <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center shrink-0">
                  <Mail className="text-secondary-foreground" size={20} />
                </div>
                <div className="min-w-0">
                  <p className="text-primary-foreground/60 text-xs sm:text-sm">{t('contact.info.email')}</p>
                  <p className="text-primary-foreground font-medium text-sm sm:text-base truncate">info@hi-techkz.com</p>
                </div>
              </a>
              <a href="tel:+77271234567" className="flex items-center gap-4 p-4 rounded-xl bg-primary-foreground/10 backdrop-blur hover:bg-primary-foreground/20 transition-colors">
                <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center shrink-0">
                  <Phone className="text-secondary-foreground" size={20} />
                </div>
                <div className="min-w-0">
                  <p className="text-primary-foreground/60 text-xs sm:text-sm">{t('contact.info.phone')}</p>
                  <p className="text-primary-foreground font-medium text-sm sm:text-base truncate">+7 (727) 123-4567</p>
                </div>
              </a>
            </div>
          </div>

          {/* Right - Form Card */}
          <div className="min-w-0 bg-card p-5 sm:p-8 md:p-10 rounded-2xl shadow-elevated">
            <h3 className="font-display text-xl sm:text-2xl font-bold text-foreground mb-6">
              {t('contact.form.title')}
            </h3>
            <FormFields />
          </div>
        </div>
      </div>
    </section>
  );
};

const FormFields = () => {
  const { t } = useTranslation();
  const toast = useToast();
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) {
      toast.toast({ title: t('contact.form.validation_email') || 'Email required' });
      return;
    }
    setLoading(true);
    try {
      await api.post(apiPath('cms', 'contact-requests/'), {
        first_name: firstName,
        last_name: lastName,
        email,
        message,
      });
      setFirstName('');
      setLastName('');
      setEmail('');
      setMessage('');
      toast.toast({ title: t('contact.form.sent') || 'Message sent', description: t('contact.form.thanks') || '' });
    } catch (err) {
      console.error('Contact submit error:', err);
      const status = (err as any)?.response?.status;
      const data = (err as any)?.response?.data;
      if (status) {
        toast.toast({ title: `Send failed (${status})`, description: JSON.stringify(data) });
      } else {
        toast.toast({ title: t('contact.form.send_failed') || 'Send failed', description: String(err) });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="space-y-4 sm:space-y-5" onSubmit={handleSubmit}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-5">
        <div>
          <label className="text-sm font-medium text-foreground mb-1.5 block">{t('contact.form.first_name')}</label>
          <input
            value={firstName}
            onChange={(e) => setFirstName(e.target.value)}
            type="text"
            placeholder="John"
            className="w-full px-4 py-3 min-h-[44px] rounded-lg bg-accent border border-border focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all text-base sm:text-sm"
          />
        </div>
        <div>
          <label className="text-sm font-medium text-foreground mb-1.5 block">{t('contact.form.last_name')}</label>
          <input
            value={lastName}
            onChange={(e) => setLastName(e.target.value)}
            type="text"
            placeholder="Doe"
            className="w-full px-4 py-3 min-h-[44px] rounded-lg bg-accent border border-border focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all text-base sm:text-sm"
          />
        </div>
      </div>
      <div>
        <label className="text-sm font-medium text-foreground mb-1.5 block">{t('contact.form.email')}</label>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          type="email"
          placeholder="john@example.com"
          className="w-full px-4 py-3 min-h-[44px] rounded-lg bg-accent border border-border focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all text-base sm:text-sm"
        />
      </div>
      <div>
        <label className="text-sm font-medium text-foreground mb-1.5 block">{t('contact.form.message')}</label>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={4}
          placeholder={t('contact.form.placeholder')}
          className="w-full px-4 py-3 rounded-lg bg-accent border border-border focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all resize-none text-base sm:text-sm"
        />
      </div>
      <Button type="submit" className="w-full btn-secondary rounded-xl text-base sm:text-lg min-h-[48px] group font-semibold shadow-soft" disabled={loading}>
        {t('contact.form.send')}
        <ArrowRight size={18} className="ml-2 transition-transform group-hover:translate-x-1" />
      </Button>
    </form>
  );
};
