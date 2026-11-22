import * as Haptics from 'expo-haptics';
import { useEffect, useRef, useState } from 'react';
import { GestureResponderEvent, PanResponder, StyleSheet, Text, View } from 'react-native';
import { Btn } from '../components';
import { useSession } from '../session';
import { C } from '../theme';

type Touch = { pageX: number; pageY: number };
const centroid = (ts: readonly Touch[]) => ({
  x: ts.reduce((a, t) => a + t.pageX, 0) / Math.max(ts.length, 1),
  y: ts.reduce((a, t) => a + t.pageY, 0) / Math.max(ts.length, 1),
});

export default function PadScreen() {
  const { call } = useSession();
  const acc = useRef({ mx: 0, my: 0, sc: 0, busy: false });
  const st = useRef({ last: { x: 0, y: 0 }, t0: 0, moved: 0, maxT: 0, count: 0 });
  const drag = useRef(false);
  const [dragOn, setDragOn] = useState(false);
  const callRef = useRef(call);
  callRef.current = call;

  // Движения копим и отправляем пачками, чтобы не заваливать сеть.
  useEffect(() => {
    const id = setInterval(async () => {
      const a = acc.current;
      if (a.busy) return;
      const dx = Math.trunc(a.mx), dy = Math.trunc(a.my), n = Math.trunc(a.sc);
      if (!dx && !dy && !n) return;
      a.mx -= dx; a.my -= dy; a.sc -= n;
      a.busy = true;
      try {
        if (dx || dy) await callRef.current({ a: 'move', dx, dy });
        if (n) await callRef.current({ a: 'scroll', n });
      } finally {
        a.busy = false;
      }
    }, 16);
    return () => clearInterval(id);
  }, []);

  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderStart: (e: GestureResponderEvent) => {
        const s = st.current, ts = e.nativeEvent.touches;
        if (ts.length === 1) { s.t0 = Date.now(); s.moved = 0; s.maxT = 0; }
        s.count = ts.length;
        s.maxT = Math.max(s.maxT, ts.length);
        s.last = centroid(ts);
      },
      onPanResponderMove: (e: GestureResponderEvent) => {
        const s = st.current, ts = e.nativeEvent.touches;
        const c = centroid(ts);
        if (ts.length !== s.count) { s.count = ts.length; s.last = c; return; }
        const dx = c.x - s.last.x, dy = c.y - s.last.y;
        s.last = c;
        s.moved += Math.abs(dx) + Math.abs(dy);
        if (ts.length === 1) {
          const g = 1.3 + Math.min(Math.hypot(dx, dy), 40) / 25;
          acc.current.mx += dx * g;
          acc.current.my += dy * g;
        } else {
          acc.current.sc += dy / 12;
        }
      },
      onPanResponderRelease: () => {
        const s = st.current;
        if (s.moved < 8 && Date.now() - s.t0 < 250 && !drag.current) {
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
          callRef.current({ a: 'click', b: s.maxT >= 2 ? 'right' : 'left' });
        }
      },
    }),
  ).current;

  const toggleDrag = async () => {
    const next = !drag.current;
    drag.current = next;
    setDragOn(next);
    Haptics.selectionAsync();
    await call({ a: next ? 'down' : 'up' });
  };

  return (
    <View style={{ flex: 1, padding: 14, gap: 12 }}>
      <View style={s.pad} {...pan.panHandlers}>
        <Text style={s.hint}>Один палец: курсор · касание: клик{'\n'}Два пальца: прокрутка · касание: правый клик</Text>
      </View>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Btn title="Левая" onPress={() => call({ a: 'click', b: 'left' })} style={{ flex: 1 }} />
        <Btn title="Тащить" active={dragOn} onPress={toggleDrag} style={{ flex: 1 }} />
        <Btn title="Правая" onPress={() => call({ a: 'click', b: 'right' })} style={{ flex: 1 }} />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  pad: { flex: 1, borderRadius: 26, backgroundColor: C.card, borderWidth: 1, borderColor: C.line, justifyContent: 'flex-end', alignItems: 'center', padding: 18 },
  hint: { color: '#4a5380', textAlign: 'center', lineHeight: 20 },
});
