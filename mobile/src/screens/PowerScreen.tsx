import { useEffect, useState } from 'react';
import { Alert, ScrollView, Text, View } from 'react-native';
import { Btn, Card } from '../components';
import { useSession } from '../session';
import { C } from '../theme';

const TIMERS: [string, number][] = [['15 мин', 15], ['30 мин', 30], ['1 час', 60], ['2 часа', 120]];

export default function PowerScreen() {
  const { call, notify, disconnect } = useSession();
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const r = await call({ a: 'stats' });
      if (alive && r) setLeft(r.timer ?? null);
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(id); };
  }, [call]);

  const confirm = (title: string, text: string, ok: () => void) =>
    Alert.alert(title, text, [{ text: 'Отмена', style: 'cancel' }, { text: 'Да', style: 'destructive', onPress: ok }]);

  return (
    <ScrollView contentContainerStyle={{ padding: 14, gap: 12 }}>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Btn title="Заблокировать" onPress={() => call({ a: 'power', m: 'lock' })} style={{ flex: 1 }} />
        <Btn title="Сон" onPress={() => confirm('Отправить ноутбук в сон?', 'Связь с ним пропадёт.', () => call({ a: 'power', m: 'sleep' }))} style={{ flex: 1 }} />
      </View>
      <Btn title="Выключить сейчас" kind="danger" onPress={() => confirm('Выключить ноутбук?', 'Он выключится прямо сейчас.', () => call({ a: 'power', m: 'shutdown' }))} />
      <Card>
        <Text style={{ color: C.dim, marginBottom: 10 }}>Выключить через…</Text>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {TIMERS.map(([label, min]) => (
            <Btn key={min} title={label} style={{ flex: 1, paddingHorizontal: 2 }}
              onPress={() => confirm(`Выключить через ${label}?`, 'Таймер можно отменить здесь же.', async () => { if (await call({ a: 'timer', min })) setLeft(min * 60); })} />
          ))}
        </View>
        {left != null && (
          <>
            <Text style={{ color: C.warn, marginTop: 12 }}>Выключение через {Math.floor(left / 60)} мин {left % 60} с</Text>
            <Btn title="Отменить таймер" onPress={async () => { if (await call({ a: 'cancel' })) { setLeft(null); notify('Таймер отменён'); } }} style={{ marginTop: 10 }} />
          </>
        )}
      </Card>
      <Text style={{ color: C.dim, fontSize: 12, textAlign: 'center' }}>
        Питание по умолчанию выключено: разреши его в DaSync на ноутбуке → Устройства.
      </Text>
      <Btn title="Отключить это устройство" kind="danger" onPress={() => confirm('Отключиться от ноутбука?', 'Чтобы подключиться снова, надо будет заново отсканировать QR.', disconnect)} style={{ marginTop: 18 }} />
    </ScrollView>
  );
}
