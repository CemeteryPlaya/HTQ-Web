/**
 * Менеджер комнат — управляет Mediasoup Router, Producer'ами, Consumer'ами
 * и реализует определение активного спикера с динамическим мультиплексированием потоков.
 *
 * Каждая комната создаёт один Router. Участники отправляют (produce) и получают (consume)
 * медиа через WebRtcTransport'ы, привязанные к этому Router'у.
 *
 * Ключевая функция: только топ 1-3 активных спикера получают пересылку в 1080p/12Mbps.
 * Остальные участники получают приостановленные/миниатюрные потоки для экономии пропускной способности.
 */

import { types as mediasoupTypes } from 'mediasoup';
import { mediaCodecs } from './media-codecs.js';
import { config } from './config.js';

// ═══════════════════════════════════════════════════════════
// Типы
// ═══════════════════════════════════════════════════════════

export interface Peer {
  id: string;
  displayName: string;
  transports: Map<string, mediasoupTypes.WebRtcTransport>;
  producers: Map<string, mediasoupTypes.Producer>;
  consumers: Map<string, mediasoupTypes.Consumer>;
  // Отслеживание уровня аудио для определения активного спикера
  audioLevel: number;
  lastAudioLevelUpdate: number;
}

export interface RoomEvents {
  onActiveSpeakersChanged: (speakers: ActiveSpeakerInfo[]) => void;
  onPeerJoined: (peerId: string, displayName: string) => void;
  onPeerLeft: (peerId: string) => void;
  onNewConsumerNeeded: (
    consumingPeerId: string,
    producerPeerId: string,
    producer: mediasoupTypes.Producer
  ) => void;
}

export interface ActiveSpeakerInfo {
  peerId: string;
  audioLevel: number;
  isPrimary: boolean;
}

export interface PeerQualityReport {
  packetLossRate: number;
  rttMs: number;
}

// ═══════════════════════════════════════════════════════════
// Класс комнаты
// ═══════════════════════════════════════════════════════════

export class Room {
  public readonly id: string;
  public readonly router: mediasoupTypes.Router;
  private readonly webRtcServer: mediasoupTypes.WebRtcServer;
  private peers: Map<string, Peer> = new Map();
  private events: RoomEvents;

  private statsInterval: NodeJS.Timeout | null = null;

  // Состояние активного спикера
  private audioLevelObserver: mediasoupTypes.AudioLevelObserver | null = null;
  private readonly MAX_HD_STREAMS = 3; // Топ N спикеров получают 1080p

  private constructor(
    id: string,
    router: mediasoupTypes.Router,
    webRtcServer: mediasoupTypes.WebRtcServer,
    events: RoomEvents
  ) {
    this.id = id;
    this.router = router;
    this.webRtcServer = webRtcServer;
    this.events = events;
  }

  /**
   * Создание новой комнаты с Mediasoup Router.
   */
  static async create(
    worker: mediasoupTypes.Worker,
    webRtcServer: mediasoupTypes.WebRtcServer,
    roomId: string,
    events: RoomEvents
  ): Promise<Room> {
    const router = await worker.createRouter({ mediaCodecs });

    console.log(
      `[Room ${roomId}] Создана с кодеками:`,
      router.rtpCapabilities.codecs?.map((c) => c.mimeType).join(', ')
    );

    const room = new Room(roomId, router, webRtcServer, events);
    room.startActiveSpeakerDetection();
    room.startStatsLogging();

    return room;
  }

  /**
   * Получить RTP-возможности Router'а (отправляются клиентам для загрузки устройства).
   */
  get rtpCapabilities(): mediasoupTypes.RtpCapabilities {
    return this.router.rtpCapabilities;
  }

  /**
   * Получить список существующих участников (для новых подключившихся).
   */
  getParticipants(): Array<{
    peerId: string;
    displayName: string;
    producers: Array<{ producerId: string; kind: string }>;
  }> {
    const result: Array<{
      peerId: string;
      displayName: string;
      producers: Array<{ producerId: string; kind: string }>;
    }> = [];

    for (const [peerId, peer] of this.peers) {
      const producers: Array<{ producerId: string; kind: string }> = [];
      for (const [producerId, producer] of peer.producers) {
        producers.push({ producerId, kind: producer.kind });
      }
      result.push({ peerId, displayName: peer.displayName, producers });
    }

    return result;
  }

  // ─────────────────────────────────────────────────────
  // Жизненный цикл участника
  // ─────────────────────────────────────────────────────

