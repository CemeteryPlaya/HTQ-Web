// TODO: Когда будет реализована панель администратора, данные будут загружаться через API.
// Текущие данные — статичные заглушки с i18n ключами для поддержки мультиязычности.

const panels1 = '/images/panels1.webp';
const panels2 = '/images/panels2.webp';
const panels3 = '/images/panels3.webp';
const panels4 = '/images/panels4.webp';
const heroSolar = '/images/hero-solar.webp';

export interface Project {
  id: number;
  nameKey: string;
  power: string;
  locationKey: string;
  status: 'operational' | 'development';
  descriptionKey: string;
  customerKey: string;
  tasksKey: string;
  image: string;
}

export const projects: Project[] = [
  {
    id: 1,
    nameKey: 'projects_data.1.name',
    power: '250 MW',
    locationKey: 'projects_data.1.location',
    status: 'operational',
    descriptionKey: 'projects_data.1.description',
    customerKey: 'projects_data.1.customer',
    tasksKey: 'projects_data.1.tasks',
    image: panels2,
  },
  {
    id: 2,
    nameKey: 'projects_data.2.name',
    power: '40 MW',
    locationKey: 'projects_data.2.location',
    status: 'operational',
    descriptionKey: 'projects_data.2.description',
    customerKey: 'projects_data.2.customer',
    tasksKey: 'projects_data.2.tasks',
    image: heroSolar,
  },
  {
    id: 3,
    nameKey: 'projects_data.3.name',
    power: '50 MW',
    locationKey: 'projects_data.3.location',
    status: 'operational',
    descriptionKey: 'projects_data.3.description',
    customerKey: 'projects_data.3.customer',
    tasksKey: 'projects_data.3.tasks',
    image: panels1,
  },
  {
    id: 4,
    nameKey: 'projects_data.4.name',
    power: '130 MW',
    locationKey: 'projects_data.4.location',
    status: 'operational',
    descriptionKey: 'projects_data.4.description',
    customerKey: 'projects_data.4.customer',
    tasksKey: 'projects_data.4.tasks',
    image: panels3,
  },
  {
    id: 5,
    nameKey: 'projects_data.5.name',
    power: '100 MW',
    locationKey: 'projects_data.5.location',
    status: 'operational',
    descriptionKey: 'projects_data.5.description',
    customerKey: 'projects_data.5.customer',
    tasksKey: 'projects_data.5.tasks',
    image: panels4,
  },
  {
    id: 6,
    nameKey: 'projects_data.6.name',
    power: '14 MW',
    locationKey: 'projects_data.6.location',
    status: 'operational',
    descriptionKey: 'projects_data.6.description',
    customerKey: 'projects_data.6.customer',
    tasksKey: 'projects_data.6.tasks',
    image: panels2,
  },
  {
    id: 7,
    nameKey: 'projects_data.7.name',
    power: '7 MW',
    locationKey: 'projects_data.7.location',
    status: 'operational',
    descriptionKey: 'projects_data.7.description',
    customerKey: 'projects_data.7.customer',
    tasksKey: 'projects_data.7.tasks',
    image: heroSolar,
  },
  {
    id: 8,
    nameKey: 'projects_data.8.name',
    power: '50 MW',
    locationKey: 'projects_data.8.location',
    status: 'operational',
    descriptionKey: 'projects_data.8.description',
    customerKey: 'projects_data.8.customer',
    tasksKey: 'projects_data.8.tasks',
    image: panels1,
  },
  {
    id: 9,
    nameKey: 'projects_data.9.name',
    power: '200 MW',
    locationKey: 'projects_data.9.location',
    status: 'development',
    descriptionKey: 'projects_data.9.description',
    customerKey: 'projects_data.9.customer',
    tasksKey: 'projects_data.9.tasks',
    image: panels3,
  },
  {
    id: 10,
    nameKey: 'projects_data.10.name',
    power: '300 kW',
    locationKey: 'projects_data.10.location',
    status: 'operational',
    descriptionKey: 'projects_data.10.description',
    customerKey: 'projects_data.10.customer',
    tasksKey: 'projects_data.10.tasks',
    image: panels4,
  },
];
