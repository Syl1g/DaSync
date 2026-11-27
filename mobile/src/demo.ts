// Демо-режим: приложение само изображает ноутбук, чтобы можно было всё посмотреть без компьютера.
import { DEMO_DESKTOP_JPEG } from './demoImage';

type DemoFile = { name: string; size: number; ts: number };
const t0 = Date.now();
const now = () => Math.floor(Date.now() / 1000);
let files: DemoFile[] = [
  { name: 'Отчёт Q4.pdf', size: 482113, ts: now() - 3600 },
  { name: 'Фото с отпуска.jpg', size: 3145728, ts: now() - 86400 },
  { name: 'Презентация.pptx', size: 8912345, ts: now() - 172800 },
];
let timerAt: number | null = null;

export function demoAddFile(name: string, size: number) {
  files = [{ name, size, ts: now() }, ...files.filter((f) => f.name !== name)];
}

export function demoCall(body: Record<string, unknown>): any {
  const t = (Date.now() - t0) / 1000;
  switch (body.a) {
    case 'stats': {
      const cpu = Math.max(3, 24 + 14 * Math.sin(t / 3) + 6 * Math.sin(t / 1.3));
      return {
        cpu,
        ram: { pct: 61, used: 9.6e9, total: 15.7e9 },
        disk: { pct: 48, free: 262e9, total: 512e9 },
        net: { down: 180000 + 90000 * Math.sin(t / 2), up: 30000 + 12000 * Math.sin(t / 1.7) },
        bat: { pct: 82, plugged: false, left: 14400 },
        temp: null,
        uptime: 93600 + Math.floor(t),
        host: 'ДЕМО-НОУТБУК',
        timer: timerAt ? Math.max(0, Math.floor((timerAt - Date.now()) / 1000)) : null,
      };
    }
    case 'shot':
      return { img: 'data:image/jpeg;base64,' + DEMO_DESKTOP_JPEG, cx: 0.5 + 0.2 * Math.sin(t / 2), cy: 0.45 + 0.15 * Math.cos(t / 2.5) };
    case 'files':
      return { dir: 'C:\\Users\\Demo\\LaptopHub', files };
    case 'file_del':
      files = files.filter((f) => f.name !== body.name);
      return { ok: true };
    case 'clip_get':
      return { t: 'Привет из демо-ноутбука!' };
    case 'timer':
      timerAt = Date.now() + Number(body.min) * 60000;
      return { ok: true };
    case 'cancel':
      timerAt = null;
      return { ok: true };
    default:
      return { ok: true };
  }
}
