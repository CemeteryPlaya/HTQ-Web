import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useHomeSection } from '@/hooks/useHomeContent';
import { LucideIcon } from '@/components/ui/icon-picker';
import { legalLinks, socialLinks } from '@/data/company';
import { services } from '@/data/services';

const logo = '/images/logo.webp';

/**
 * Футер — теперь редактируется со страницы «Главная страница» (`/manage/home`),
 * а не программистом в коде. Пять секций ``footer-*`` заведены миграцией
 * `0011_seed_footer_sections` (см. её докстринг для полного разбора раскладки):
 * слоган, колонка «Компания», колонка «Услуги», колонка «Контакты» и нижняя
 * строка (копирайт + правовые ссылки).
 *
 * ОТКАТ НА ПРЕЖНИЙ ВИД ОБЯЗАТЕЛЕН: футер показывается на каждой публичной
 * странице, и пустой подвал из-за упавшего запроса или ещё не заполненной
 * секции — слишком дорогая цена. Поэтому по каждому блоку данные берутся из
 * БД, только если они там реально есть (``items.length`` для списков, иначе —
 * прежний статический список); тексты откатываются на i18n через `text()` —
 * ровно та же схема, что уже используют `StatsSection`/`AboutSection` и др.
 */
export const Footer = () => {
  const { t } = useTranslation();

  const brand = useHomeSection('footer-brand');
  const companyNav = useHomeSection('footer-company');
  const servicesNav = useHomeSection('footer-services');
  const contact = useHomeSection('footer-contact');
  const legal = useHomeSection('footer-legal');

  const fallbackLinks = {
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

  // CMS-элемент даёт готовую пару «текст + ссылка»; из БД берём список только
  // когда редактор его реально наполнил — иначе показываем прежний статический.
  const companyLinks = companyNav.items.length
    ? companyNav.items.map((i) => ({ label: i.title, href: i.link }))
    : fallbackLinks.company;
  const servicesLinks = servicesNav.items.length
    ? servicesNav.items.map((i) => ({ label: i.title, href: i.link }))
    : fallbackLinks.services;

  // Три контакта по умолчанию: адрес без ссылки (просто текст), почта и
  // телефон — с `mailto:`/`tel:`, уже собранными в поле `link` элемента.
  const fallbackContact = [
    { icon: 'MapPin', label: t('contact.info.location'), href: '' },
    { icon: 'Mail', label: 'info@hi-techkz.com', href: 'mailto:info@hi-techkz.com' },
    { icon: 'Phone', label: '+7 (727) 123-4567', href: 'tel:+77271234567' },
  ];
  const contactItems = contact.items.length
    ? contact.items.map((i) => ({ icon: i.icon, label: i.title, href: i.link }))
    : fallbackContact;

  const legalItems = legal.items.length
    ? legal.items.map((i) => ({ label: i.title, href: i.link }))
    : legalLinks.map((link) => ({ label: t(link.labelKey), href: link.href }));

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
              {brand.text('description', 'footer.tagline')}
            </p>
            {/* Соцсети намеренно остаются в коде (`data/company.ts`), а не в
                CMS: список сейчас пуст (реальных аккаунтов ещё нет), а редактор
                иконок блоков лендинга (`IconPicker`) отдаёт только набор
                lucide — логотипов соцсетей там нет, так что честно завести
                это поле в общую форму сейчас нечем. */}
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
            <h4 className="font-display font-semibold text-background mb-6">
              {companyNav.text('title', 'footer.company')}
            </h4>
            <ul className="space-y-3">
              {companyLinks.map((link) => (
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
            <h4 className="font-display font-semibold text-background mb-6">
              {servicesNav.text('title', 'footer.services')}
            </h4>
            <ul className="space-y-3">
              {servicesLinks.map((link) => (
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
            <h4 className="font-display font-semibold text-background mb-6">
              {contact.text('title', 'footer.contact')}
            </h4>
            <ul className="space-y-4">
              {contactItems.map((item) => (
                <li key={item.label} className="flex items-start gap-3">
                  {/* `LucideIcon` — тот же renderer по имени, что использует
                      сама CMS-форма (`ManageHomeSections.tsx`); статический
                      список задаёт те же имена (`MapPin`/`Mail`/`Phone`), так
                      что вид не меняется, пока редактор ничего не менял. */}
                  <span className="text-secondary flex-shrink-0 mt-0.5">
                    <LucideIcon name={item.icon} className="w-[18px] h-[18px]" />
                  </span>
                  {item.href ? (
                    <a href={item.href} className="text-background/60 hover:text-secondary transition-colors text-sm">
                      {item.label}
                    </a>
                  ) : (
                    <span className="text-background/60 text-sm">{item.label}</span>
                  )}
                </li>
              ))}
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
            © {new Date().getFullYear()} Hi-Tech Group. {legal.text('description', 'footer.rights')}
          </p>
          {legalItems.length > 0 && (
            <div className="flex flex-wrap justify-center gap-4 sm:gap-6">
              {legalItems.map((link) => (
                <a
                  key={link.label}
                  href={link.href}
                  className="text-background/40 hover:text-background/80 transition-colors text-sm py-1.5 px-2 rounded-lg"
                >
                  {link.label}
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </footer>
  );
};
