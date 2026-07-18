import { ArrowRight, ArrowUpRight, Zap, RefreshCw, FileCheck, ChevronRight, ChevronLeft, MapPin, Calendar, Mail, Phone, Linkedin } from 'lucide-react';

/**
 * DesignPreview — компромисс между текущим тёплым стилем и строгим preview.
 * Сохраняем фирменную тёплую палитру и приветливые формы,
 * но добавляем дисциплину: нумерованные секции, hairline-сетки,
 * крупные tabular-метрики, timeline, карта, серьёзный footer.
 * Все стили заскоупленны в .preview-scope.
 */
const DesignPreview = () => {
  return (
    <div className="preview-scope min-h-screen">
      <ScopedStyles />

      <PreviewHeader />
      <Hero />
      <DirectionsBlock />
      <ProjectsBlock />
      <ServicesBlock />
      <StatsBlock />
      <MissionBlock />
      <AboutTimeline />
      <PartnersCertificates />
      <NewsBlock />
      <ContactBlock />
      <PreviewFooter />
    </div>
  );
};

export default DesignPreview;

/* ─────────────────────────────────────────────────────────────────
 *  SCOPED STYLES — компромисс между текущей и строгой палитрой
 * ───────────────────────────────────────────────────────────────── */

const ScopedStyles = () => (
  <style>{`
    .preview-scope {
      /* Палитра — посередине между «текущей» и «препрева» */
      --p-primary: 148 42% 19%;        /* было 145 45% 22% (тек.) / 152 38% 16% (преп.) */
      --p-primary-soft: 148 32% 26%;
      --p-primary-deep: 148 45% 13%;
      --p-secondary: 40 78% 52%;       /* было 42 85% 55% / 38 60% 48% */
      --p-secondary-soft: 40 70% 65%;
      --p-secondary-fg: 210 14% 12%;
      --p-graphite: 210 14% 22%;
      --p-graphite-soft: 210 10% 45%;
      --p-surface: 145 18% 97%;        /* warm off-white */
      --p-surface-2: 145 14% 94%;
      --p-border: 145 10% 88%;
      --p-border-strong: 145 10% 78%;
      --p-on-dark-fg: 0 0% 100%;

      color: hsl(var(--p-graphite));
      font-family: 'Inter', system-ui, sans-serif;
    }

    /* Display — Outfit оставляем, но плотнее (tracking-tight) */
    .preview-scope .p-display {
      font-family: 'Outfit', 'Inter', sans-serif;
      font-weight: 700;
      letter-spacing: -0.022em;
      line-height: 1.08;
    }
    .preview-scope .p-display-xl { font-size: clamp(36px, 5vw, 66px); }
    .preview-scope .p-display-lg { font-size: clamp(28px, 3.4vw, 44px); }
    .preview-scope .p-display-md { font-size: clamp(22px, 2.2vw, 28px); }

    .preview-scope .p-numeric {
      font-variant-numeric: tabular-nums;
      font-feature-settings: 'tnum';
    }

    /* Eyebrow — мягкий tag-pill, но без анимации */
    .preview-scope .p-eyebrow-pill {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 7px 14px;
      border-radius: 999px;
      background: hsl(var(--p-primary) / 0.06);
      border: 1px solid hsl(var(--p-primary) / 0.12);
      color: hsl(var(--p-primary));
      font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .preview-scope .p-eyebrow-pill::before {
      content: '';
      width: 6px; height: 6px; border-radius: 50%;
      background: hsl(var(--p-secondary));
    }
    .preview-scope .p-eyebrow-pill-dark {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 7px 14px;
      border-radius: 999px;
      background: hsl(0 0% 100% / 0.08);
      border: 1px solid hsl(0 0% 100% / 0.14);
      color: hsl(0 0% 100% / 0.9);
      font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
      text-transform: uppercase;
      backdrop-filter: blur(8px);
    }
    .preview-scope .p-eyebrow-pill-dark::before {
      content: '';
      width: 6px; height: 6px; border-radius: 50%;
      background: hsl(var(--p-secondary));
    }
    .preview-scope .p-section-num {
      font-size: 11px;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      font-weight: 600;
      color: hsl(var(--p-secondary));
      font-variant-numeric: tabular-nums;
    }

    /* Buttons — pill, но компактнее текущего */
    .preview-scope .p-btn {
      display: inline-flex; align-items: center; gap: 8px;
      height: 50px; padding: 0 24px;
      border-radius: 999px;             /* pill — компромисс */
      font-weight: 600; font-size: 15px;
      letter-spacing: -0.005em;
      transition: background 220ms ease, transform 220ms ease, box-shadow 220ms ease, border-color 220ms ease;
      cursor: pointer;
    }
    .preview-scope .p-btn:hover { transform: translateY(-1px); }
    .preview-scope .p-btn-primary {
      background: hsl(var(--p-primary));
      color: white; border: 1px solid hsl(var(--p-primary));
      box-shadow: 0 6px 24px -10px hsl(var(--p-primary) / 0.5);
    }
    .preview-scope .p-btn-accent {
      background: hsl(var(--p-secondary));
      color: hsl(var(--p-secondary-fg));
      border: 1px solid hsl(var(--p-secondary));
      box-shadow: 0 6px 24px -10px hsl(var(--p-secondary) / 0.5);
    }
    .preview-scope .p-btn-ghost-dark {
      background: hsl(0 0% 100% / 0.08);
      color: white;
      border: 1px solid hsl(0 0% 100% / 0.22);
      backdrop-filter: blur(8px);
    }
    .preview-scope .p-btn-ghost-dark:hover { border-color: hsl(0 0% 100% / 0.5); background: hsl(0 0% 100% / 0.14); }
    .preview-scope .p-btn-ghost-light {
      background: transparent;
      color: hsl(var(--p-primary));
      border: 1px solid hsl(var(--p-border-strong));
    }
    .preview-scope .p-btn-ghost-light:hover { border-color: hsl(var(--p-primary) / 0.5); background: hsl(var(--p-surface)); }

    /* Card — rounded-xl, мягкое поднятие на hover */
    .preview-scope .p-card {
      background: white;
      border: 1px solid hsl(var(--p-border));
      border-radius: 16px;
      transition: transform 260ms ease, box-shadow 260ms ease, border-color 260ms ease;
    }
    .preview-scope .p-card:hover {
      transform: translateY(-2px);
      border-color: hsl(var(--p-primary) / 0.25);
      box-shadow: 0 20px 40px -20px hsl(var(--p-graphite) / 0.18);
    }

    /* Стеклянная карточка на тёмном — мягче, без сильного blur */
    .preview-scope .p-glass {
      background: hsl(0 0% 100% / 0.06);
      border: 1px solid hsl(0 0% 100% / 0.12);
      border-radius: 16px;
      backdrop-filter: blur(10px);
      transition: background 240ms ease, border-color 240ms ease;
    }
    .preview-scope .p-glass:hover {
      background: hsl(0 0% 100% / 0.1);
      border-color: hsl(0 0% 100% / 0.2);
    }

    /* Vertical rhythm — единая система отступов */
    .preview-scope .p-section { padding: 96px 0; }
    @media (min-width: 768px) { .preview-scope .p-section { padding: 128px 0; } }
    @media (min-width: 1280px) { .preview-scope .p-section { padding: 144px 0; } }

    .preview-scope .p-section-header { margin-bottom: 56px; }
    @media (min-width: 768px) { .preview-scope .p-section-header { margin-bottom: 72px; } }

    .preview-scope .p-container {
      max-width: 1280px; margin: 0 auto;
      padding: 0 24px;
    }
    @media (min-width: 768px) { .preview-scope .p-container { padding: 0 40px; } }

    .preview-scope .p-header-grid {
      display: grid; grid-template-columns: 1fr; gap: 24px;
      align-items: end;
    }
    @media (min-width: 1024px) {
      .preview-scope .p-header-grid { grid-template-columns: 1fr 1fr; gap: 64px; }
    }

    /* Eyebrow→title gap */
    .preview-scope .p-title-gap { margin-bottom: 20px; }
    /* Header→content paragraph gap (used inside paragraphs after h2) */
    .preview-scope .p-lead { margin-top: 24px; line-height: 1.65; color: hsl(var(--p-graphite) / 0.65); }

    .preview-scope .p-link {
      display: inline-flex; align-items: center; gap: 6px;
      color: hsl(var(--p-primary));
      font-weight: 600; font-size: 14px;
      border-bottom: 1px solid hsl(var(--p-primary) / 0.3);
      padding-bottom: 2px;
      transition: border-color 200ms ease;
    }
    .preview-scope .p-link:hover { border-color: hsl(var(--p-primary)); }
    .preview-scope .p-link-light {
      display: inline-flex; align-items: center; gap: 6px;
      color: hsl(var(--p-secondary));
      font-weight: 600; font-size: 14px;
    }

    /* Tag chip (used inside dark cards) */
    .preview-scope .p-chip-light {
      display: inline-flex; align-items: center;
      padding: 4px 10px;
      border-radius: 999px;
      background: hsl(var(--p-secondary) / 0.12);
      color: hsl(var(--p-secondary));
      font-size: 11px; font-weight: 600;
      letter-spacing: 0.06em; text-transform: uppercase;
    }

    /* Анимация carousel-кнопок круглых */
    .preview-scope .p-circle-btn {
      width: 44px; height: 44px;
      border-radius: 999px;
      border: 1px solid hsl(var(--p-border-strong));
      display: inline-flex; align-items: center; justify-content: center;
      color: hsl(var(--p-primary));
      transition: all 220ms ease;
      background: white;
    }
    .preview-scope .p-circle-btn:hover {
      background: hsl(var(--p-primary));
      color: white;
      border-color: hsl(var(--p-primary));
    }
  `}</style>
);

