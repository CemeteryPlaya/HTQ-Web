import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Mail, MapPin, Phone } from 'lucide-react';
import { legalLinks, socialLinks } from '@/data/company';
import { services } from '@/data/services';

const logo = '/images/logo.webp';

export const Footer = () => {
  const { t } = useTranslation();

  const footerLinks = {
    // Футер рендерится на всех страницах, поэтому якоря главной пишем как
    // ``/#...`` — голый ``#about`` за пределами ``/`` никуда не ведёт.
    company: [
      { label: t('header.about'), href: '/#about' },
      { label: t('header.projects'), href: '/projects' },
      { label: t('header.services'), href: '/services' },
      { label: t('header.news'), href: '/#news' },
    ],
    // Ссылки ведут к соответствующим карточкам на странице услуг (якоря
    // ``id="service-N"`` объявлены в ``pages/Services.tsx``).
    services: services
      .filter((service) => service.featuredOnMain)
      .slice(0, 4)
      .map((service) => ({
        label: t(service.titleKey),
        href: `/services#service-${service.id}`,
      })),
  };

  return (
    <footer className="bg-foreground text-background">
      {/* Main Footer */}
      <div className="container-custom py-16">
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-12">
          {/* Brand */}
          <div className="lg:col-span-1">
            <Link to="/" className="flex min-h-[44px] min-w-[44px] items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-full bg-white flex items-center justify-center overflow-hidden">
                <img src={logo} alt="Logo" width={40} height={40} className="w-full h-full object-contain" />
              </div>
              <div>
                <span className="font-display font-bold text-xl text-background">Hi-Tech Group</span>
              </div>
            </Link>
            <p className="text-background/60 text-sm leading-relaxed mb-6">
              {t('footer.tagline')}
            </p>
            {socialLinks.length > 0 && (
              <div className="flex gap-4">
                {socialLinks.map((social) => (
                  <a
                    key={social.href}
                    href={social.href}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="w-10 h-10 rounded-full bg-background/10 flex items-center justify-center hover:bg-secondary transition-colors text-background/60 text-sm font-semibold"
                  >
                    <span className="sr-only">{social.name}</span>
                    <span aria-hidden="true">{social.name.charAt(0).toUpperCase()}</span>
                  </a>
                ))}
              </div>
            )}
          </div>

          {/* Company Links */}
          <div>
            <h4 className="font-display font-semibold text-background mb-6">{t('footer.company')}</h4>
            <ul className="space-y-3">
              {footerLinks.company.map((link) => (
                <li key={link.label}>
                  <a href={link.href} className="text-background/60 hover:text-secondary transition-colors text-sm">
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Services Links */}
          <div>
            <h4 className="font-display font-semibold text-background mb-6">{t('footer.services')}</h4>
            <ul className="space-y-3">
              {footerLinks.services.map((link) => (
                <li key={link.label}>
                  <a href={link.href} className="text-background/60 hover:text-secondary transition-colors text-sm">
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          {/* Contact */}
          <div>
            <h4 className="font-display font-semibold text-background mb-6">{t('footer.contact')}</h4>
            <ul className="space-y-4">
              <li className="flex items-start gap-3">
                <MapPin size={18} className="text-secondary flex-shrink-0 mt-0.5" />
                <span className="text-background/60 text-sm">{t('contact.info.location')}</span>
              </li>
              <li className="flex items-start gap-3">
                <Mail size={18} className="text-secondary flex-shrink-0 mt-0.5" />
                <a href="mailto:info@hi-techkz.com" className="text-background/60 hover:text-secondary transition-colors text-sm">
                  info@hi-techkz.com
                </a>
              </li>
              <li className="flex items-start gap-3">
                <Phone size={18} className="text-secondary flex-shrink-0 mt-0.5" />
                <a href="tel:+77271234567" className="text-background/60 hover:text-secondary transition-colors text-sm">
                  +7 (727) 123-4567
                </a>
              </li>
            </ul>
          </div>
        </div>
      </div>

      {/* Bottom Bar */}
      {/* Отступ снизу нужен вдобавок к распорке из BottomNav: шеллы страниц
          свёрстаны как `min-h-screen flex flex-col`, поэтому на коротком экране
          футер прижат ровно к низу вьюпорта, а распорка уходит уже за него —
          и нижняя панель накрывала последние ссылки футера. */}
      <div className="border-t border-background/10 pb-20 md:pb-0">
        <div className="container-custom py-6 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-background/40 text-sm text-center md:text-left">
            © {new Date().getFullYear()} Hi-Tech Group. {t('footer.rights')}
          </p>
          {legalLinks.length > 0 && (
            <div className="flex flex-wrap justify-center gap-4 sm:gap-6">
              {legalLinks.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  className="text-background/40 hover:text-background/80 transition-colors text-sm py-1.5 px-2 rounded-lg"
                >
                  {t(link.labelKey)}
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </footer>
  );
};
