/**
 * Метрики SFU для Prometheus.
 *
 * У mediasoup своего /metrics нет, поэтому экспорт живёт здесь и снимается
 * с тех же структур, которыми сервер управляет комнатами. Числа собираются
 * НА СКРЕЙПЕ (`collect()` у gauge), а не по таймеру: состояние конференции
 * меняется каждую секунду, и любой кэш давал бы устаревшую картину именно
 * в тот момент, когда на неё смотрят — во время инцидента со звонком.
 *
 * Сервер держит структуры у себя, а сюда передаёт функцию-снимок: иначе
 * получился бы цикл импортов server ↔ metrics.
 */
import {
  Registry,
  Gauge,
  collectDefaultMetrics,
  type Metric,
} from 'prom-client';
import { fallback, fallbackTotal } from './fallback.js';

/** Снимок состояния SFU на момент скрейпа. */
export interface SfuSnapshot {
  /** Живые комнаты. */
  rooms: number;
  /** Открытые WebSocket-сигналинга (включая тех, кто ещё не вошёл в комнату). */
  connections: number;
  /** Участники во всех комнатах суммарно. */
  peers: number;
  transports: number;
  producers: number;
  consumers: number;
}

export const registry = new Registry();

// Стандартные метрики процесса: heap, лаг event-loop, дескрипторы, CPU.
// Для Node-сервиса это половина диагностики — лаг event-loop объясняет
// рассыпающийся звук раньше, чем любые прикладные счётчики.
collectDefaultMetrics({ register: registry, prefix: 'sfu_process_' });

// Счётчик подмен объявлен в fallback.ts (чтобы тот ничего не импортировал
// отсюда и не образовал цикл), а на реестр кладётся здесь — вместе со всеми
// остальными метриками SFU, одним экспортом.
registry.registerMetric(fallbackTotal);

let snapshotSource: (() => SfuSnapshot) | null = null;

function gauge(name: string, help: string, pick: (s: SfuSnapshot) => number): void {
  const metric: Metric = new Gauge({
    name,
    help,
    registers: [registry],
    collect() {
      const source = snapshotSource;
      if (!source) {
        // Раньше здесь стоял `: 0`, и это была ложь: «источник не привязан» и
        // «в конференции никого» выглядели одинаково. Ноль в дежурной панели
        // читается как «всё тихо», а не как «метрики сломаны».
        //
        // Достижимо только если порядок в main() поедет: bindSnapshotSource
        // вызывается до httpServer.listen, то есть до первого скрейпа.
        // Значение не трогаем вовсе — пусть остаётся прежним.
        fallback('sfu.metrics.no_snapshot_source', null, {
          reason: 'источник снимка не привязан — гейджи не обновляются',
          context: { metric: name },
        });
        return;
      }
      // `this` — сам gauge; типы prom-client это допускают.
      (this as Gauge).set(pick(source()));
    },
  });
  void metric;
}

gauge('sfu_rooms', 'Активные комнаты конференции', (s) => s.rooms);
gauge('sfu_signaling_connections', 'Открытые WebSocket-соединения сигналинга', (s) => s.connections);
gauge('sfu_peers', 'Участники во всех комнатах', (s) => s.peers);
gauge('sfu_transports', 'Открытые WebRTC-транспорты', (s) => s.transports);
gauge('sfu_producers', 'Активные producers (исходящие потоки)', (s) => s.producers);
gauge('sfu_consumers', 'Активные consumers (входящие потоки)', (s) => s.consumers);

/** Подключить источник данных. Вызывается один раз при старте сервера. */
export function bindSnapshotSource(source: () => SfuSnapshot): void {
  snapshotSource = source;
}

export async function renderMetrics(): Promise<{ body: string; contentType: string }> {
  return {
    body: await registry.metrics(),
    contentType: registry.contentType,
  };
}