/* ─────────────────────────────────────────────────────────────────
 *  HEADER
 * ───────────────────────────────────────────────────────────────── */

const PreviewHeader = () => (
  <header className="sticky top-0 z-50 border-b" style={{ background: 'hsl(0 0% 100% / 0.92)', backdropFilter: 'blur(12px)', borderColor: 'hsl(var(--p-border))' }}>
    <div className="p-container flex items-center justify-between h-[72px]">
      <div className="flex items-center gap-3">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-sm"
          style={{ background: 'linear-gradient(135deg, hsl(var(--p-primary)) 0%, hsl(var(--p-primary-deep)) 100%)' }}
        >
          HT
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] font-semibold" style={{ color: 'hsl(var(--p-secondary))' }}>
            Hi-Tech Group
          </div>
          <div className="text-sm font-semibold leading-tight" style={{ color: 'hsl(var(--p-graphite))' }}>
            Энергетика · СЭС · EPC
          </div>
        </div>
      </div>
      <nav className="hidden md:flex items-center gap-8 text-sm font-medium" style={{ color: 'hsl(var(--p-graphite))' }}>
        <a href="#">Направления</a>
        <a href="#">Проекты</a>
        <a href="#">О компании</a>
        <a href="#">Новости</a>
        <a href="#">Контакты</a>
      </nav>
      <button className="p-btn p-btn-primary !h-11 !px-5 text-sm">Связаться <ArrowRight size={14} /></button>
    </div>
  </header>
);

/* ─────────────────────────────────────────────────────────────────
 *  HERO — фото-фон, мягкий gradient, eyebrow-pill, плотный заголовок
 * ───────────────────────────────────────────────────────────────── */

