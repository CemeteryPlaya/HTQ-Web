#!/usr/bin/env node

/**
 * SFU Configuration Checker
 * 
 * Этот скрипт проверяет конфигурацию SFU и выявляет типичные проблемы
 * с видео/аудио потоками между клиентами.
 * 
 * ЗАПУСК:
 *   node scripts/check-sfu-config.js
 */

import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = join(__dirname, '..');

console.log('🔍 SFU Configuration Checker');
console.log('=' .repeat(60));

let hasErrors = false;
let hasWarnings = false;

function check(description, condition, recommendation) {
  if (condition) {
    console.log(`✅ ${description}`);
  } else {
    console.log(`❌ ${description}`);
    console.log(`   💡 ${recommendation}`);
    hasErrors = true;
  }
}

function warn(description, recommendation) {
  console.log(`⚠️  ${description}`);
  console.log(`   💡 ${recommendation}`);
  hasWarnings = true;
}

// 1. Проверка existence .env файла
console.log('\n📁 Проверка конфигурационных файлов:');

const sfuEnvPath = join(rootDir, 'sfu', '.env');
const sfuEnvExists = existsSync(sfuEnvPath);

check(
  'sfu/.env файл существует',
  sfuEnvExists,
  'Создайте файл sfu/.env на основе sfu/.env.example'
);

let sfuEnv = {};
if (sfuEnvExists) {
  try {
    const sfuEnvContent = readFileSync(sfuEnvPath, 'utf-8');
    sfuEnvContent.split('\n').forEach(line => {
      line = line.trim();
      if (line && !line.startsWith('#')) {
        const [key, ...valueParts] = line.split('=');
        if (key && valueParts.length > 0) {
          sfuEnv[key.trim()] = valueParts.join('=').trim();
        }
      }
    });
  } catch (e) {
    console.log(`❌ Ошибка чтения sfu/.env: ${e.message}`);
    hasErrors = true;
  }
}

// 2. Проверка WEBRTC_LISTEN_IP
console.log('\n🌐 Проверка WebRTC сетевых настроек:');

const listenIp = sfuEnv.WEBRTC_LISTEN_IP || '0.0.0.0';
const announcedIp = sfuEnv.WEBRTC_ANNOUNCED_IP || '';

check(
  `WEBRTC_LISTEN_IP=${listenIp}`,
  listenIp === '0.0.0.0' || listenIp === '::',
  'Установите WEBRTC_LISTEN_IP=0.0.0.0 для прослушивания всех интерфейсов'
);

check(
  `WEBRTC_ANNOUNCED_IP=${announcedIp}`,
  announcedIp.length > 0 && announcedIp !== '0.0.0.0' && announcedIp !== '127.0.0.1',
  'Установите WEBRTC_ANNOUNCED_IP=<публичный_IP_сервера> в sfu/.env. Это КРИТИЧЕСКИ важно для работы видео между компьютерами!'
);

if (announcedIp) {
  const isPrivateIp = announcedIp.startsWith('10.') || 
                      announcedIp.startsWith('192.168.') ||
                      announcedIp.startsWith('172.16.') ||
                      announcedIp.startsWith('127.');
  
  if (isPrivateIp) {
    warn(
      `WEBRTC_ANNOUNCED_IP=${announcedIp} - это приватный IP`,
      'Для работы через интернет используйте публичный IP сервера. Для LAN тестов можно оставить приватный IP.'
    );
  }
}

// 3. Проверка портов
console.log('\n🔌 Проверка портов:');

const sfuPort = parseInt(sfuEnv.SFU_PORT || '4443', 10);
const webRtcPort = parseInt(sfuEnv.WEBRTC_SERVER_PORT || '44444', 10);

check(
  `SFU_PORT=${sfuPort} (WebSocket signaling)`,
  sfuPort > 0 && sfuPort < 65536,
  'Установите корректный SFU_PORT (например 4443)'
);

check(
  `WEBRTC_SERVER_PORT=${webRtcPort} (WebRTC media)`,
  webRtcPort > 0 && webRtcPort < 65536,
  'Установите корректный WEBRTC_SERVER_PORT (например 44444)'
);

// 4. Проверка TCP_TUNNEL_MODE
console.log('\n🚇 Проверка режима работы:');

const tcpTunnelMode = sfuEnv.TCP_TUNNEL_MODE === 'true' || sfuEnv.TCP_TUNNEL_MODE === '1';

if (tcpTunnelMode) {
  console.log('ℹ️  TCP_TUNNEL_MODE включен');
  console.log('   • UDP отключен, работает только TCP');
  console.log('   • Необходимо для туннелей (ngrok, bore и т.д.)');
  console.log('   • Убедитесь что туннель правильно настроен');
} else {
  console.log('ℹ️  UDP+TCP режим (по умолчанию)');
  console.log('   • Откройте порты 44444/udp и 44444/tcp в firewall');
}

// 5. Проверка TURN
console.log('\n🔄 Проверка TURN сервера:');

const turnUrls = sfuEnv.TURN_URLS || '';
const turnUsername = sfuEnv.TURN_USERNAME || '';
const turnCredential = sfuEnv.TURN_CREDENTIAL || '';

