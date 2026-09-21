/**
 * Тесты блокираторов отправки на согласование.
 *
 * Проверяется не «функция возвращает строку», а ДОГОВОР с бэкендом: текст
 * совпадает с тем, что отдаёт `*_service.py` в 409, и — не менее важно —
 * функция НЕ запрещает больше сервера. Ложная блокировка хуже пропущенной:
 * 409 объясняет причину, а погашенная кнопка молчит.
 */
import { describe, expect, it } from 'vitest';

import {
  budgetSubmitBlock,
  counterpartySubmitBlock,
  draftOnlySubmitBlock,
} from './submitBlock';

describe('draftOnlySubmitBlock', () => {
  it('пропускает черновик', () => {
    expect(draftOnlySubmitBlock('draft', 'Черновик', 'договор')).toBeNull();
  });

  it('называет предмет и его текущий статус', () => {
    expect(draftOnlySubmitBlock('signed', 'Подписан', 'договор')).toBe(
      'На согласование отправляется черновик; договор в статусе «Подписан»',
    );
    expect(draftOnlySubmitBlock('closed', 'Закрыта', 'оплата')).toBe(
      'На согласование отправляется черновик; оплата в статусе «Закрыта»',
    );
  });

  it('запирает любой статус, кроме draft', () => {
    // `on_review` — тот самый случай, с которого всё началось: статус
    // проставлен, процесса нет, сервер отвечает 409.
    for (const status of ['on_review', 'approved', 'signed', 'awaiting_accounting', 'closed']) {
      expect(draftOnlySubmitBlock(status, 'Неважно', 'акт')).not.toBeNull();
    }
  });
});

describe('budgetSubmitBlock', () => {
  it('пропускает активный бюджет со строками', () => {
    expect(budgetSubmitBlock('active', 3)).toBeNull();
  });

  it('запирает закрытый', () => {
    expect(budgetSubmitBlock('closed', 3)).toBe(
      'Закрытый бюджет на согласование не отправляется',
    );
  });

  it('запирает пустой', () => {
    expect(budgetSubmitBlock('active', 0)).toBe(
      'В бюджете нет ни одной программы — согласовывать нечего',
    );
  });

  it('молчит про пустоту, когда состав строк неизвестен', () => {
    // Реестр может отдать бюджет без `lines`. Тогда решение за сервером:
    // выдумывать «пустой» из отсутствия данных нельзя.
    expect(budgetSubmitBlock('active', undefined)).toBeNull();
    expect(budgetSubmitBlock('active', null)).toBeNull();
  });

  it('закрытый важнее пустого', () => {
    // Оба запрета сразу — показываем тот, что ближе к причине: бюджет
    // закрыли, а не забыли наполнить.
    expect(budgetSubmitBlock('closed', 0)).toBe(
      'Закрытый бюджет на согласование не отправляется',
    );
  });
});

describe('counterpartySubmitBlock', () => {
  it('запирает заблокированного', () => {
    expect(counterpartySubmitBlock('blocked')).toBe(
      'Заблокированный контрагент на согласование не отправляется',
    );
  });

  it('пропускает активного И неактивного', () => {
    // `inactive` сервер НЕ запрещает — повторять здесь чужую строгость
    // нельзя, иначе кнопка гаснет там, где отправка разрешена.
    expect(counterpartySubmitBlock('active')).toBeNull();
    expect(counterpartySubmitBlock('inactive')).toBeNull();
  });
});
