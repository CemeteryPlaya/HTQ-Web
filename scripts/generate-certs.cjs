/**
 * Generate self-signed SSL certificate for local-network WebRTC testing.
 */
const selfsigned = require('selfsigned');
const { writeFileSync, mkdirSync } = require('fs');
const { join } = require('path');
const { networkInterfaces } = require('os');

async function main() {
  const certsDir = join(__dirname, '..', 'infra', 'certs');
  mkdirSync(certsDir, { recursive: true });

  const lanIps = [];
  for (const [, addrs] of Object.entries(networkInterfaces())) {
    for (const addr of addrs || []) {
      if (addr.family === 'IPv4' && !addr.internal) lanIps.push(addr.address);
    }
  }

  console.log('LAN IPs:', lanIps.join(', ') || 'none');

  const altNames = [
    { type: 2, value: 'localhost' },
    { type: 7, ip: '127.0.0.1' },
    ...lanIps.map(ip => ({ type: 7, ip })),
  ];

  const pems = await selfsigned.generate(
    [{ name: 'commonName', value: 'HTQWeb Local Dev' }],
    {
      algorithm: 'sha256',
      days: 365,
      keySize: 2048,
      extensions: [
        { name: 'subjectAltName', altNames },
        { name: 'basicConstraints', cA: false },
        { name: 'keyUsage', digitalSignature: true, keyEncipherment: true },
        { name: 'extKeyUsage', serverAuth: true },
      ],
    }
  );

  const cert = pems.cert;
  const key = pems.private || pems.key;

  writeFileSync(join(certsDir, 'cert.pem'), cert);
  writeFileSync(join(certsDir, 'key.pem'), key);

  console.log('✅ cert:', join(certsDir, 'cert.pem'));
  console.log('✅ key: ', join(certsDir, 'key.pem'));
}

main().catch(e => { console.error(e); process.exit(1); });
