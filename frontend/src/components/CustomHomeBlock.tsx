/**
 * CustomHomeBlock — рендер блоков, созданных редактором на /manage/home.
 *
 * У девяти исходных секций свои компоненты со своей вёрсткой; этот рисует
 * блоки, собранные из интерфейса, по выбранному макету. Именно наличие
 * шаблонных макетов и делает возможным создание блоков без разработчика:
 * bespoke в лендинге оказались только фотографии и иконки, а каркас
 * повторяется от секции к секции.
 *
 * Незнакомый макет не рисуется вовсе, а не падает: строку в БД можно завести
 * миграцией или руками, и опечатка в поле не должна ронять главную.
 */
import { LucideIcon } from '@/components/ui/icon-picker';
import type { HomeSectionPublic } from '@/api/homeSections';

function SectionHeader({ section, light = false }: { section: HomeSectionPublic; light?: boolean }) {
  return (
    <div className="mx-auto mb-12 max-w-3xl text-center">
      {section.tag && (
        <span className="text-sm font-semibold uppercase tracking-wider text-secondary">
          {section.tag}
        </span>
      )}
      {section.title && (
        <h2 className={`font-display mt-2 text-4xl font-bold md:text-5xl ${light ? 'text-primary-foreground' : ''}`}>
          {section.title}
        </h2>
      )}
      {section.description && (
        <p className={`mt-4 text-lg ${light ? 'text-primary-foreground/80' : 'text-muted-foreground'}`}>
          {section.description}
        </p>
      )}
    </div>
  );
}

export function CustomHomeBlock({ section }: { section: HomeSectionPublic }) {
  if (section.layout === 'stats') {
    return (
      <section className="bg-primary py-20">
        <div className="container-custom">
          <SectionHeader section={section} light />
          <div className="grid gap-8 md:grid-cols-3">
            {section.items.map((item) => (
              <div key={item.id} className="text-center">
                <div className="font-display text-5xl font-bold text-secondary">
                  {item.value}
                </div>
                <div className="mt-2 text-primary-foreground/80">
                  {item.title || item.description}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    );
  }

  if (section.layout === 'cta') {
    return (
      <section className="bg-primary py-16">
        <div className="container-custom text-center">
          {section.tag && (
            <span className="text-sm font-medium text-primary-foreground/80">{section.tag}</span>
          )}
          <h2 className="font-display mt-2 text-4xl font-bold text-primary-foreground md:text-5xl">
            {section.title}
          </h2>
          {section.description && (
            <p className="mx-auto mt-4 max-w-2xl text-lg text-primary-foreground/80">
              {section.description}
            </p>
          )}
          {/* Кнопкой служит ПЕРВЫЙ элемент блока: отдельных полей под ссылку у
              секции нет, а заводить их ради одного макета — плодить колонки,
              пустующие у всех остальных. */}
          {section.items[0]?.link && (
            <a
              href={section.items[0].link}
              className="mt-8 inline-flex h-12 items-center justify-center rounded-full bg-secondary px-8 font-medium text-secondary-foreground transition-opacity hover:opacity-90"
            >
              {section.items[0].title || 'Подробнее'}
            </a>
          )}
        </div>
      </section>
    );
  }

  if (section.layout === 'text_media') {
    const media = section.items.find((i) => i.image);
    return (
      <section className="py-20">
        <div className="container-custom grid items-center gap-12 md:grid-cols-2">
          {media && (
            <img
              src={media.image}
              alt={media.title || section.title}
              loading="lazy"
              className="w-full rounded-2xl object-cover shadow-lg"
            />
          )}
          <div className={media ? '' : 'md:col-span-2'}>
            {section.tag && (
              <span className="text-sm font-semibold uppercase tracking-wider text-secondary">
                {section.tag}
              </span>
            )}
            <h2 className="font-display mt-2 text-4xl font-bold">{section.title}</h2>
            {section.description && (
              <p className="mt-4 text-lg text-muted-foreground">{section.description}</p>
            )}
            <div className="mt-6 grid gap-4">
              {section.items.filter((i) => i !== media).map((item) => (
                <div key={item.id} className="flex gap-3">
                  {item.icon && (
                    <LucideIcon name={item.icon} className="mt-0.5 h-5 w-5 shrink-0 text-secondary" />
                  )}
                  <div>
                    <div className="font-semibold">{item.title}</div>
                    <div className="text-sm text-muted-foreground">{item.description}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    );
  }

  if (section.layout === 'features_grid') {
    return (
      <section className="py-20">
        <div className="container-custom">
          <SectionHeader section={section} />
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {section.items.map((item) => (
              <div key={item.id} className="rounded-2xl border bg-card p-6 shadow-sm">
                {item.image ? (
                  <img
                    src={item.image}
                    alt={item.title}
                    loading="lazy"
                    className="mb-4 h-40 w-full rounded-xl object-cover"
                  />
                ) : item.icon ? (
                  <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-secondary/10">
                    <LucideIcon name={item.icon} className="h-6 w-6 text-secondary" />
                  </div>
                ) : null}
                {item.value && (
                  <div className="font-display text-3xl font-bold text-secondary">{item.value}</div>
                )}
                <h3 className="font-display text-xl font-semibold">{item.title}</h3>
                {item.description && (
                  <p className="mt-2 text-sm text-muted-foreground">{item.description}</p>
                )}
                {item.link && (
                  <a href={item.link} className="mt-3 inline-block text-sm font-medium text-primary">
                    Подробнее →
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    );
  }

  return null;
}

export default CustomHomeBlock;