  addPeer(peerId: string, displayName: string): void {
    if (this.peers.has(peerId)) {
      console.warn(`[Room ${this.id}] Участник ${peerId} уже существует`);
      return;
    }

    const peer: Peer = {
      id: peerId,
      displayName,
      transports: new Map(),
      producers: new Map(),
      consumers: new Map(),
      audioLevel: 0,
      lastAudioLevelUpdate: Date.now(),
    };

    this.peers.set(peerId, peer);
    this.events.onPeerJoined(peerId, displayName);
    console.log(`[Room ${this.id}] Участник присоединился: ${displayName} (${peerId})`);
  }

  removePeer(peerId: string): void {
    const peer = this.peers.get(peerId);
    if (!peer) return;

    // Закрываем все consumer'ы
    for (const [, consumer] of peer.consumers) {
      try {
        if (!consumer.closed) {
          consumer.close();
        }
      } catch (error) {
        console.warn(
          `[Room ${this.id}] Не удалось закрыть consumer ${consumer.id} для участника ${peerId}:`,
          error
        );
      }
    }
    peer.consumers.clear();

    // Закрываем все producer'ы (и останавливаем переопределение BWE)
    for (const [producerId, producer] of peer.producers) {
      try {
        if (!producer.closed) {
          producer.close();
        }
      } catch (error) {
        console.warn(
          `[Room ${this.id}] Не удалось закрыть producer ${producerId} для участника ${peerId}:`,
          error
        );
      }
    }
    peer.producers.clear();

    // Закрываем все транспорты
    for (const [, transport] of peer.transports) {
      try {
        if (!transport.closed) {
          transport.close();
        }
      } catch (error) {
        console.warn(
          `[Room ${this.id}] Не удалось закрыть транспорт ${transport.id} для участника ${peerId}:`,
          error
        );
      }
    }
    peer.transports.clear();

    this.peers.delete(peerId);
    this.events.onPeerLeft(peerId);
    console.log(`[Room ${this.id}] Участник вышел: ${peer.displayName} (${peerId})`);
  }

  // ─────────────────────────────────────────────────────
  // Транспорт
  // ─────────────────────────────────────────────────────

  async createWebRtcTransport(
    peerId: string
  ): Promise<{
    transportId: string;
    iceParameters: mediasoupTypes.IceParameters;
    iceCandidates: mediasoupTypes.IceCandidate[];
    dtlsParameters: mediasoupTypes.DtlsParameters;
  }> {
    const peer = this.getPeer(peerId);

    // Используем WebRtcServer (один порт) вместо listenIps (диапазон портов).
    // WebRtcServer уже имеет привязанный корректный IP / announcedAddress.
    const transport = await this.router.createWebRtcTransport({
      webRtcServer: this.webRtcServer,
      enableUdp: config.mediasoup.webRtcTransport.enableUdp,
      enableTcp: config.mediasoup.webRtcTransport.enableTcp,
      preferUdp: config.mediasoup.webRtcTransport.preferUdp,
      preferTcp: config.mediasoup.webRtcTransport.preferTcp,
      initialAvailableOutgoingBitrate:
        config.mediasoup.webRtcTransport.initialAvailableOutgoingBitrate,
    });

    // Устанавливаем максимальный входящий битрейт
    const maxIncomingBitrate = config.mediasoup.webRtcTransport.maxIncomingBitrate;
    if (maxIncomingBitrate > 0) {
      await transport.setMaxIncomingBitrate(maxIncomingBitrate);
    }

    // Мониторинг состояния DTLS на уровне транспорта
    transport.on('dtlsstatechange', (dtlsState: mediasoupTypes.DtlsState) => {
      const logFn = (dtlsState === 'failed' || dtlsState === 'closed') ? console.warn : console.log;
      logFn(
        `[Room ${this.id}] Транспорт ${transport.id} состояние DTLS: ${dtlsState}`
      );
      if (dtlsState === 'failed' || dtlsState === 'closed') {
        transport.close();
      }
    });
    transport.on('icestatechange', (iceState: string) => {
      console.log(`[Room ${this.id}] Транспорт ${transport.id} состояние ICE: ${iceState}`);
    });
    transport.on('@close', () => {
      peer.transports.delete(transport.id);
    });

    peer.transports.set(transport.id, transport);

    return {
      transportId: transport.id,
      iceParameters: transport.iceParameters,
      iceCandidates: transport.iceCandidates,
      dtlsParameters: transport.dtlsParameters,
    };
  }

  async connectTransport(
    peerId: string,
    transportId: string,
    dtlsParameters: mediasoupTypes.DtlsParameters
  ): Promise<void> {
    const peer = this.getPeer(peerId);
    const transport = peer.transports.get(transportId);
    if (!transport) throw new Error(`Транспорт ${transportId} не найден`);

    await transport.connect({ dtlsParameters });
  }

