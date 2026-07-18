export interface ContactPerson {
  positionKey: string;
  phone: string;
}

export interface Office {
  id: string;
  nameKey: string;
  addressKey: string;
  contacts: ContactPerson[];
}

export interface AffiliatedCompany {
  nameKey: string;
  descriptionKey: string;
  detailsKey: string;
  tagKeys: string[];
  office: Office;
}

// TODO: Когда будет реализована панель администратора, данные будут загружаться из базы данных.
// Текущие данные — статичные заглушки с i18n ключами для поддержки мультиязычности.

export const offices: Office[] = [
  {
    id: 'office-main',
    nameKey: 'contacts_data.offices.main.name',
    addressKey: 'contacts_data.offices.main.address',
    contacts: [
      { positionKey: 'contacts_data.positions.position1', phone: '+7 (700) 000-00-01' },
      { positionKey: 'contacts_data.positions.position2', phone: '+7 (700) 000-00-02' },
      { positionKey: 'contacts_data.positions.position3', phone: '+7 (700) 000-00-03' },
    ],
  },
  {
    id: 'office-astana',
    nameKey: 'contacts_data.offices.office2.name',
    addressKey: 'contacts_data.offices.office2.address',
    contacts: [
      { positionKey: 'contacts_data.positions.position4', phone: '+7 (700) 000-00-04' },
      { positionKey: 'contacts_data.positions.position5', phone: '+7 (700) 000-00-05' },
    ],
  },
  {
    id: 'office-almaty',
    nameKey: 'contacts_data.offices.office3.name',
    addressKey: 'contacts_data.offices.office3.address',
    contacts: [
      { positionKey: 'contacts_data.positions.position6', phone: '+7 (700) 000-00-06' },
      { positionKey: 'contacts_data.positions.position7', phone: '+7 (700) 000-00-07' },
    ],
  },
];

export const affiliatedCompany: AffiliatedCompany = {
  nameKey: 'contacts_data.affiliated.name',
  descriptionKey: 'contacts_data.affiliated.description',
  detailsKey: 'contacts_data.affiliated.details',
  tagKeys: [
    'contacts_data.affiliated.tag1',
    'contacts_data.affiliated.tag2',
  ],
  office: {
    id: 'office-affiliated',
    nameKey: 'contacts_data.offices.affiliated.name',
    addressKey: 'contacts_data.offices.affiliated.address',
    contacts: [
      { positionKey: 'contacts_data.positions.position8', phone: '+7 (700) 000-00-08' },
      { positionKey: 'contacts_data.positions.position9', phone: '+7 (700) 000-00-09' },
    ],
  },
};
