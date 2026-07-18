import { useTranslation } from 'react-i18next';
import { MapPin, Phone, User } from 'lucide-react';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { useLanguageTransition } from '@/hooks/use-language-transition';
import { offices, affiliatedCompany, type Office } from '@/data/contacts';

const OfficeCard = ({ office }: { office: Office }) => {
  const { t } = useTranslation();

  return (
    <div className="bg-card rounded-2xl shadow-elevated overflow-hidden flex flex-col">
      {/* TODO: Вставить карту (Google Maps / Yandex Maps) для адреса этого офиса */}
      <div className="h-48 bg-muted flex items-center justify-center">
        <div className="text-center text-muted-foreground">
          <MapPin size={32} className="mx-auto mb-2 opacity-40" />
          <span className="text-sm opacity-60">{t('contacts_page.map_placeholder')}</span>
        </div>
      </div>

      <div className="p-6 flex-1">
        <h3 className="font-display text-xl font-bold text-foreground mb-3">{t(office.nameKey)}</h3>
        <div className="flex items-start gap-2 text-muted-foreground text-sm">
          <MapPin size={16} className="mt-0.5 shrink-0 text-secondary" />
          <span>{t(office.addressKey)}</span>
        </div>

        <div className="mt-6">
          <p className="text-xs font-semibold uppercase tracking-wider text-secondary mb-3">
            {t('contacts_page.contacts')}
          </p>
          {office.contacts.map((contact, i) => (
            <div key={i} className={`flex items-start gap-3 py-3 ${i > 0 ? 'border-t border-accent' : ''}`}>
              <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <User size={16} className="text-primary" />
              </div>
              <div>
                <p className="font-medium text-foreground text-sm">{t(contact.positionKey)}</p>
                <a
                  href={`tel:${contact.phone.replace(/[^\d+]/g, '')}`}
                  className="text-muted-foreground text-sm flex items-center gap-1.5 mt-0.5 hover:text-primary transition-colors"
                >
                  <Phone size={13} className="text-secondary" />
                  {contact.phone}
                </a>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const Contacts = () => {
  const { t } = useTranslation();
  const isChanging = useLanguageTransition();

  return (
    <div className={`min-h-screen language-transition ${isChanging ? 'language-changing' : ''}`}>
      <Header />

      {/* Hero */}
      <section className="py-24 bg-background">
        <div className="container-custom text-center">
          <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('contacts_page.tag')}</span>
          <h1 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2">
            {t('contacts_page.title')}
          </h1>
          <p className="text-muted-foreground text-lg mt-4 max-w-2xl mx-auto">
            {t('contacts_page.subtitle')}
          </p>
        </div>
      </section>

      {/* Наши офисы */}
      <section className="py-16 bg-accent">
        <div className="container-custom">
          <h2 className="font-display text-3xl font-bold text-foreground mb-12 text-center">
            {t('contacts_page.our_offices')}
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            {offices.map((office) => (
              <OfficeCard key={office.id} office={office} />
            ))}
          </div>
        </div>
      </section>

      {/* Аффилированная компания */}
      <section className="py-16 bg-background">
        <div className="container-custom">
          <div className="max-w-5xl mx-auto">
            <h2 className="font-display text-3xl font-bold text-foreground mb-4 text-center">
              {t('contacts_page.affiliated_company')}
            </h2>
            <p className="text-muted-foreground text-center mb-12 max-w-2xl mx-auto">
              {t(affiliatedCompany.descriptionKey)}
            </p>
            <div className="grid lg:grid-cols-2 gap-8 items-start">
              {/* Информация о компании */}
              <div className="bg-card rounded-2xl shadow-elevated p-8">
                <h3 className="font-display text-2xl font-bold text-foreground mb-4">
                  {t(affiliatedCompany.nameKey)}
                </h3>
                <p className="text-muted-foreground leading-relaxed">
                  {t(affiliatedCompany.detailsKey)}
                </p>
                {affiliatedCompany.tagKeys.length > 0 && (
                  <div className="mt-6 flex flex-wrap gap-2">
                    {affiliatedCompany.tagKeys.map((tagKey, i) => (
                      <span
                        key={i}
                        className="inline-flex px-3 py-1.5 rounded-full text-xs font-medium bg-primary/10 text-primary"
                      >
                        {t(tagKey)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {/* Блок офиса аффилированной компании */}
              <OfficeCard office={affiliatedCompany.office} />
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default Contacts;
