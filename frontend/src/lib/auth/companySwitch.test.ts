import { afterEach, describe, expect, it, vi } from 'vitest';

import { companyFromHost, hostLabelOf, parentDomain, switchCompany } from './companySwitch';

describe('companyFromHost', () => {
  it('извлекает компанию из поддомена', () => {
    expect(companyFromHost('kz.example.kz')).toBe('kz');
    expect(companyFromHost('htq-uz.example.kz')).toBe('htq-uz');
  });

  it('возвращает null для голого домена', () => {
    expect(companyFromHost('example.kz')).toBeNull();
  });

  it('возвращает null для localhost без поддомена', () => {
    expect(companyFromHost('localhost')).toBeNull();
  });

  it('работает с localhost-поддоменами в разработке', () => {
    expect(companyFromHost('kz.localhost')).toBe('kz');
  });

  it('игнорирует порт', () => {
    expect(companyFromHost('kz.localhost:3000')).toBe('kz');
  });

  // Три случая ниже проверяют согласование с регуляркой nginx
  // (infra/nginx/default.conf, server_name) — расхождение здесь означает,
  // что фронт считает себя внутри компании, а шлюз заголовок X-HTQ-Company
  // не поставит, и запрос молча уйдёт в схему public.

  it('не считает "www" компанией — это общий домен, а не поддомен-компания', () => {
    expect(companyFromHost('www.example.kz')).toBeNull();
  });

  it('не считает IP-адрес компанией — имя компании обязано начинаться с буквы', () => {
    expect(companyFromHost('192.168.1.10')).toBeNull();
  });

  it('не даёт компанию, если после неё голый однословный корень (не localhost)', () => {
    // "kz.co" -> формально похоже на "компания.корень", но корень "co" —
    // не localhost и не содержит своей точки, поэтому по регулярке nginx
    // это не матчится вовсе (и не должно матчиться на фронте).
    expect(companyFromHost('kz.co')).toBeNull();
  });

  it('не зависит от регистра хоста — nginx приводит Host к нижнему регистру до сравнения', () => {
    expect(companyFromHost('KZ.EXAMPLE.KZ')).toBe('kz');
  });
});

describe('parentDomain', () => {
  it('отбрасывает поддомен компании', () => {
    // Домен refresh-cookie: он обязан быть общим для всех компаний,
    // иначе переключение выглядит как разлогин.
    expect(parentDomain('kz.example.kz')).toBe('.example.kz');
  });

  it('оставляет голый домен как есть', () => {
    expect(parentDomain('example.kz')).toBe('.example.kz');
  });

  it('не ставит точку перед localhost', () => {
    expect(parentDomain('kz.localhost')).toBe('localhost');
  });
});

describe('switchCompany', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('ведёт на псевдоним, когда он есть', () => {
    const assign = vi.fn();
    vi.stubGlobal('location', {
      host: 'htq.htq.group', pathname: '/hr/employees', search: '', hash: '',
      protocol: 'https:', assign,
    });

    switchCompany({ slug: 'hi-tech-systems', subdomain: 'hts' });

    expect(assign).toHaveBeenCalledWith('https://hts.htq.group/hr/employees');
  });

  it('ведёт на слаг, когда псевдонима нет', () => {
    const assign = vi.fn();
    vi.stubGlobal('location', {
      host: 'acme.htq.group', pathname: '/', search: '', hash: '',
      protocol: 'https:', assign,
    });

    switchCompany({ slug: 'beta' });

    expect(assign).toHaveBeenCalledWith('https://beta.htq.group/');
  });

  it('без второго аргумента сохраняет текущий путь, query и hash', () => {
    const assign = vi.fn();
    vi.stubGlobal('location', {
      host: 'htq.localhost:3000', pathname: '/hr/employees', search: '?tab=cards', hash: '#top',
      protocol: 'http:', assign,
    });

    switchCompany({ slug: 'hi-tech-systems', subdomain: null });

    expect(assign).toHaveBeenCalledWith('http://hi-tech-systems.localhost:3000/hr/employees?tab=cards#top');
  });

  it('с целевым путём ведёт на него, а не на текущий', () => {
    // Экран выбора компании: человек пришёл на голый домен по глубокой
    // ссылке, RequireAuth увёл его на /companies/choose — вернуть надо туда,
    // куда он шёл, а не на сам экран выбора.
    const assign = vi.fn();
    vi.stubGlobal('location', {
      host: 'htq.group', pathname: '/companies/choose', search: '', hash: '',
      protocol: 'https:', assign,
    });

    switchCompany({ slug: 'hi-tech-qazaqstan', subdomain: 'htq' }, '/hr/employees?tab=cards#top');

    expect(assign).toHaveBeenCalledWith('https://htq.htq.group/hr/employees?tab=cards#top');
  });
});

describe('hostLabelOf', () => {
  it('берёт псевдоним, если он задан', () => {
    expect(hostLabelOf({ slug: 'hi-tech-qazaqstan', subdomain: 'htq' })).toBe('htq');
  });

  it('берёт слаг, если псевдонима нет или он пуст', () => {
    expect(hostLabelOf({ slug: 'beta' })).toBe('beta');
    expect(hostLabelOf({ slug: 'beta', subdomain: null })).toBe('beta');
    expect(hostLabelOf({ slug: 'beta', subdomain: '' })).toBe('beta');
  });
});
