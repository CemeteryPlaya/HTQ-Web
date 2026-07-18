#!/usr/bin/env node
/**
 * Generate self-signed SSL certificate for local-network WebRTC testing.
 * Uses `selfsigned` package for reliable X.509 generation.
 */

import selfsigned from 'selfsigned';
import { writeFileSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { networkInterfaces } from 'os';

const __dirname = dirname(fileURLToPath(import.meta.url));
const certsDir = join(__dirname, '..', 'infra', 'certs');
mkdirSync(certsDir, { recursive: true });

// Auto-detect LAN IPs
const lanIps = [];
for (const [, addrs] of Object.entries(networkInterfaces())) {
  for (const addr of addrs || []) {
    if (addr.family === 'IPv4' && !addr.internal) {
      lanIps.push(addr.address);
    }
  }
}

console.log('============================================');
console.log('  SSL Certificate Generator (selfsigned)');
console.log('============================================');
console.log(`Output: ${certsDir}`);
console.log(`LAN IPs: ${lanIps.length > 0 ? lanIps.join(', ') : 'none detected'}`);
console.log('');

// Build SAN altNames
const altNames = [
  { type: 2, value: 'localhost' },       // DNS
  { type: 7, ip: '127.0.0.1' },          // IP
  ...lanIps.map(ip => ({ type: 7, ip })), // LAN IPs
];

const attrs = [{ name: 'commonName', value: 'HTQWeb Local Dev' }];

const pems = await selfsigned.generate(attrs, {
  algorithm: 'sha256',
  days: 365,
  keySize: 2048,
  extensions: [
    {
      name: 'subjectAltName',
      altNames,
    },
    {
      name: 'basicConstraints',
      cA: false,
    },
    {
      name: 'keyUsage',
      digitalSignature: true,
      keyEncipherment: true,
    },
    {
      name: 'extKeyUsage',
      serverAuth: true,
    },
  ],
});

const cert = pems.cert;
const key = pems.private || pems.key;

if (!cert || !key) {
  console.error('selfsigned returned:', Object.keys(pems));
  process.exit(1);
}

writeFileSync(join(certsDir, 'cert.pem'), cert);
writeFileSync(join(certsDir, 'key.pem'), key);

console.log('✅ Certificate generated successfully!');
console.log(`   cert: ${join(certsDir, 'cert.pem')}`);
console.log(`   key:  ${join(certsDir, 'key.pem')}`);
console.log('');
console.log('SANs included:');
console.log('   DNS: localhost');
console.log('   IP:  127.0.0.1');
for (const ip of lanIps) {
  console.log(`   IP:  ${ip}`);
}
console.log('');
console.log('Valid for: 1 year');