const Hero = () => (
  <section className="relative overflow-hidden" style={{ minHeight: '92vh' }}>
    {/* Background photo — заметнее, чем в preview */}
    <div className="absolute inset-0">
      <img
        src="/images/hero-solar-1024w.webp"
        alt=""
        className="w-full h-full object-cover"
      />
      {/* Тёплый gradient overlay — сохранён зелёно-янтарный характер */}
      <div
        className="absolute inset-0"
        style={{
          background: `linear-gradient(105deg,
            hsl(var(--p-primary) / 0.92) 0%,
            hsl(var(--p-primary) / 0.7) 45%,
            hsl(var(--p-primary) / 0.25) 100%)`
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background: `linear-gradient(180deg,
            transparent 0%,
            transparent 50%,
            hsl(var(--p-primary-deep) / 0.6) 100%)`
        }}
      />
    </div>

    <div className="relative p-container pt-40 pb-24 md:pt-48 md:pb-32">
      <div className="max-w-4xl">
        <div className="p-eyebrow-pill-dark p-title-gap">Hi-Tech Group · с 2014 года</div>
        <h1 className="p-display p-display-xl text-white">
          Энергия солнца
          <br />
          <span style={{ color: 'hsl(var(--p-secondary))' }}>Казахстана</span>
        </h1>
        <p className="mt-6 text-lg max-w-2xl" style={{ color: 'rgba(255,255,255,0.85)', lineHeight: 1.65 }}>
          Проектируем, строим и обслуживаем солнечные электростанции по всему Казахстану.
          Полный цикл — от технико-экономического обоснования до подключения к сети.
        </p>
        <div className="mt-10 flex flex-wrap gap-3">
          <button className="p-btn p-btn-accent">Связаться <ArrowRight size={14} /></button>
          <button className="p-btn p-btn-ghost-dark">Наши проекты</button>
        </div>
      </div>

      {/* Stats — рядом 3 glass-карточки, иконки в обведённом круге (как сейчас),
          но плотнее и с tabular-цифрами */}
      <div className="mt-20 grid md:grid-cols-3 gap-5">
        {[
          { icon: Zap, value: '722 МВт', label: 'Установленная мощность СЭС' },
          { icon: RefreshCw, value: 'Полный цикл', label: 'EPC + эксплуатация и сервис' },
          { icon: FileCheck, value: 'Собственная методика', label: 'Расчёта генерации в условиях РК' },
        ].map((stat, i) => {
          const Icon = stat.icon;
          return (
            <div key={i} className="p-glass p-7">
              <div className="flex items-start justify-between mb-5">
                <div
                  className="w-12 h-12 rounded-full border flex items-center justify-center"
                  style={{ borderColor: 'hsl(var(--p-secondary) / 0.5)' }}
                >
                  <Icon size={22} style={{ color: 'hsl(var(--p-secondary))' }} strokeWidth={1.75} />
                </div>
                <span className="p-numeric text-xs font-mono opacity-50" style={{ color: 'white' }}>
                  0{i + 1}
                </span>
              </div>
              <div className="p-display p-numeric text-xl text-white mb-1">{stat.value}</div>
              <div className="text-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.65)' }}>
                {stat.label}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  </section>
);

/* ─────────────────────────────────────────────────────────────────
 *  ACTIVITY DIRECTIONS — фото-карточки с overlay, как сейчас,
 *  но с нумерацией и hairline-сеткой
 * ───────────────────────────────────────────────────────────────── */

const DirectionsBlock = () => {
  const items = [
    { num: '01', title: 'Земляные работы', desc: 'Подготовка площадок СЭС — съёмка, выравнивание, дренаж.', img: '/images/directionsLogo1.webp' },
    { num: '02', title: 'Строительство', desc: 'Возведение объектов инфраструктуры — фундаменты, ограждения.', img: '/images/directionsLogo2.webp' },
    { num: '03', title: 'Монтаж оборудования', desc: 'Установка фотомодулей, инверторов, трекеров.', img: '/images/directionsLogo3.webp' },
    { num: '04', title: 'Солнечные парки', desc: 'EPC-проекты под ключ. От ТЭО до коммерческой эксплуатации.', img: '/images/directionsLogo4.webp' },
    { num: '05', title: 'Подстанции', desc: 'Высоковольтные подстанции и подключение к сетям ЕЭС.', img: '/images/directionsLogo5.webp' },
  ];
  return (
    <section className="p-section" style={{ background: 'hsl(var(--p-surface))' }}>
      <div className="p-container">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 p-section-header">
          <div>
            <div className="p-eyebrow-pill mb-4">01 — Направления</div>
            <h2 className="p-display p-display-lg" style={{ color: 'hsl(var(--p-graphite))' }}>
              Пять компетенций<br />внутри одной компании
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <button className="p-circle-btn"><ChevronLeft size={18} /></button>
            <button className="p-circle-btn"><ChevronRight size={18} /></button>
          </div>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {items.map((item) => (
            <article
              key={item.num}
              className="group relative overflow-hidden cursor-pointer p-card !p-0"
              style={{ borderRadius: 16 }}
            >
              <div className="aspect-[4/3] relative">
                <img
                  src={item.img}
                  alt={item.title}
                  className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-[1.06]"
                />
                <div
                  className="absolute inset-0"
                  style={{
                    background: `linear-gradient(180deg,
                      transparent 30%,
                      hsl(var(--p-primary) / 0.55) 65%,
                      hsl(var(--p-primary-deep) / 0.95) 100%)`,
                  }}
                />
                {/* Number badge */}
                <div className="absolute top-5 left-5 p-eyebrow-pill-dark !text-[10px] !py-1.5 !px-3" style={{ background: 'hsl(0 0% 0% / 0.4)' }}>
                  {item.num}
                </div>
                <ArrowUpRight
                  size={20}
                  strokeWidth={1.75}
                  className="absolute top-5 right-5 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
                  style={{ color: 'hsl(var(--p-secondary))' }}
                />
              </div>
              <div className="absolute bottom-0 left-0 right-0 p-6">
                <h3 className="p-display text-xl text-white mb-2 transition-transform duration-300 group-hover:-translate-y-1">
                  {item.title}
                </h3>
                <div className="grid grid-rows-[0fr] group-hover:grid-rows-[1fr] transition-all duration-400">
                  <div className="min-h-0 overflow-hidden">
                    <p className="text-sm" style={{ color: 'rgba(255,255,255,0.78)', lineHeight: 1.5 }}>
                      {item.desc}
                    </p>
                  </div>
                </div>
              </div>
            </article>
          ))}
          {/* CTA tile */}
          <article
            className="p-card flex flex-col justify-between p-7"
            style={{ background: 'white', minHeight: 280 }}
          >
            <div>
              <div className="p-section-num mb-4">06 — Ещё</div>
              <h3 className="p-display text-xl mb-3" style={{ color: 'hsl(var(--p-graphite))' }}>
                Не нашли свою задачу?
              </h3>
              <p className="text-sm" style={{ color: 'hsl(var(--p-graphite) / 0.65)', lineHeight: 1.6 }}>
                Обсудим нестандартный энергопроект — от концепции до запуска.
              </p>
            </div>
            <a className="p-link mt-6" href="#">
              Все направления <ArrowRight size={14} />
            </a>
          </article>
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  INVEST BAND — тёплая полоса с зелёно-золотым градиентом
 * ───────────────────────────────────────────────────────────────── */

const InvestBand = () => (
  <section
    className="relative overflow-hidden"
    style={{
      background: `linear-gradient(110deg, hsl(var(--p-primary)) 0%, hsl(var(--p-primary-soft)) 60%, hsl(40 60% 40%) 120%)`,
    }}
  >
    <div className="p-container py-20 grid md:grid-cols-[1fr,auto] items-center gap-10 relative z-10">
      <div>
        <div className="p-eyebrow-pill-dark mb-5">Для инвесторов</div>
        <h3 className="p-display p-display-lg text-white max-w-3xl">
          ВИЭ Казахстана — гарантированный тариф,<br />валютная индексация, окупаемость 7–9 лет.
        </h3>
      </div>
      <div className="flex flex-col gap-3">
        <button className="p-btn p-btn-accent">Условия партнёрства <ArrowRight size={14} /></button>
        <a className="text-sm font-medium underline underline-offset-4" style={{ color: 'rgba(255,255,255,0.85)' }} href="#">
          Скачать меморандум (PDF, 4.2 МБ)
        </a>
      </div>
    </div>
    {/* Decorative sun-like radial */}
    <div
      className="absolute -top-32 -right-32 w-[480px] h-[480px] rounded-full opacity-30"
      style={{ background: 'radial-gradient(circle, hsl(var(--p-secondary)) 0%, transparent 70%)' }}
    />
  </section>
);

/* ─────────────────────────────────────────────────────────────────
 *  PROJECTS + MAP
 * ───────────────────────────────────────────────────────────────── */

const ProjectsBlock = () => {
  const projects = [
    { name: 'СЭС «Сарань»', loc: 'Карагандинская обл.', mw: '50 МВт', year: '2023' },
    { name: 'СЭС «Шу»', loc: 'Жамбылская обл.', mw: '100 МВт', year: '2022' },
    { name: 'СЭС «Капшагай»', loc: 'Алматинская обл.', mw: '76 МВт', year: '2021' },
  ];
  return (
    <section className="p-section" style={{ background: 'white' }}>
      <div className="p-container">
        <div className="p-header-grid p-section-header">
          <div>
            <div className="p-eyebrow-pill mb-4">02 — Проекты</div>
            <h2 className="p-display p-display-lg" style={{ color: 'hsl(var(--p-graphite))' }}>
              География работ:<br />шесть областей Казахстана
            </h2>
          </div>
          <p className="self-end" style={{ color: 'hsl(var(--p-graphite) / 0.65)', lineHeight: 1.65 }}>
            Реализовано 15+ объектов общей мощностью 722 МВт. Все объекты прошли независимый
            аудит по стандартам IEC 61215, IEC 61730.
          </p>
        </div>

        <div className="grid lg:grid-cols-[1fr,500px] gap-8">
          {/* Project list — hairline разделители */}
          <div
            className="rounded-2xl border overflow-hidden"
            style={{ borderColor: 'hsl(var(--p-border))' }}
          >
            {projects.map((p, i) => (
              <article
                key={p.name}
                className="grid grid-cols-[1fr,auto,auto] items-center gap-6 px-7 py-6 group cursor-pointer transition-colors"
                style={{
                  background: 'white',
                  borderTop: i > 0 ? '1px solid hsl(var(--p-border))' : 'none',
                }}
              >
                <div>
                  <h3 className="p-display p-display-md mb-2" style={{ color: 'hsl(var(--p-graphite))' }}>
                    {p.name}
                  </h3>
                  <div className="flex items-center gap-2 text-sm" style={{ color: 'hsl(var(--p-graphite) / 0.6)' }}>
                    <MapPin size={14} strokeWidth={1.6} />
                    {p.loc}
                  </div>
                </div>
                <div className="text-right">
                  <div className="p-section-num mb-1" style={{ color: 'hsl(var(--p-graphite) / 0.5)' }}>Мощность</div>
                  <div className="p-display p-numeric text-xl" style={{ color: 'hsl(var(--p-primary))' }}>{p.mw}</div>
                </div>
                <div className="text-right min-w-[60px]">
                  <div className="p-section-num mb-1" style={{ color: 'hsl(var(--p-graphite) / 0.5)' }}>Год</div>
                  <div className="p-display p-numeric text-xl" style={{ color: 'hsl(var(--p-graphite))' }}>{p.year}</div>
                </div>
              </article>
            ))}
            <div
              className="px-7 py-6"
              style={{ background: 'hsl(var(--p-surface))', borderTop: '1px solid hsl(var(--p-border))' }}
            >
              <a className="p-link" href="#">Все проекты (15) <ArrowRight size={14} /></a>
            </div>
          </div>

          {/* Карта */}
          <div className="p-card p-7 flex flex-col" style={{ background: 'hsl(var(--p-surface))' }}>
            <div className="p-section-num mb-3">Карта проектов</div>
            <div className="text-sm mb-6" style={{ color: 'hsl(var(--p-graphite) / 0.65)' }}>
              Действующие СЭС Hi-Tech Group на территории РК
            </div>
            <div className="relative flex-1 min-h-[220px]">
              <svg viewBox="0 0 400 220" className="w-full h-full">
                <path
                  d="M 30 90 Q 80 50 150 60 Q 220 50 290 80 Q 360 90 370 120 Q 350 160 280 170 Q 200 180 130 175 Q 60 165 30 130 Z"
                  fill="hsl(var(--p-primary) / 0.08)"
                  stroke="hsl(var(--p-primary) / 0.4)"
                  strokeWidth="1.5"
                />
                {[
                  { cx: 110, cy: 130 }, { cx: 190, cy: 110 }, { cx: 270, cy: 100 },
                  { cx: 240, cy: 140 }, { cx: 320, cy: 130 },
                ].map((pt, i) => (
                  <g key={i}>
                    <circle cx={pt.cx} cy={pt.cy} r={14} fill="hsl(var(--p-secondary) / 0.18)" />
                    <circle cx={pt.cx} cy={pt.cy} r={5} fill="hsl(var(--p-secondary))" />
                  </g>
                ))}
              </svg>
            </div>
            <div className="mt-6 grid grid-cols-2 gap-4 text-xs">
              <div>
                <div className="p-display p-numeric text-3xl" style={{ color: 'hsl(var(--p-primary))' }}>15+</div>
                <div className="mt-1" style={{ color: 'hsl(var(--p-graphite) / 0.6)' }}>проектов</div>
              </div>
              <div>
                <div className="p-display p-numeric text-3xl" style={{ color: 'hsl(var(--p-primary))' }}>6</div>
                <div className="mt-1" style={{ color: 'hsl(var(--p-graphite) / 0.6)' }}>регионов РК</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  SERVICES — карточки с buleted-списками
 * ───────────────────────────────────────────────────────────────── */

const ServicesBlock = () => {
  const services = [
    { num: '01', title: 'EPC под ключ', items: ['Проектирование', 'Поставка оборудования', 'Монтаж', 'Пуско-наладка'] },
    { num: '02', title: 'Эксплуатация и сервис', items: ['Мониторинг 24/7', 'Регламентные работы', 'Аварийный выезд', 'Отчётность'] },
    { num: '03', title: 'Инжиниринг и ТЭО', items: ['Геология', 'Энергетические расчёты', 'Документация', 'Согласование'] },
    { num: '04', title: 'Подключение к сетям', items: ['Подстанции', 'Кабельные линии', 'Согласование с ЕЭС', 'Релейная защита'] },
  ];
  return (
    <section className="p-section" style={{ background: 'hsl(var(--p-surface))' }}>
      <div className="p-container">
        <div className="p-header-grid p-section-header">
          <div>
            <div className="p-eyebrow-pill mb-4">03 — Услуги</div>
            <h2 className="p-display p-display-lg" style={{ color: 'hsl(var(--p-graphite))' }}>
              От ТЭО до коммерческой эксплуатации
            </h2>
          </div>
          <p className="self-end" style={{ color: 'hsl(var(--p-graphite) / 0.65)', lineHeight: 1.65 }}>
            Любую часть жизненного цикла СЭС можно заказать отдельно или комплексно.
            Все этапы выполняются собственными силами без субподряда.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-5">
          {services.map((s) => (
            <article key={s.num} className="p-card p-8">
              <div className="flex items-start justify-between mb-5">
                <div className="p-chip-light">{s.num}</div>
                <ArrowUpRight size={18} strokeWidth={1.6} style={{ color: 'hsl(var(--p-graphite) / 0.4)' }} />
              </div>
              <h3 className="p-display p-display-md mb-5" style={{ color: 'hsl(var(--p-graphite))' }}>
                {s.title}
              </h3>
              <ul className="space-y-2.5">
                {s.items.map((item) => (
                  <li key={item} className="flex items-center gap-3 text-sm" style={{ color: 'hsl(var(--p-graphite) / 0.78)' }}>
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'hsl(var(--p-secondary))' }} />
                    {item}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  STATS — крупные tabular-цифры на тёмно-зелёном с softer fill
 * ───────────────────────────────────────────────────────────────── */

const StatsBlock = () => {
  const stats = [
    { value: '722', unit: 'МВт', label: 'Установленная мощность объектов' },
    { value: '15', unit: '+', label: 'Реализованных проектов под ключ' },
    { value: '10', unit: 'лет', label: 'На рынке энергостроительства' },
    { value: '1 200', unit: 'га', label: 'Освоенных площадей СЭС' },
  ];
  return (
    <section
      className="p-section relative overflow-hidden"
      style={{
        background: `linear-gradient(135deg, hsl(var(--p-primary)) 0%, hsl(var(--p-primary-deep)) 100%)`,
        color: 'white',
      }}
    >
      {/* Sun glow decoration */}
      <div
        className="absolute -top-40 -right-40 w-[560px] h-[560px] rounded-full opacity-20"
        style={{ background: 'radial-gradient(circle, hsl(var(--p-secondary)) 0%, transparent 60%)' }}
      />
      <div className="p-container relative z-10">
        <div className="max-w-3xl p-section-header">
          <div className="p-eyebrow-pill-dark mb-5">04 — Цифры</div>
          <h2 className="p-display p-display-lg text-white">
            Десятилетие работы<br />в цифрах
          </h2>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
          {stats.map((s, i) => (
            <div
              key={s.label}
              className="p-glass p-7 lg:p-8"
            >
              <div className="p-numeric text-xs mb-6" style={{ color: 'hsl(var(--p-secondary))', letterSpacing: '0.18em' }}>
                — 0{i + 1} —
              </div>
              <div className="flex items-baseline gap-2 mb-4">
                <span className="p-display p-numeric text-white" style={{ fontSize: 'clamp(44px, 5.5vw, 68px)' }}>
                  {s.value}
                </span>
                <span className="p-display p-numeric" style={{ fontSize: 'clamp(20px, 2.2vw, 26px)', color: 'hsl(var(--p-secondary))' }}>
                  {s.unit}
                </span>
              </div>
              <div className="text-xs uppercase tracking-[0.14em] font-medium" style={{ color: 'rgba(255,255,255,0.65)', maxWidth: 200, lineHeight: 1.5 }}>
                {s.label}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  MISSION — крупный typographic statement, мягкий surface
 * ───────────────────────────────────────────────────────────────── */

const MissionBlock = () => (
  <section className="p-section" style={{ background: 'white' }}>
    <div className="p-container">
      <div className="p-eyebrow-pill p-title-gap">05 — Миссия</div>
      <p
        className="p-display max-w-5xl"
        style={{
          fontSize: 'clamp(24px, 3vw, 44px)',
          color: 'hsl(var(--p-graphite))',
          lineHeight: 1.25,
          letterSpacing: '-0.018em',
          marginBottom: 56,
        }}
      >
        Мы строим инфраструктуру, которая работает{' '}
        <span style={{ color: 'hsl(var(--p-secondary))' }}>25+ лет</span>{' '}
        в условиях континентального климата Казахстана — от −40 °C зимой до +45 °C летом.
      </p>
      <div className="grid md:grid-cols-3 gap-8 max-w-5xl">
        {[
          { title: 'Надёжность', desc: 'Только сертифицированное оборудование, ресурс ≥ 25 лет на критических узлах.' },
          { title: 'Локализация', desc: 'Собственное производство БМЗ-конструкций и металлоконструкций в РК.' },
          { title: 'Прозрачность', desc: 'Открытая отчётность по KPI на каждом этапе строительства и эксплуатации.' },
        ].map((m) => (
          <div key={m.title}>
            <div className="flex items-center gap-3 mb-3">
              <span className="w-8 h-px" style={{ background: 'hsl(var(--p-secondary))' }} />
              <h4 className="p-display text-lg" style={{ color: 'hsl(var(--p-primary))' }}>
                {m.title}
              </h4>
            </div>
            <p style={{ color: 'hsl(var(--p-graphite) / 0.7)', fontSize: 14, lineHeight: 1.65 }}>
              {m.desc}
            </p>
          </div>
        ))}
      </div>
    </div>
  </section>
);

/* ─────────────────────────────────────────────────────────────────
 *  ABOUT + TIMELINE
 * ───────────────────────────────────────────────────────────────── */

const AboutTimeline = () => {
  const milestones = [
    { year: '2014', title: 'Основание', desc: 'Создание Hi-Tech Group, первые проекты в строительстве подстанций.' },
    { year: '2017', title: 'Первая СЭС', desc: 'Запуск первой солнечной электростанции в Жамбылской области, 12 МВт.' },
    { year: '2019', title: 'EPC под ключ', desc: 'Переход к комплексному подряду — проектирование + строительство + наладка.' },
    { year: '2021', title: '500 МВт', desc: 'Совокупная установленная мощность объектов превысила 500 МВт.' },
    { year: '2023', title: '722 МВт', desc: 'Запуск четырёх новых СЭС, выход на 722 МВт совокупной мощности.' },
    { year: '2026', title: 'Сегодня', desc: 'В работе ещё 3 проекта общей мощностью 150 МВт.' },
  ];
  return (
    <section className="p-section" style={{ background: 'hsl(var(--p-surface))' }}>
      <div className="p-container">
        <div className="p-header-grid p-section-header">
          <div>
            <div className="p-eyebrow-pill mb-4">06 — О компании</div>
            <h2 className="p-display p-display-lg" style={{ color: 'hsl(var(--p-graphite))' }}>
              История за 12 лет<br />на энергорынке РК
            </h2>
          </div>
          <p className="self-end" style={{ color: 'hsl(var(--p-graphite) / 0.65)', lineHeight: 1.65 }}>
            От первых подстанционных контрактов до крупнейших EPC-проектов в области ВИЭ.
            Команда выросла с 12 до 240+ инженеров и монтажников.
          </p>
        </div>

        <div className="relative">
          {/* линия по центру колонки годов */}
          <div
            className="absolute left-[90px] md:left-[124px] top-2 bottom-2 w-px"
            style={{ background: 'hsl(var(--p-border-strong))' }}
          />
          <div className="space-y-10">
            {milestones.map((m, i) => {
              const isLast = i === milestones.length - 1;
              return (
                <div key={m.year} className="grid grid-cols-[90px,1fr] md:grid-cols-[124px,1fr] gap-8 md:gap-14 items-start">
                  <div className="relative">
                    <div
                      className="p-display p-numeric text-2xl md:text-3xl"
                      style={{ color: isLast ? 'hsl(var(--p-secondary))' : 'hsl(var(--p-primary))' }}
                    >
                      {m.year}
                    </div>
                    <div
                      className="absolute top-3 -right-[6px] w-3 h-3 rounded-full border-2"
                      style={{
                        background: isLast ? 'hsl(var(--p-secondary))' : 'hsl(var(--p-surface))',
                        borderColor: isLast ? 'hsl(var(--p-secondary))' : 'hsl(var(--p-primary))',
                      }}
                    />
                  </div>
                  <div className="p-card p-6">
                    <h3 className="p-display text-lg mb-2" style={{ color: 'hsl(var(--p-graphite))' }}>
                      {m.title}
                    </h3>
                    <p style={{ color: 'hsl(var(--p-graphite) / 0.7)', fontSize: 14, lineHeight: 1.65, maxWidth: 560 }}>
                      {m.desc}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  PARTNERS + CERTIFICATES
 * ───────────────────────────────────────────────────────────────── */

/* Стилизованные SVG-логотипы партнёров — каждый со своим визуальным маркером.
   В продакшене заменяются на реальные SVG / PNG из public/images/partners/. */
const PartnerLogos = {
  Kegoc: () => (
    <svg viewBox="0 0 140 32" className="h-7 w-auto" fill="currentColor">
      <circle cx="13" cy="16" r="9" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <path d="M 9 16 L 17 16 M 13 12 L 13 20" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <text x="30" y="22" fontSize="18" fontWeight="800" letterSpacing="0.04em" fontFamily="Inter, sans-serif">KEGOC</text>
    </svg>
  ),
  Samruk: () => (
    <svg viewBox="0 0 170 32" className="h-7 w-auto" fill="currentColor">
      <polygon points="6,6 18,6 22,16 18,26 6,26 2,16" fill="currentColor" />
      <text x="30" y="14" fontSize="9" fontWeight="700" letterSpacing="0.18em" fontFamily="Inter, sans-serif">САМРУК</text>
      <text x="30" y="26" fontSize="11" fontWeight="800" letterSpacing="0.04em" fontFamily="Inter, sans-serif">ЭНЕРГО</text>
    </svg>
  ),
  KazMinerals: () => (
    <svg viewBox="0 0 170 32" className="h-7 w-auto" fill="currentColor">
      <path d="M 4 22 L 12 8 L 20 22 Z M 16 22 L 24 14 L 30 22 Z" fill="currentColor" />
      <text x="38" y="22" fontSize="15" fontWeight="800" letterSpacing="-0.01em" fontFamily="Inter, sans-serif">KAZ Minerals</text>
    </svg>
  ),
  KMG: () => (
    <svg viewBox="0 0 160 32" className="h-7 w-auto" fill="currentColor">
      <rect x="4" y="6" width="20" height="20" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
      <text x="9" y="22" fontSize="12" fontWeight="800" fontFamily="Inter, sans-serif" fill="currentColor">КМГ</text>
      <text x="32" y="14" fontSize="9" fontWeight="600" letterSpacing="0.12em" fontFamily="Inter, sans-serif">НАЦИОНАЛЬНАЯ КОМПАНИЯ</text>
      <text x="32" y="26" fontSize="11" fontWeight="800" letterSpacing="0.02em" fontFamily="Inter, sans-serif">КАЗМУНАЙГАЗ</text>
    </svg>
  ),
  Jinko: () => (
    <svg viewBox="0 0 180 32" className="h-7 w-auto" fill="currentColor">
      <circle cx="13" cy="16" r="10" fill="currentColor" />
      <circle cx="13" cy="16" r="5" fill="white" opacity="0.95" />
      <text x="32" y="22" fontSize="17" fontWeight="800" letterSpacing="-0.01em" fontFamily="Inter, sans-serif">JinkoSolar</text>
    </svg>
  ),
  Sungrow: () => (
    <svg viewBox="0 0 150 32" className="h-7 w-auto" fill="currentColor">
      <path d="M 4 16 Q 10 6 16 16 Q 22 26 28 16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="16" cy="9" r="2.5" fill="currentColor" />
      <text x="38" y="22" fontSize="17" fontWeight="800" letterSpacing="-0.005em" fontFamily="Inter, sans-serif">Sungrow</text>
    </svg>
  ),
  Huawei: () => (
    <svg viewBox="0 0 200 32" className="h-7 w-auto" fill="currentColor">
      <path d="M 4 20 Q 8 8 14 20 Q 20 8 26 20" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <text x="34" y="14" fontSize="13" fontWeight="800" letterSpacing="0.06em" fontFamily="Inter, sans-serif">HUAWEI</text>
      <text x="34" y="26" fontSize="9" fontWeight="500" letterSpacing="0.12em" fontFamily="Inter, sans-serif">FusionSolar</text>
    </svg>
  ),
  Trina: () => (
    <svg viewBox="0 0 160 32" className="h-7 w-auto" fill="currentColor">
      <rect x="4" y="6" width="22" height="20" fill="currentColor" />
      <rect x="8" y="10" width="3" height="12" fill="white" opacity="0.9" />
      <rect x="13" y="10" width="3" height="12" fill="white" opacity="0.9" />
      <rect x="18" y="10" width="3" height="12" fill="white" opacity="0.9" />
      <text x="34" y="14" fontSize="11" fontWeight="800" letterSpacing="0.04em" fontFamily="Inter, sans-serif">TRINA</text>
      <text x="34" y="26" fontSize="9" fontWeight="500" letterSpacing="0.18em" fontFamily="Inter, sans-serif">SOLAR</text>
    </svg>
  ),
};

const PartnersCertificates = () => {
  const partners = [
    { key: 'kegoc', Logo: PartnerLogos.Kegoc },
    { key: 'samruk', Logo: PartnerLogos.Samruk },
    { key: 'kazminerals', Logo: PartnerLogos.KazMinerals },
    { key: 'kmg', Logo: PartnerLogos.KMG },
    { key: 'jinko', Logo: PartnerLogos.Jinko },
    { key: 'sungrow', Logo: PartnerLogos.Sungrow },
    { key: 'huawei', Logo: PartnerLogos.Huawei },
    { key: 'trina', Logo: PartnerLogos.Trina },
  ];
  const certs = [
    { code: 'ISO 9001:2015', desc: 'Система менеджмента качества' },
    { code: 'ISO 14001:2015', desc: 'Экологический менеджмент' },
    { code: 'ISO 45001:2018', desc: 'Охрана труда и безопасность' },
    { code: 'IEC 61215', desc: 'Сертификация фотомодулей' },
    { code: 'IEC 61730', desc: 'Безопасность фотомодулей' },
  ];
  return (
    <section className="p-section" style={{ background: 'white' }}>
      <div className="p-container">
        <div className="p-header-grid items-end p-section-header">
          <div>
            <div className="p-eyebrow-pill mb-4">07 — Партнёры</div>
            <h2 className="p-display p-display-lg" style={{ color: 'hsl(var(--p-graphite))' }}>
              С кем мы работаем
            </h2>
          </div>
          <p className="self-end" style={{ color: 'hsl(var(--p-graphite) / 0.65)', lineHeight: 1.65 }}>
            Заказчики из энергетики, добывающего сектора и крупной промышленности.
            Поставщики оборудования — мировые лидеры рынка.
          </p>
        </div>

        {/* Логотипы — монохромная сетка, на hover восстанавливается фирменный зелёный */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mb-20">
          {partners.map(({ key, Logo }) => (
            <div
              key={key}
              className="h-28 flex items-center justify-center px-6 rounded-xl border transition-all duration-300 group"
              style={{ borderColor: 'hsl(var(--p-border))', background: 'white' }}
            >
              <div
                className="opacity-55 transition-all duration-300 group-hover:opacity-100"
                style={{ color: 'hsl(var(--p-graphite))', transition: 'color 300ms ease, opacity 300ms ease' }}
                onMouseEnter={(e) => { e.currentTarget.style.color = 'hsl(var(--p-primary))'; }}
                onMouseLeave={(e) => { e.currentTarget.style.color = 'hsl(var(--p-graphite))'; }}
              >
                <Logo />
              </div>
            </div>
          ))}
        </div>

        {/* Сертификаты */}
        <div>
          <div className="p-section-num mb-5">Сертификаты и стандарты</div>
          <div className="grid md:grid-cols-3 lg:grid-cols-5 gap-5">
            {certs.map((c) => (
              <div key={c.code} className="p-card p-6">
                <FileCheck size={20} strokeWidth={1.5} style={{ color: 'hsl(var(--p-secondary))' }} className="mb-3" />
                <div className="p-display text-sm font-semibold mb-1" style={{ color: 'hsl(var(--p-graphite))' }}>
                  {c.code}
                </div>
                <div className="text-xs" style={{ color: 'hsl(var(--p-graphite) / 0.6)', lineHeight: 1.5 }}>
                  {c.desc}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  NEWS
 * ───────────────────────────────────────────────────────────────── */

const NewsBlock = () => {
  const news = [
    { date: '14 мая 2026', cat: 'Запуск', title: 'Введена в эксплуатацию СЭС «Сарань-2», 50 МВт', desc: 'Объект подключён к сетям KEGOC, начало коммерческой генерации запланировано на III квартал.' },
    { date: '02 апреля 2026', cat: 'Партнёрство', title: 'Подписано рамочное соглашение с JinkoSolar на поставку 300 МВт модулей', desc: 'Поставка фотомодулей серии Tiger Neo N-type для трёх объектов 2026–2027 годов.' },
    { date: '18 марта 2026', cat: 'Технологии', title: 'Собственная методика расчёта генерации в условиях РК прошла валидацию', desc: 'Точность прогноза по полевым данным трёх СЭС — отклонение менее 3.2% годового объёма.' },
  ];
  return (
    <section className="p-section" style={{ background: 'hsl(var(--p-surface))' }}>
      <div className="p-container">
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 p-section-header">
          <div>
            <div className="p-eyebrow-pill mb-4">08 — Пресс-центр</div>
            <h2 className="p-display p-display-lg" style={{ color: 'hsl(var(--p-graphite))' }}>
              Что происходит<br />в компании
            </h2>
          </div>
          <a className="p-link" href="#">
            Все публикации <ArrowRight size={14} />
          </a>
        </div>

        <div className="grid md:grid-cols-3 gap-5">
          {news.map((n) => (
            <article key={n.title} className="p-card p-7 group cursor-pointer flex flex-col" style={{ minHeight: 300 }}>
              <div className="flex items-center gap-3 mb-5">
                <div className="p-chip-light">{n.cat}</div>
                <span className="flex items-center gap-1.5 text-xs" style={{ color: 'hsl(var(--p-graphite) / 0.55)' }}>
                  <Calendar size={12} strokeWidth={1.6} />
                  {n.date}
                </span>
              </div>
              <h3 className="p-display text-lg mb-3" style={{ color: 'hsl(var(--p-graphite))', lineHeight: 1.3 }}>
                {n.title}
              </h3>
              <p style={{ color: 'hsl(var(--p-graphite) / 0.7)', fontSize: 13, lineHeight: 1.6 }}>
                {n.desc}
              </p>
              <div className="mt-auto pt-6 inline-flex items-center gap-1.5 text-sm font-semibold transition-transform group-hover:gap-2" style={{ color: 'hsl(var(--p-primary))' }}>
                Читать <ChevronRight size={14} />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
};

/* ─────────────────────────────────────────────────────────────────
 *  CONTACT
 * ───────────────────────────────────────────────────────────────── */

const ContactBlock = () => (
  <section className="p-section" style={{ background: 'white' }}>
    <div className="p-container">
      <div className="grid lg:grid-cols-[1fr,500px] gap-12 lg:gap-16">
        <div>
          <div className="p-eyebrow-pill mb-4">09 — Контакты</div>
          <h2 className="p-display p-display-lg max-w-2xl mb-6" style={{ color: 'hsl(var(--p-graphite))' }}>
            Обсудим ваш<br />энергопроект
          </h2>
          <p className="max-w-xl mb-12" style={{ color: 'hsl(var(--p-graphite) / 0.65)', lineHeight: 1.65 }}>
            Опишите задачу — пришлём коммерческое предложение и предварительный график работ в течение 3 рабочих дней.
          </p>

          <div className="space-y-5">
            {[
              { icon: Phone, label: 'Контактный центр', value: '+7 (727) 000-00-00' },
              { icon: Mail, label: 'Коммерческий отдел', value: 'sales@hi-tech.kz' },
              { icon: MapPin, label: 'Головной офис', value: 'г. Алматы, ул. Энергетиков 1' },
            ].map((c) => {
              const Icon = c.icon;
              return (
                <div key={c.label} className="flex items-start gap-4">
                  <div
                    className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
                    style={{ background: 'hsl(var(--p-primary) / 0.08)' }}
                  >
                    <Icon size={18} strokeWidth={1.6} style={{ color: 'hsl(var(--p-primary))' }} />
                  </div>
                  <div>
                    <div className="p-section-num mb-1" style={{ color: 'hsl(var(--p-graphite) / 0.55)' }}>
                      {c.label}
                    </div>
                    <div className="p-display text-base" style={{ color: 'hsl(var(--p-graphite))' }}>
                      {c.value}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <form
          className="p-8 md:p-10 rounded-2xl border"
          style={{ borderColor: 'hsl(var(--p-border))', background: 'hsl(var(--p-surface))' }}
          onSubmit={(e) => e.preventDefault()}
        >
          <div className="p-eyebrow-pill mb-6">Заявка</div>
          {[
            { label: 'Компания', placeholder: 'Hi-Tech Energy Holdings' },
            { label: 'Имя', placeholder: 'Алмат Бекенов' },
            { label: 'E-mail', placeholder: 'a.bekenov@example.kz' },
          ].map((f) => (
            <div key={f.label} className="mb-5">
              <label className="p-section-num block mb-2" style={{ color: 'hsl(var(--p-graphite) / 0.55)' }}>
                {f.label}
              </label>
              <input
                placeholder={f.placeholder}
                className="w-full h-12 px-4 text-sm bg-white border focus:outline-none focus:border-[hsl(var(--p-primary))] transition-colors"
                style={{ borderColor: 'hsl(var(--p-border-strong))', borderRadius: 10, color: 'hsl(var(--p-graphite))' }}
              />
            </div>
          ))}
          <div className="mb-8">
            <label className="p-section-num block mb-2" style={{ color: 'hsl(var(--p-graphite) / 0.55)' }}>
              Кратко о задаче
            </label>
            <textarea
              rows={4}
              placeholder="Мощность объекта, ориентировочное место, сроки..."
              className="w-full px-4 py-3 text-sm bg-white border focus:outline-none focus:border-[hsl(var(--p-primary))] transition-colors resize-none"
              style={{ borderColor: 'hsl(var(--p-border-strong))', borderRadius: 10, color: 'hsl(var(--p-graphite))' }}
            />
          </div>
          <button className="p-btn p-btn-primary w-full justify-center" type="submit">
            Отправить заявку <ArrowRight size={14} />
          </button>
        </form>
      </div>
    </div>
  </section>
);

/* ─────────────────────────────────────────────────────────────────
 *  FOOTER
 * ───────────────────────────────────────────────────────────────── */

const PreviewFooter = () => (
  <footer
    className="relative overflow-hidden"
    style={{
      background: `linear-gradient(135deg, hsl(var(--p-primary-deep)) 0%, hsl(var(--p-primary)) 100%)`,
      color: 'white',
    }}
  >
    {/* Sun glow */}
    <div
      className="absolute -bottom-40 -right-40 w-[500px] h-[500px] rounded-full opacity-15"
      style={{ background: 'radial-gradient(circle, hsl(var(--p-secondary)) 0%, transparent 60%)' }}
    />
    <div className="p-container py-16 relative z-10">
      <div className="grid md:grid-cols-[2fr,1fr,1fr,1fr] gap-10 mb-14">
        <div>
          <div className="p-section-num mb-4">Hi-Tech Group</div>
          <div className="flex items-center gap-3 mb-5">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center text-[hsl(var(--p-primary))] font-bold text-base"
              style={{ background: 'white' }}
            >
              HT
            </div>
            <div className="p-display text-base">Энергетика · СЭС</div>
          </div>
          <p className="max-w-xs text-sm" style={{ color: 'rgba(255,255,255,0.65)', lineHeight: 1.65 }}>
            EPC-подрядчик с десятилетним опытом строительства солнечных электростанций в Республике Казахстан.
          </p>
        </div>
        {[
          { title: 'Компания', items: ['О нас', 'Команда', 'Сертификаты', 'Карьера'] },
          { title: 'Услуги', items: ['EPC под ключ', 'Эксплуатация', 'Инжиниринг', 'Подстанции'] },
          { title: 'Контакты', items: ['Алматы', 'Астана', 'Шымкент', 'Караганда'] },
        ].map((col) => (
          <div key={col.title}>
            <div className="p-section-num mb-4">{col.title}</div>
            <ul className="space-y-2.5 text-sm">
              {col.items.map((i) => (
                <li key={i}>
                  <a href="#" style={{ color: 'rgba(255,255,255,0.78)' }} className="hover:text-white transition-colors">
                    {i}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div
        className="pt-8 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 text-xs"
        style={{ borderTop: '1px solid hsl(0 0% 100% / 0.14)', color: 'rgba(255,255,255,0.5)' }}
      >
        <div>© 2026 Hi-Tech Group. Все права защищены.</div>
        <div className="flex items-center gap-5">
          <a href="#" className="hover:text-white">Политика конфиденциальности</a>
          <a href="#" className="hover:text-white"><Linkedin size={16} strokeWidth={1.5} /></a>
        </div>
      </div>
    </div>
  </footer>
);
