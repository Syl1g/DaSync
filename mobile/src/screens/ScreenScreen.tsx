import { useCallback, useEffect, useRef, useState } from 'react';
import { Image, Pressable, ScrollView, Text, View } from 'react-native';
import { Btn } from '../components';
import { useSession } from '../session';
import { C } from '../theme';

type Mode = 'click' | 'double' | 'right';

export default function ScreenScreen() {
  const { call } = useSession();
  const [uri, setUri] = useState<string | null>(null);
  const [ratio, setRatio] = useState(16 / 9);
  const [cur, setCur] = useState<{ x: number; y: number } | null>(null);
  const [live, setLive] = useState(false);
  const [mode, setMode] = useState<Mode>('click');
  const [size, setSize] = useState({ w: 0, h: 0 });
  const loading = useRef(false);

  const shot = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    const r = await call({ a: 'shot' });
    loading.current = false;
    if (r?.img) {
      setUri(r.img);
      setCur({ x: r.cx, y: r.cy });
      Image.getSize(r.img, (w, h) => setRatio(w / h), () => {});
    } else {
      setLive(false);
    }
  }, [call]);

  useEffect(() => { shot(); }, [shot]);
  useEffect(() => {
    if (!live) return;
    const id = setInterval(shot, 450);
    return () => clearInterval(id);
  }, [live, shot]);

  const tap = async (x: number, y: number) => {
    if (!size.w || !size.h) return;
    const r = await call({ a: 'tap', fx: x / size.w, fy: y / size.h, b: mode === 'right' ? 'right' : 'left', n: mode === 'double' ? 2 : 1 });
    if (r) setTimeout(shot, 450);
  };

  return (
    <ScrollView contentContainerStyle={{ padding: 14, gap: 12 }}>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Btn title="Клик" active={mode === 'click'} onPress={() => setMode('click')} style={{ flex: 1, minHeight: 44 }} />
        <Btn title="Двойной" active={mode === 'double'} onPress={() => setMode('double')} style={{ flex: 1, minHeight: 44 }} />
        <Btn title="Правый" active={mode === 'right'} onPress={() => setMode('right')} style={{ flex: 1, minHeight: 44 }} />
      </View>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Btn title="Обновить" onPress={shot} style={{ flex: 1 }} />
        <Btn title={live ? 'Live: вкл' : 'Live: выкл'} active={live} onPress={() => setLive((v) => !v)} style={{ flex: 1 }} />
      </View>
      <Pressable
        onPress={(e) => tap(e.nativeEvent.locationX, e.nativeEvent.locationY)}
        onLayout={(e) => setSize({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })}
        style={{ width: '100%', aspectRatio: ratio, borderRadius: 16, overflow: 'hidden', backgroundColor: '#000', borderWidth: 1, borderColor: C.line }}
      >
        {uri && <Image source={{ uri }} style={{ width: '100%', height: '100%' }} resizeMode="contain" pointerEvents="none" />}
        {cur && size.w > 0 && (
          <View pointerEvents="none" style={{ position: 'absolute', left: cur.x * size.w - 7, top: cur.y * size.h - 7, width: 14, height: 14, borderRadius: 7, borderWidth: 2, borderColor: C.warn }} />
        )}
      </Pressable>
      <Text style={{ color: C.dim, fontSize: 13, textAlign: 'center' }}>Тапни по картинке, и на ноуте произойдёт клик в этом месте.</Text>
    </ScrollView>
  );
}
