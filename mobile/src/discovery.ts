import { Client, Creds } from './protocol';
import type { Deps } from './protocol';

/**
 * Если у ноутбука сменился IP, ищем его в той же подсети /24 по порту DaSync
 * и подтверждаем подписанным запросом, чтобы не подключиться к чужому устройству.
 */
export async function findLaptop(client: Client, deps: Deps): Promise<string | null> {
  const m = client.base.match(/^http:\/\/(\d+\.\d+\.\d+)\.\d+:(\d+)$/);
  if (!m) return null;
  const [, prefix, port] = m;
  const hosts = Array.from({ length: 254 }, (_, i) => `http://${prefix}.${i + 1}:${port}`);
  let found: string | null = null;
  let idx = 0;

  async function probe(host: string): Promise<boolean> {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 700);
    try {
      const r = await deps.fetch(host + '/manifest.json', { signal: ctl.signal });
      const j: any = await r.json();
      if (j.short_name !== 'DaSync') return false;
      const creds: Creds = { ...client.creds, base: host };
      await new Client(creds, deps).call({ a: 'ping' });
      return true;
    } catch {
      return false;
    } finally {
      clearTimeout(t);
    }
  }

  async function worker() {
    while (found === null && idx < hosts.length) {
      const h = hosts[idx++];
      if (await probe(h)) found = h;
    }
  }
  await Promise.all(Array.from({ length: 40 }, worker));
  return found;
}