  // ─────────────────────────────────────────────────────
  // Producer (отправка медиа)
  // ─────────────────────────────────────────────────────

  async produce(
    peerId: string,
    transportId: string,
    kind: mediasoupTypes.MediaKind,
    rtpParameters: mediasoupTypes.RtpParameters
  ): Promise<string> {
    const peer = this.getPeer(peerId);
    const transport = peer.transports.get(transportId);
    if (!transport) throw new Error(`Транспорт ${transportId} не найден`);

    const producer = await transport.produce({
      kind,
      rtpParameters: this.enforceTargetBitrates(kind, rtpParameters),
    });

    peer.producers.set(producer.id, producer);

    // Для видео-producer'ов мы больше не ограничиваем битрейт искусственно до 12Mbps —
    // позволяем стандартному GCC управлению перегрузкой работать через TCP.
    if (kind === 'video') {
      // Переопределение BWE убрано. Браузер и сеть сами управляют стабильным битрейтом.
    }

    // Отслеживаем уровни аудио для определения активного спикера
    if (kind === 'audio') {
      this.audioLevelObserver
        ?.addProducer({ producerId: producer.id })
        .catch(() => {
          // Producer может закрыться до присоединения к наблюдателю.
        });

      producer.on('score', (score) => {
        // Используем оценку producer'а как прокси для активности аудио
        // (Реальная реализация использует audioLevelObserver)
      });
    }

    // Уведомляем всех остальных участников о необходимости создать consumer'ы
    for (const [otherPeerId, otherPeer] of this.peers) {
      if (otherPeerId === peerId) continue;
      this.events.onNewConsumerNeeded(otherPeerId, peerId, producer);
    }

    producer.on('transportclose', () => {
      console.log(
        `[Room ${this.id}] Producer ${producer.id} — транспорт закрыт`
      );

      if (producer.kind === 'audio') {
        this.audioLevelObserver
          ?.removeProducer({ producerId: producer.id })
          .catch(() => {
            // Игнорируем гонку с закрытием.
          });
      }

      peer.producers.delete(producer.id);
    });
    producer.on('@close', () => {
      peer.producers.delete(producer.id);
    });

    console.log(
      `[Room ${this.id}] ${peer.displayName} отправляет ${kind} (${producer.id})`
    );

    return producer.id;
  }

  // ─────────────────────────────────────────────────────
  // Consumer (приём медиа)
  // ─────────────────────────────────────────────────────

  async consume(
    consumingPeerId: string,
    transportId: string,
    producerId: string,
    rtpCapabilities: mediasoupTypes.RtpCapabilities
  ): Promise<{
    consumerId: string;
    producerId: string;
    kind: mediasoupTypes.MediaKind;
    rtpParameters: mediasoupTypes.RtpParameters;
    producerPeerId: string;
    producerDisplayName: string;
  } | null> {
    // Проверяем, может ли Router потребить этот producer
    if (!this.router.canConsume({ producerId, rtpCapabilities })) {
      console.warn(
        `[Room ${this.id}] Невозможно потребить producer ${producerId} — несовпадение кодеков`
      );
      return null;
    }

    const consumingPeer = this.getPeer(consumingPeerId);
    const transport = consumingPeer.transports.get(transportId);
    if (!transport) throw new Error(`Транспорт ${transportId} не найден`);

    // Находим участника-владельца producer'а для отображаемого имени
    let producerPeerId = '';
    let producerDisplayName = '';
    for (const [pid, peer] of this.peers) {
      if (peer.producers.has(producerId)) {
        producerPeerId = pid;
        producerDisplayName = peer.displayName;
        break;
      }
    }

    // Если у этого участника уже есть активный consumer для того же producer'а,
    // возвращаем существующую привязку вместо создания дубликатов.
    for (const [, existingConsumer] of consumingPeer.consumers) {
      if (existingConsumer.producerId === producerId && !existingConsumer.closed) {
        return {
          consumerId: existingConsumer.id,
          producerId: existingConsumer.producerId,
          kind: existingConsumer.kind,
          rtpParameters: existingConsumer.rtpParameters,
          producerPeerId,
          producerDisplayName,
        };
      }
    }

    const consumer = await transport.consume({
      producerId,
      rtpCapabilities,
      paused: true, // Стартуем на паузе; клиент возобновит когда будет готов
    });

    consumingPeer.consumers.set(consumer.id, consumer);

    // Все три события приводят к уничтожению Consumer в C++ worker'е.
    // Удаляем его из Map немедленно, чтобы последующий resume() не получил
    // "закрытый" объект и не уронил процесс Node.js.
    const cleanupConsumer = () => {
      consumingPeer.consumers.delete(consumer.id);
      console.log(
        `[Room ${this.id}] Consumer ${consumer.id} удалён из Map (peer: ${consumingPeerId})`
      );
    };

    consumer.on('transportclose', cleanupConsumer);
    consumer.on('producerclose', cleanupConsumer);
    consumer.on('@close', cleanupConsumer);

    return {
      consumerId: consumer.id,
      producerId: consumer.producerId,
      kind: consumer.kind,
      rtpParameters: consumer.rtpParameters,
      producerPeerId,
      producerDisplayName,
    };
  }

