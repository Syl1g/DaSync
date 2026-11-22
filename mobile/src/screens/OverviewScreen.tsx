import { useEffect, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import Svg, { Polyline } from 'react-native-svg';
import { Card, Ring } from '../components';
import { colorFor, dur, gb, rate } from '../format';
import { useSession } from '../session';
import { C } from '../theme';

type Stats = {
  cpu: number;
  ram: { pct: number; used: number; total: number };
  disk: { pct: number; free: number };
  net: { down: number; up: number };
  bat: null | { pct: number; plugged: boolean; left: number | null };
  temp: number | null;
  uptime: number;
  host: string;
};

export default function OverviewScreen() {
  const { call } = useSession();
  const [s, setS] = useState<Stats | null>(null);
  const [hist, setHist] = useState<number[]>([]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await call({ a: 'stats' });
      if (alive && r && r.cpu !== undefined) {
        setS(r);
        setHist((h) => [...h.slice(-59), r.cpu]);
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [call]);

  if (!s) return <Text style={{ color: C.dim, textAlign: 'center', marginTop: 60 }}>Собираю данные…</Text>;

  const W = 280, H = 56;
  const pts = hist.map((v, i) => `${(i / 59) * W},${H - 4 - (v / 100) * (H - 8)}`).join(' ');
  const bat = s.bat;

  return (
    <ScrollView contentContainerStyle={{ padding: 14, gap: 12 }}>
      <Text style={{ color: C.dim }}>{s.host} · включён {dur(s.uptime)}</Text>
      <Card>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          <Ring value={s.cpu} label="Процессор" sub={s.temp != null ? `${s.temp} °C` : 'нагрузка'} color={colorFor(s.cpu)} />
          <Ring value={s.ram.pct} label="Память" sub={`${gb(s.ram.used)} из ${gb(s.ram.total)}`} color={colorFor(s.ram.pct)} />
          <Ring value={s.disk.pct} label="Диск" sub={`свободно ${gb(s.disk.free)}`} color={colorFor(s.disk.pct, 85, 95)} />
          <Ring
            value={bat ? bat.pct : 0}
            label="Батарея"
            sub={!bat ? 'батареи нет' : bat.plugged ? 'заряжается' : bat.left ? `ещё ${Math.floor(bat.left / 3600)} ч ${Math.floor((bat.left % 3600) / 60)} мин` : 'от батареи'}
            color={bat && bat.pct <= 15 && !bat.plugged ? C.bad : bat && bat.pct <= 30 && !bat.plugged ? C.warn : C.ok}
          />
        </View>
      </Card>
      <Card>
        <Text style={{ color: C.dim, marginBottom: 6 }}>Процессор за последнюю минуту</Text>
        <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <Polyline points={pts} fill="none" stroke={C.accent} strokeWidth={2} strokeLinejoin="round" />
        </Svg>
      </Card>
      <View style={{ flexDirection: 'row', gap: 12 }}>
        <Card style={{ flex: 1 }}>
          <Text style={{ color: C.ok, fontSize: 20, fontWeight: '700' }}>↓ {rate(s.net.down)}</Text>
          <Text style={{ color: C.dim, fontSize: 12 }}>загрузка</Text>
        </Card>
        <Card style={{ flex: 1 }}>
          <Text style={{ color: C.warn, fontSize: 20, fontWeight: '700' }}>↑ {rate(s.net.up)}</Text>
          <Text style={{ color: C.dim, fontSize: 12 }}>отдача</Text>
        </Card>
      </View>
    </ScrollView>
  );
}
