import { Client } from '../src/protocol';
(async () => {
  const c = new Client({ base: 'demo', devid: 'demo', k: '' }, { fetch: globalThis.fetch, rng: (n) => new Uint8Array(n) });
  const s = await c.call({ a: 'stats' });
  console.log(JSON.stringify({ isDemo: c.isDemo, cpu: s.cpu > 0 && s.cpu < 100, host: s.host, bat: s.bat.pct, timer: s.timer }));
  const sh = await c.call({ a: 'shot' });
  console.log(JSON.stringify({ shot: sh.img.startsWith('data:image/jpeg;base64,/9j/'), kb: Math.round(sh.img.length * 0.75 / 1024), cx: sh.cx >= 0 && sh.cx <= 1 }));
  await c.call({ a: 'timer', min: 15 }); console.log(JSON.stringify({ timer: (await c.call({ a: 'stats' })).timer }));
  console.log(JSON.stringify({ files: (await c.call({ a: 'files' })).files.length }), JSON.stringify({ после_удаления: ((await c.call({ a: 'file_del', name: 'Отчёт Q4.pdf' })), (await c.call({ a: 'files' })).files.length) }));
})();