  async resumeConsumer(peerId: string, consumerId: string): Promise<void> {
    const peer = this.getPeer(peerId);
    const consumer = peer.consumers.get(consumerId);
    if (!consumer) {
      throw new Error(`Consumer ${consumerId} не найден`);
    }
    // Consumer уничтожается C++ worker'ом мгновенно при закрытии транспорта (DTLS failed).
    // Вызов resume() на закрытом consumer вызовет краш Node.js.
    if (consumer.closed) {
      peer.consumers.delete(consumerId);
      throw new Error(`Consumer ${consumerId} уже закрыт (транспорт завершён)`);
    }
    await consumer.resume();
  }

  async pauseConsumer(peerId: string, consumerId: string): Promise<void> {
    const peer = this.getPeer(peerId);
    const consumer = peer.consumers.get(consumerId);
    if (!consumer) {
      throw new Error(`Consumer ${consumerId} не найден`);
    }
    if (consumer.closed) {
      peer.consumers.delete(consumerId);
      throw new Error(`Consumer ${consumerId} уже закрыт (транспорт завершён)`);
    }
    await consumer.pause();
  }

  hasConsumerForProducer(peerId: string, producerId: string): boolean {
    const peer = this.getPeer(peerId);
    for (const [, consumer] of peer.consumers) {
      if (consumer.producerId === producerId && !consumer.closed) {
        return true;
      }
    }
    return false;
  }

  /**
   * Отчёты о качестве от клиентов используются для модуляции переопределения BWE.
   * Один отчёт распространяется на все видео-producer'ы этого участника.
   */
  handleQualityReport(peerId: string, report: PeerQualityReport): void {
    const peer = this.peers.get(peerId);
    if (!peer) return;

    // Отчёты о качестве от клиентов можно логировать или использовать для метрик,
    // но переопределения BWE отключены для поддержки стабильного TCP-туннелирования.
  }

  // ─────────────────────────────────────────────────────
  // Определение активного спикера и мультиплексирование потоков
  // ─────────────────────────────────────────────────────

  /**
   * Запуск периодического определения активного спикера.
   * Мониторит уровни аудио и динамически переключает,
   * какие видео-потоки пересылаются в полном качестве.
   */
  private startActiveSpeakerDetection(): void {
    // Создаём AudioLevelObserver на Router'е
    this.router
      .createAudioLevelObserver({
        maxEntries: this.MAX_HD_STREAMS,
        threshold: -50,    // Порог dBov для определения "говорит"
        interval: 800,     // Проверка каждые 800мс
      })
      .then((observer) => {
        this.audioLevelObserver = observer;

        observer.on('volumes', (volumes) => {
          const speakers: ActiveSpeakerInfo[] = volumes.map(
            (
              vol: { producer: mediasoupTypes.Producer; volume: number },
              idx: number
            ) => {
              // Находим участника, которому принадлежит этот producer
              const peerId = this.findPeerByProducerId(vol.producer.id);
              if (peerId) {
                const peer = this.peers.get(peerId);
                if (peer) {
                  peer.audioLevel = vol.volume;
                  peer.lastAudioLevelUpdate = Date.now();
                }
              }

              return {
                peerId: peerId || 'unknown',
                audioLevel: vol.volume,
                isPrimary: idx === 0,
              };
            }
          );

          if (speakers.length > 0) {
            this.events.onActiveSpeakersChanged(speakers);
            this.updateStreamMultiplexing(speakers);
          }
        });

        observer.on('silence', () => {
          // Никто не говорит — оставляем последнего активного спикера
        });

        // Добавляем все существующие аудио-producer'ы к наблюдателю
        for (const [, peer] of this.peers) {
          for (const [, producer] of peer.producers) {
            if (producer.kind === 'audio') {
              observer.addProducer({ producerId: producer.id }).catch(() => {
                // Producer мог уже закрыться
              });
            }
          }
        }

        console.log(`[Room ${this.id}] AudioLevelObserver запущен`);
      })
      .catch((err) => {
        console.error(
          `[Room ${this.id}] Не удалось создать AudioLevelObserver:`,
          err
        );
      });
  }