if (turnUrls) {
  console.log(`✅ TURN_URLS настроены: ${turnUrls.split(',')[0]}${turnUrls.split(',').length > 1 ? '...' : ''}`);
  check(
    'TURN_USERNAME задан',
    turnUsername.length > 0,
    'Установите TURN_USERNAME в sfu/.env'
  );
  check(
    'TURN_CREDENTIAL задан',
    turnCredential.length > 0,
    'Установите TURN_CREDENTIAL в sfu/.env'
  );
} else {
  warn(
    'TURN сервер не настроен',
    'Для работы через интернет (за NAT) рекомендуется настроить TURN сервер. Без него видео может не работать между разными сетями.'
  );
}

// 6. Проверка TLS
console.log('\n🔒 Проверка TLS/SSL:');

const tlsCert = sfuEnv.TLS_CERT || '';
const tlsKey = sfuEnv.TLS_KEY || '';

if (tlsCert && tlsKey) {
  const certExists = existsSync(join(rootDir, 'sfu', tlsCert));
  const keyExists = existsSync(join(rootDir, 'sfu', tlsKey));
  
  check(
    `TLS сертификат существует (${tlsCert})`,
    certExists,
    'Создайте или получите TLS сертификат. Для тестов используйте scripts/generate-certs.mjs'
  );
  
  check(
    `TLS ключ существует (${tlsKey})`,
    keyExists,
    'Создайте или получите TLS ключ. Для тестов используйте scripts/generate-certs.mjs'
  );
} else {
  warn(
    'TLS не настроен',
    'Без HTTPS браузер может блокировать доступ к камере/микрофону. Используйте ngrok/instatunnel для HTTPS туннеля или настройте TLS сертификаты.'
  );
}

// 7. Проверка кодеков
console.log('\n🎬 Проверка медиа кодеков:');

const mediaCodecsPath = join(rootDir, 'sfu', 'src', 'media-codecs.ts');
const mediaCodecsExists = existsSync(mediaCodecsPath);

check(
  'media-codecs.ts существует',
  mediaCodecsExists,
  'Файл sfu/src/media-codecs.ts должен существовать с настройками кодеков'
);

if (mediaCodecsExists) {
  try {
    const mediaCodecsContent = readFileSync(mediaCodecsPath, 'utf-8');
    
    check(
      'Opus аудио кодек настроен',
      mediaCodecsContent.includes('audio/opus'),
      'Добавьте аудио кодек Opus в media-codecs.ts'
    );
    
    const hasVp8 = mediaCodecsContent.includes('video/VP8') || mediaCodecsContent.includes('video/vp8');
    const hasH264 = mediaCodecsContent.includes('video/H264') || mediaCodecsContent.includes('video/h264');
    
    check(
      'VP8 видео кодек настроен',
      hasVp8,
      'Добавьте видео кодек VP8 в media-codecs.ts для максимальной совместимости'
    );
    
    check(
      'H264 видео кодек настроен',
      hasH264,
      'Добавьте видео кодек H264 в media-codecs.ts для совместимости'
    );
    
    if (hasVp8 && hasH264) {
      console.log('✅ Оба видео кодека (VP8 + H264) настроены - отлично!');
    } else if (hasVp8 || hasH264) {
      warn(
        'Настроен только один видео кодек',
        'Рекомендуется иметь оба кодека (VP8 + H264) для максимальной совместимости с разными браузерами'
      );
    }
  } catch (e) {
    console.log(`❌ Ошибка чтения media-codecs.ts: ${e.message}`);
    hasErrors = true;
  }
}

// 8. Проверка битрейта
console.log('\n📊 Проверка битрейта:');

const videoBitrate = parseInt(sfuEnv.VIDEO_BITRATE_BPS || '1500000', 10);
const audioBitrate = parseInt(sfuEnv.AUDIO_BITRATE_BPS || '64000', 10);

check(
  `VIDEO_BITRATE_BPS=${videoBitrate} (${(videoBitrate / 1000000).toFixed(1)} Mbps)`,
  videoBitrate >= 500000 && videoBitrate <= 8000000,
  'Установите VIDEO_BITRATE_BPS между 500000 (0.5 Mbps) и 8000000 (8 Mbps). Рекомендуемо: 1500000 (1.5 Mbps)'
);

check(
  `AUDIO_BITRATE_BPS=${audioBitrate} (${(audioBitrate / 1000).toFixed(0)} kbps)`,
  audioBitrate >= 32000 && audioBitrate <= 192000,
  'Установите AUDIO_BITRATE_BPS между 32000 (32 kbps) и 192000 (192 kbps). Рекомендуемо: 64000 (64 kbps)'
);

// 9. Итоговая сводка
console.log('\n' + '='.repeat(60));

if (hasErrors) {
  console.log('\n❌ Найдены критические ошибки!');
  console.log('   Исправьте все ошибки (❌) перед запуском SFU сервера.');
  console.log('   Предупреждения (⚠️) могут быть проигнорированы для тестов.');
  process.exit(1);
} else if (hasWarnings) {
  console.log('\n⚠️  Конфигурация рабочая, но есть рекомендации');
  console.log('   Сервер должен запуститься, но рекомендуется исправить предупреждения.');
  console.log('   Для production используйте все рекомендации.');
  process.exit(0);
} else {
  console.log('\n✅ Конфигурация отличная!');
  console.log('   Все проверки пройдены. SFU сервер должен работать корректно.');
  console.log('   Для запуска: cd sfu && npm start');
  process.exit(0);
}
