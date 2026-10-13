// Synthetic-only, deterministic test fixture generator. No network or environment secrets.
import crypto from 'node:crypto';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
const secret = 'synthetic-ipn-secret-for-isolated-tests-only-0123456789';
// Official NOWPayments Node example (documenter.getpostman.com/view/7907941/2s93JusNJt).
function sortObject(obj) {
  return Object.keys(obj).sort().reduce((result, key) => {
    result[key] = (obj[key] && typeof obj[key] === 'object') ? sortObject(obj[key]) : obj[key];
    return result;
  }, {});
}
const raw = [
 '{"n":1.0,"tiny":1e-7,"edge":0.000001,"large":1e21,"negzero":-0}',
 '{"n":9007199254740993,"fraction":19.99,"long":0.0000012345678901234567}',
 '{"10":10,"2":2,"4294967295":5,"astral":"🙂","שלום":{"nested":[1.0,2.50]}}',
 '{"nested":{"a":null,"b":false,"c":true},"array":[{"z":2,"a":1},0.0000001]}'
];
const vectors = raw.map(raw => {
  const canonical = JSON.stringify(sortObject(JSON.parse(raw)));
  return { raw, canonical, signature: crypto.createHmac('sha512', secret).update(canonical).digest('hex') };
});
const target = new URL('../security_tests/fixtures/nowpayments_node_vectors.json', import.meta.url);
fs.mkdirSync(fileURLToPath(new URL('.', target)), { recursive: true });
fs.writeFileSync(target, JSON.stringify({ schema: 1, generator: 'Official NOWPayments recursive Node sortObject + JSON.stringify + SHA-512 HMAC', vectors }, null, 2) + '\n');
console.log(fileURLToPath(target), 'vectors:', vectors.length);