  /**
   * Динамическое мультиплексирование потоков: только топ N спикеров получают полное 1080p.
   * Все остальные видео-consumer'ы ставятся на паузу для экономии пропускной способности.
   */
  private updateStreamMultiplexing(speakers: ActiveSpeakerInfo[]): void {
    // Когда участников мало — не ставим потоки на паузу:
    // все получают видео в полном качестве без фильтрации по активному спикеру.
    if (this.peers.size <= this.MAX_HD_STREAMS) {
      // Возобновляем все видео-consumer'ы (отменяем предыдущие паузы).
      for (const [, peer] of this.peers) {
        for (const [, consumer] of peer.consumers) {
          if (consumer.kind === 'video' && consumer.paused) {
            consumer.resume().catch(() => {});
          }
        }
      }
      return;
    }

    const activePeerIds = new Set(
      speakers.slice(0, this.MAX_HD_STREAMS).map((s) => s.peerId)
    );

    for (const [, peer] of this.peers) {
      for (const [, consumer] of peer.consumers) {
        if (consumer.kind !== 'video' || consumer.closed) continue;

        const producerPeerId = this.findPeerByProducerId(consumer.producerId);
        if (!producerPeerId) continue;

        if (activePeerIds.has(producerPeerId)) {
          if (consumer.paused) {
            consumer.resume().catch(() => {});
          }
        } else {
          if (!consumer.paused) {
            consumer.pause().catch(() => {});
          }
        }
      }
    }
  }

  // ─────────────────────────────────────────────────────
  // Вспомогательные методы
  // ─────────────────────────────────────────────────────

  private getPeer(peerId: string): Peer {
    const peer = this.peers.get(peerId);
    if (!peer) throw new Error(`Участник ${peerId} не найден в комнате ${this.id}`);
    return peer;
  }

  private findPeerByProducerId(producerId: string): string | null {
    for (const [peerId, peer] of this.peers) {
      if (peer.producers.has(producerId)) return peerId;
    }
    return null;
  }

  get peerCount(): number {
    return this.peers.size;
  }

  private enforceTargetBitrates(
    kind: mediasoupTypes.MediaKind,
    rtpParameters: mediasoupTypes.RtpParameters
  ): mediasoupTypes.RtpParameters {
    const encodings =
      rtpParameters.encodings && rtpParameters.encodings.length > 0
        ? rtpParameters.encodings.map((encoding) => ({ ...encoding }))
        : [{}];

    if (kind === 'video') {
      for (const encoding of encodings) {
        encoding.maxBitrate = config.bitrate.videoBps;
      }
    }

    if (kind === 'audio') {
      for (const encoding of encodings) {
        encoding.maxBitrate = config.bitrate.audioBps;
      }
    }

    return {
      ...rtpParameters,
      encodings,
    };
  }

  /**
   * Закрытие комнаты и освобождение всех ресурсов.
   */
  close(): void {
    this.audioLevelObserver?.close();
    this.audioLevelObserver = null;

    for (const [peerId] of this.peers) {
      this.removePeer(peerId);
    }

    this.router.close();
    console.log(`[Room ${this.id}] Закрыта`);
  }

  private startStatsLogging() {
    if (this.statsInterval) clearInterval(this.statsInterval);
    this.statsInterval = setInterval(async () => {
      try {
        console.log(`\n=== [Room ${this.id}] RTP-статистика ===`);
        for (const [peerId, peer] of this.peers) {
          console.log(` Участник ${peer.displayName || peerId}:`);
          for (const [prodId, prod] of peer.producers) {
            const stats = await prod.getStats();
            const s = stats[0] as any;
            if (s) {
              console.log(`  Prod [${prod.kind}] ${prodId} | получено: ${(s.bitrate || 0)/1000} kbps | байты: ${s.byteCount || 0} | пакеты: ${s.packetCount || 0} | потеряно: ${s.packetsLost || 0}`);
            }
          }
          for (const [consId, cons] of peer.consumers) {
            const stats = await cons.getStats();
            const s = stats[0] as any;
            if (s) {
              console.log(`  Cons [${cons.kind}] ${consId} | отправлено: ${(s.bitrate || 0)/1000} kbps | байты: ${s.byteCount || 0} | пакеты: ${s.packetCount || 0} | на паузе: ${cons.paused}`);
            }
          }
        }
        console.log(`=============================\n`);
      } catch (err) {
        console.error(`[Room] Ошибка логирования статистики:`, err);
      }
    }, 5000);
  }
}
