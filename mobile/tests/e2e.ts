// Сквозной тест: настоящий мобильный протокол против настоящего сервера на ноуте.
// Запуск: PORT=8765 S=<секрет из QR> npx tsx tests/e2e.ts
import { randomBytes } from 'node:crypto';
import { ApiError, Client, Creds, Deps, hmacHex, pair, parsePairLink } from '../src/protocol';
import { findLaptop } from '../src/discovery';

const deps: Deps = { fetch: globalThis.fetch, rng: (n) => new Uint8Array(randomBytes(n)) };
const base = `http://127.0.0.1:${process.env.PORT}`;
const out = (k: string, v: unknown) => console.log(JSON.stringify({ [k]: v }));

async function kind(p: Promise<unknown>): Promise<string> {
  try { await p; return 'ok'; } catch (e) { return e instanceof ApiError ? e.kind : 'crash:' + String(e); }
}

(async () => {
  const S = process.env.S!;
  out('parsePairLink', parsePairLink(`${base}/#p=${S}`)?.base === base);
  out('parsePairLink(мусор)', parsePairLink('https://example.com/#p=123'));

  out('wrong_code', await kind(pair(base, '00'.repeat(16), deps, undefined, 200)));
  const creds: Creds = await pair(base, S, deps, (p) => out('phase', p), 250);
  out('paired', creds.devid.length === 32 && creds.k.length === 64);

  const c = new Client(creds, deps);
  out('ping', (await c.call({ a: 'ping' })).ok);
  out('stats', 'cpu' in (await c.call({ a: 'stats' })));
  out('shot', ((await c.call({ a: 'shot' })).img as string).startsWith('data:image/jpeg'));
  out('move(control on)', (await c.call({ a: 'move', dx: 1, dy: 1 })).ok);

  const power = await c.call({ a: 'power', m: 'shutdown' }).catch((e: ApiError) => e);
  out('power(default OFF)', [(power as ApiError).kind, (power as ApiError).detail?.cap]);

  c.skew = -500; // телефон «в прошлом»: должен сам подстроиться по X-Now
  out('clock_skew_recovers', (await c.call({ a: 'ping' })).ok);

  const bad = new Client({ ...creds, k: '11'.repeat(32) }, deps);
  out('wrong_key', await kind(bad.call({ a: 'ping' })));

  const lost = new Client({ ...creds, base: `http://127.0.0.77:${process.env.PORT}` }, deps);
  out('discovery(IP сменился)', await findLaptop(lost, deps));
  // файлы: загрузка с подписью и скачивание по подписанной ссылке
  const name = 'отчёт Q4.txt', body = Buffer.from('привет из DaSync, ' + 'x'.repeat(5000));
  const up = c.signUpload(name, body.length);
  const ur = await fetch(up.url, { method: 'POST', headers: up.headers, body });
  out('upload', [ur.status, (await ur.json()).name]);
  const wrong = c.signUpload(name, body.length + 1); // подпись на другой размер
  out('upload(подпись не сходится)', (await fetch(wrong.url, { method: 'POST', headers: wrong.headers, body })).status);
  const list = await c.call({ a: 'files' });
  out('files_list', list.files.map((f: any) => [f.name, f.size]));
  const dl = await fetch(c.signedFileUrl(name));
  out('download', [dl.status, (await dl.text()).startsWith('привет из DaSync')]);
  out('download(чужое имя)', (await fetch(c.signedFileUrl(name).replace(encodeURIComponent(name), 'secret.txt'))).status);
  out('file_del', (await c.call({ a: 'file_del', name })).ok);
  out('server_proves_itself', true);
})().catch((e) => { console.error('FAIL', e); process.exit(1); });

