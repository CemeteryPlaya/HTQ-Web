// TODO: Услуги будут создаваться и редактироваться через admin panel
// когда будет реализована авторизация и доступ администратора.
// Текущие данные — статичные.

const panels8 = '/images/panels8.webp';
const panels9 = '/images/panels9.webp';
const panels10 = '/images/panels10.webp';
const panels11 = '/images/panels11.webp';
const panels12 = '/images/panels12.webp';

export interface Service {
  id: number;
  iconName: string;
  titleKey: string;
  descKey: string;
  image: string;
  featuredOnMain: boolean;
}

export const services: Service[] = [
  {
    id: 1,
    iconName: 'ClipboardCheck',
    titleKey: 'services.items.owners_engineer.title',
    descKey: 'services.items.owners_engineer.desc',
    image: panels8,
    featuredOnMain: true,
  },
  {
    id: 2,
    iconName: 'Shield',
    titleKey: 'services.items.pot.title',
    descKey: 'services.items.pot.desc',
    image: panels9,
    featuredOnMain: true,
  },
  {
    id: 3,
    iconName: 'Wrench',
    titleKey: 'services.items.construction.title',
    descKey: 'services.items.construction.desc',
    image: panels10,
    featuredOnMain: true,
  },
  {
    id: 4,
    iconName: 'Plug',
    titleKey: 'services.items.commissioning.title',
    descKey: 'services.items.commissioning.desc',
    image: panels11,
    featuredOnMain: true,
  },
  {
    id: 5,
    iconName: 'Settings',
    titleKey: 'services.items.maintenance.title',
    descKey: 'services.items.maintenance.desc',
    image: panels12,
    featuredOnMain: true,
  },
];
