import { describe, expect, it } from 'vitest';

import { companyFromHost, parentDomain } from './companySwitch';

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
