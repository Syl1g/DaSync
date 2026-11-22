// Протокол DaSync: сопряжение по одноразовому QR и подпись каждого запроса.
// Чистая логика без привязки к платформе, поэтому её можно тестировать на Node.
import { hmac } from '@noble/hashes/hmac.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, hexToBytes, utf8ToBytes } from '@noble/hashes/utils.js';

export type Creds = { base: string; devid: string; k: string };
export type Deps = {
  fetch: typeof fetch;
  rng: (n: number) => Uint8Array;
};

export const hmacHex = (keyHex: string, msg: string): string =>
  bytesToHex(hmac(sha256, hexToBytes(keyHex), utf8ToBytes(msg)));
export const sha256Hex = (data: string): string => bytesToHex(sha256(utf8ToBytes(data)));

export type ErrorKind =
  | 'auth' | 'denied' | 'blocked' | 'network' | 'paused' | 'locked' | 'server' | 'code' | 'timeout' | 'rejected';

export class ApiError extends Error {
  kind: ErrorKind;
  detail?: { cap?: string; title?: string };
  constructor(kind: ErrorKind, message: string, detail?: { cap?: string; title?: string }) {
    super(message);
    this.kind = kind;
    this.detail = detail;
  }
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

async function timedFetch(f: typeof fetch, url: string, init: RequestInit, ms = 6000): Promise<Response> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    return await f(url, { ...init, signal: ctl.signal });
  } catch {
    throw new ApiError('network', 'Нет связи с ноутбуком');
  } finally {
    clearTimeout(t);
  }
}

/** Разбирает ссылку из QR: http://192.168.1.5:8765/#p=<32 hex> */
export function parsePairLink(text: string): { base: string; secret: string } | null {
  const m = text.trim().match(/^(https?:\/\/[^\s/#]+)\/?#p=([0-9a-f]{32})/i);
  return m ? { base: m[1], secret: m[2].toLowerCase() } : null;
}

export type PairPhase = 'checking' | 'waiting';

export async function pair(
  base: string,
  secret: string,
  deps: Deps,
  onPhase?: (p: PairPhase) => void,
  pollMs = 2000,
): Promise<Creds> {
  const devid = bytesToHex(deps.rng(16));
  const cn = bytesToHex(deps.rng(16));
  onPhase?.('checking');
  const r = await timedFetch(deps.fetch, base + '/pair/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ devid, cn, proof: hmacHex(secret, `pair1|${devid}|${cn}`) }),
  });
  const j: any = await r.json().catch(() => ({}));
  if (r.status === 401) throw new ApiError('code', 'QR устарел: он живёт 2 минуты и работает один раз. Обнови QR на ноутбуке.');
  if (r.status === 403) throw new ApiError(j.error === 'blocked' ? 'blocked' : 'network', j.error === 'blocked' ? 'Ноутбук заблокировал это устройство.' : 'Подключаться можно только из домашней сети.');
  if (r.status === 429) throw new ApiError('locked', 'Слишком много попыток. Подожди минуту.');
  if (r.status === 503) throw new ApiError('paused', 'DaSync на ноутбуке стоит на паузе.');
  if (!r.ok || !j.sn) throw new ApiError('server', 'Ноутбук ответил неожиданно. Попробуй ещё раз.');

  // Ключ вычисляется на обеих сторонах из секрета из QR и по сети не передаётся.
  const k = hmacHex(secret, `key|${devid}|${cn}|${j.sn}`);
  onPhase?.('waiting');
  for (let i = 0; i < 150; i++) {
    await sleep(pollMs);
    let sj: any;
    try {
      const sr = await timedFetch(deps.fetch, base + '/pair/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ devid, mac: hmacHex(k, `status|${devid}`) }),
      });
      sj = await sr.json();
    } catch {
      continue;
    }
    if (sj.status === 'approved') {
      if (sj.mac !== hmacHex(k, `approved|${devid}|${j.sn}`)) {
        throw new ApiError('auth', 'Ответ ноутбука не прошёл проверку. Подключение отменено.');
      }
      return { base, devid, k };
    }
    if (sj.status === 'denied') throw new ApiError('rejected', 'Ноутбук отклонил подключение.');
    if (sj.status === 'none') break;
  }
  throw new ApiError('timeout', 'Запрос не подтвердили на ноутбуке.');
}

export class Client {
  creds: Creds;
  skew = 0;
  private deps: Deps;

  constructor(creds: Creds, deps: Deps) {
    this.creds = creds;
    this.deps = deps;
  }

  get base(): string {
    return this.creds.base;
  }

  setBase(base: string) {
    this.creds = { ...this.creds, base };
  }

  private sign(method: string, path: string, bodyHash: string) {
    const ts = Math.floor(Date.now() / 1000 + this.skew);
    const nonce = bytesToHex(this.deps.rng(8));
    return {
      'X-Dev': this.creds.devid,
      'X-Ts': String(ts),
      'X-Nonce': nonce,
      'X-Sig': hmacHex(this.creds.k, `${method}\n${path}\n${ts}\n${nonce}\n${bodyHash}`),
    };
  }

  private syncClock(r: Response) {
    const n = r.headers.get('X-Now');
    if (n) this.skew = Number(n) - Date.now() / 1000;
  }

  async call<T = any>(body: Record<string, unknown>): Promise<T> {
    const str = JSON.stringify(body);
    const bh = sha256Hex(str);
    for (let n = 0; n < 2; n++) {
      const r = await timedFetch(this.deps.fetch, this.creds.base + '/api', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...this.sign('POST', '/api', bh) },
        body: str,
      });
      this.syncClock(r);
      if (r.ok) return (await r.json()) as T;
      const j: any = await r.json().catch(() => ({}));
      if (r.status === 401) {
        if (j.error === 'ts' && n === 0) continue; // часы разошлись: подстроились по X-Now, пробуем ещё раз
        throw new ApiError('auth', 'Ноутбук не узнал это устройство. Подключи его заново.');
      }
      if (r.status === 429) throw new ApiError('locked', 'Слишком много попыток. Подожди полминуты.');
      if (r.status === 403) {
        if (j.error === 'denied') {
          throw new ApiError('denied', `Нет разрешения: ${j.title ?? j.cap}. Включи в DaSync на ноуте → Устройства.`, { cap: j.cap, title: j.title });
        }
        if (j.error === 'blocked') throw new ApiError('blocked', 'Ноутбук заблокировал это устройство.');
        throw new ApiError('network', 'Ноутбук принимает подключения только из домашней сети.');
      }
      if (r.status === 503) throw new ApiError('paused', 'DaSync на ноутбуке на паузе.');
      throw new ApiError('server', 'Ошибка на стороне ноутбука.');
    }
    throw new ApiError('auth', 'Не удалось подписать запрос.');
  }

  /** Адрес и подписанные заголовки для загрузки файла на ноутбук (тело запроса = сам файл). */
  signUpload(fileName: string, size: number): { url: string; headers: Record<string, string> } {
    const fn = encodeURIComponent(fileName);
    return {
      url: this.creds.base + '/upload',
      headers: { ...this.sign('POST', '/upload', sha256Hex(`${fn}|${size}`)), 'X-Filename': fn },
    };
  }

  /** Ссылка на скачивание файла, действует 5 минут. */
  signedFileUrl(name: string): string {
    const exp = Math.floor(Date.now() / 1000 + this.skew) + 300;
    const sig = hmacHex(this.creds.k, `GET\n/f/${name}\n${exp}`);
    return `${this.creds.base}/f/${encodeURIComponent(name)}?d=${this.creds.devid}&exp=${exp}&sig=${sig}`;
  }
}
