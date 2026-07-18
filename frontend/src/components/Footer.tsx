import { useTranslation } from 'react-i18next';
import { Leaf, Mail, MapPin, Phone } from 'lucide-react';

const logo = '/images/logo.webp';

export const Footer = () => {
  const { t } = useTranslation();

  const footerLinks = {
    company: [
      { label: t('header.about'), href: '#about' },
      { label: t('header.projects'), href: '/projects' },
      { label: t('header.services'), href: '/services' },
      { label: t('header.news'), href: '#news' },
    ],
    services: [
      { label: t('services.items.owners_engineer.title'), href: '#' },
      { label: t('services.items.pot.title'), href: '#' },
      { label: t('services.items.construction.title'), href: '#' },
      { label: t('services.items.maintenance.title'), href: '#' },
    ],
  };

  return (
    <footer className="bg-foreground text-background">
      {/* Main Footer */}
      <div className="container-custom py-16">
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-12">
          {/* Brand */}
          <div className="lg:col-span-1">
            {/* Brand */}<a href="#" className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-full bg-white flex items-center justify-center overflow-hidden">
                <img src={logo} alt="Logo" width={40} height={40} className="w-full h-full object-contain" />
              </div>
              <div>
                <span className="font-display font-bold text-xl text-background">Hi-Tech Group</span>
              </div>
              {/* Brand */}</a>
            <p className="text-background/60 text-sm leading-relaxed mb-6">
              {t('footer.tagline')}
            </p>
            <div className="flex gap-4">
              {['linkedin', 'twitter', 'facebook'].map((social) => (
                <a
                  key={social}
                  href="#"
                  className="w-10 h-10 rounded-full bg-background/10 flex items-center justify-center hover:bg-secondary transition-colors"
                >
                  <span className="sr-only">{social}</span>
                  <div className="w-4 h-4 bg-background/60 rounded-sm" />
                </a>
              ))}
            </div>
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
      <div className="border-t border-background/10">
        <div className="container-custom py-6 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-background/40 text-sm">
            © 2026 Hi-Tech Group. {t('footer.rights')}
          </p>
          <div className="flex gap-6">
            <a href="#" className="text-background/40 hover:text-background/80 transition-colors text-sm">
              {t('footer.privacy')}
            </a>
            <a href="#" className="text-background/40 hover:text-background/80 transition-colors text-sm">
              {t('footer.terms')}
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
};
