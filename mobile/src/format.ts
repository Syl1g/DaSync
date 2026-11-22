export const gb = (b: number) => (b / 1073741824).toFixed(b >= 1.07e10 ? 0 : 1) + ' ГБ';
export const rate = (b: number) =>
  b >= 1048576 ? (b / 1048576).toFixed(1) + ' МБ/с' : Math.round(b / 1024) + ' КБ/с';
export function dur(s: number) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return (d ? d + ' д ' : '') + (h ? h + ' ч ' : '') + m + ' мин';
}
export const colorFor = (p: number, warn = 75, bad = 90) => (p >= bad ? '#ff7a8a' : p >= warn ? '#e8b04b' : '#5cc98a');
export const fsz = (b: number) =>
  b >= 1073741824 ? (b / 1073741824).toFixed(1) + ' ГБ' : b >= 1048576 ? (b / 1048576).toFixed(1) + ' МБ' : Math.max(1, Math.round(b / 1024)) + ' КБ';
