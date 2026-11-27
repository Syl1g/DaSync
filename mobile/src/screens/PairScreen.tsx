import { CameraView, useCameraPermissions } from 'expo-camera';
import { LinearGradient } from 'expo-linear-gradient';
import { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Btn, Logo } from '../components';
import { ApiError, Creds, Deps, PairPhase, pair, parsePairLink } from '../protocol';
import { C } from '../theme';

export default function PairScreen({ deps, onPaired, onDemo }: { deps: Deps; onPaired: (c: Creds) => void; onDemo: () => void }) {
  const insets = useSafeAreaInsets();
  const [perm, askPerm] = useCameraPermissions();
  const [phase, setPhase] = useState<'scan' | PairPhase | 'error'>('scan');
  const [msg, setMsg] = useState('');
  const [link, setLink] = useState('');
  const busy = useRef(false);

  const run = async (text: string, manual = false) => {
    if (busy.current) return;
    const p = parsePairLink(text);
    if (!p) {
      if (manual) { setPhase('error'); setMsg('Это не похоже на ссылку подключения DaSync. Нажми «Копировать ссылку» под QR на ноутбуке.'); }
      return;
    }
    busy.current = true;
    setMsg('');
    try {
      const creds = await pair(p.base, p.secret, deps, setPhase);
      onPaired(creds);
    } catch (e) {
      setPhase('error');
      setMsg(e instanceof ApiError ? e.message : 'Не удалось подключиться.');
      busy.current = false;
    }
  };

  const working = phase === 'checking' || phase === 'waiting';

  return (
    <LinearGradient colors={['#141b45', C.bg]} style={{ flex: 1 }}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: 24, paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24, alignItems: 'center' }} keyboardShouldPersistTaps="handled">
          <Logo size={72} />
          <Text style={s.title}>DaSync</Text>
          <Text style={s.sub}>Ноутбук в твоём кармане</Text>

          <View style={s.camBox}>
            {working ? (
              <View style={s.center}>
                <ActivityIndicator color={C.accent} size="large" />
                <Text style={s.state}>{phase === 'checking' ? 'Проверяю код…' : 'Подтверди на ноутбуке'}</Text>
                {phase === 'waiting' && <Text style={s.hint}>В окне DaSync на ноутбуке нажми «Разрешить».</Text>}
              </View>
            ) : perm?.granted ? (
              <>
                <CameraView
                  style={StyleSheet.absoluteFill}
                  facing="back"
                  barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
                  onBarcodeScanned={({ data }) => run(data)}
                />
                <View pointerEvents="none" style={s.frame} />
              </>
            ) : (
              <View style={s.center}>
                <Text style={s.state}>Нужен доступ к камере</Text>
                <Text style={s.hint}>Камера нужна только чтобы отсканировать QR на ноутбуке.</Text>
                <Btn title="Разрешить камеру" kind="primary" onPress={askPerm} style={{ marginTop: 14 }} />
              </View>
            )}
          </View>

          {phase === 'error' && <Text style={s.error}>{msg}</Text>}
          {!working && <Text style={s.hint}>Открой DaSync на ноутбуке и наведи камеру на QR на главной.</Text>}

          {!working && (
            <View style={{ width: '100%', marginTop: 22 }}>
              <Text style={[s.hint, { textAlign: 'left', marginBottom: 8 }]}>Или вставь ссылку подключения:</Text>
              <TextInput
                value={link}
                onChangeText={(t) => { setLink(t); if (parsePairLink(t)) run(t, true); }}
                placeholder="http://192.168.…/#p=…"
                placeholderTextColor={C.dim}
                autoCapitalize="none"
                autoCorrect={false}
                style={s.input}
              />
              <Btn title="Подключить" onPress={() => run(link, true)} style={{ marginTop: 10 }} />
              <Btn title="Посмотреть в демо-режиме" onPress={onDemo} style={{ marginTop: 10, borderColor: 'transparent', backgroundColor: 'transparent' }} />
              <Text style={[s.hint, { marginTop: 2 }]}>Демо покажет все экраны без ноутбука.</Text>
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </LinearGradient>
  );
}

const s = StyleSheet.create({
  title: { color: C.ink, fontSize: 30, fontWeight: '800', marginTop: 14, letterSpacing: 0.5 },
  sub: { color: C.dim, marginTop: 4, marginBottom: 22 },
  camBox: { width: '100%', aspectRatio: 1, maxWidth: 360, borderRadius: 28, overflow: 'hidden', backgroundColor: '#0e1430', borderWidth: 1, borderColor: C.line },
  frame: { position: 'absolute', left: '14%', right: '14%', top: '14%', bottom: '14%', borderRadius: 24, borderWidth: 2, borderColor: C.accent, opacity: 0.8 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  state: { color: C.ink, fontSize: 18, fontWeight: '600', marginTop: 16, textAlign: 'center' },
  hint: { color: C.dim, fontSize: 13, textAlign: 'center', marginTop: 12, lineHeight: 19 },
  error: { color: C.bad, textAlign: 'center', marginTop: 16, lineHeight: 20 },
  input: { backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 14, color: C.ink, paddingHorizontal: 14, paddingVertical: 13, fontSize: 15 },
});
