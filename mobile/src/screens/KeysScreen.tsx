import * as Haptics from 'expo-haptics';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Btn } from '../components';
import { useSession } from '../session';
import { C } from '../theme';

const KEYS: [string, string][] = [
  ['Esc', 'escape'], ['Tab', 'tab'], ['⌫', 'backspace'], ['Enter', 'enter'],
  ['←', 'left'], ['↑', 'up'], ['↓', 'down'], ['→', 'right'],
  ['Пробел', 'space'], ['Del', 'delete'], ['Home', 'home'], ['End', 'end'],
];
const MEDIA: [string, string][] = [
  ['Тише', 'voldown'], ['Mute', 'mute'], ['Громче', 'volup'],
  ['⏮', 'prev'], ['⏯', 'playpause'], ['⏭', 'next'],
];
const COMBOS: [string, string][] = [
  ['Рабочий стол', 'desktop'], ['Alt+Tab', 'switch'], ['Закрыть окно', 'close'],
  ['Скриншот', 'shot'], ['Копировать', 'copy'], ['Вставить', 'paste'],
];

function Grid({ items, cols, onPress }: { items: [string, string][]; cols: number; onPress: (v: string) => void }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {items.map(([label, v]) => (
        <Btn key={label} title={label} onPress={() => onPress(v)} style={{ width: `${100 / cols - 2.2}%`, minHeight: 48, paddingHorizontal: 4 }} />
      ))}
    </View>
  );
}

export default function KeysScreen() {
  const { call, notify } = useSession();
  const [text, setText] = useState('');

  const send = async (enter: boolean) => {
    if (!text) return;
    const r = await call({ a: 'text', t: text });
    if (!r) return;
    if (r.error) { notify(r.error); return; }
    if (enter) await call({ a: 'key', k: 'enter' });
    setText('');
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    notify('Отправлено');
  };
  const key = (k: string) => { Haptics.selectionAsync(); call({ a: 'key', k }); };

  return (
    <ScrollView contentContainerStyle={{ padding: 14, gap: 12 }} keyboardShouldPersistTaps="handled">
      <TextInput
        value={text}
        onChangeText={setText}
        multiline
        placeholder="Текст вставится там, где курсор на ноуте"
        placeholderTextColor={C.dim}
        style={s.input}
      />
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Btn title="Вставить" onPress={() => send(false)} style={{ flex: 1 }} />
        <Btn title="Вставить + Enter" onPress={() => send(true)} style={{ flex: 1 }} />
      </View>
      <Grid items={KEYS} cols={4} onPress={key} />
      <Text style={s.h}>Звук и плеер</Text>
      <Grid items={MEDIA} cols={3} onPress={(m) => call({ a: 'media', m })} />
      <Text style={s.h}>Горячие клавиши</Text>
      <Grid items={COMBOS} cols={3} onPress={(id) => call({ a: 'combo', id })} />
      <Text style={s.h}>Буфер обмена</Text>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Btn
          title="Взять с ноута"
          onPress={async () => { const r = await call({ a: 'clip_get' }); if (r) { setText(r.t ?? ''); notify('Буфер ноута получен'); } }}
          style={{ flex: 1 }}
        />
        <Btn
          title="Отправить на ноут"
          onPress={async () => { if (text && (await call({ a: 'clip_set', t: text }))) notify('Отправлено в буфер ноута'); }}
          style={{ flex: 1 }}
        />
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  input: { minHeight: 100, backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 16, color: C.ink, padding: 14, fontSize: 16, textAlignVertical: 'top' },
  h: { color: C.dim, fontSize: 13, marginTop: 6 },
});
