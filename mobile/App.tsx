import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import * as Crypto from 'expo-crypto';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Logo } from './src/components';
import { findLaptop } from './src/discovery';
import { ApiError, Client, Creds, Deps } from './src/protocol';
import FilesScreen from './src/screens/FilesScreen';
import KeysScreen from './src/screens/KeysScreen';
import OverviewScreen from './src/screens/OverviewScreen';
import PadScreen from './src/screens/PadScreen';
import PairScreen from './src/screens/PairScreen';
import PowerScreen from './src/screens/PowerScreen';
import ScreenScreen from './src/screens/ScreenScreen';
import { Session, SessionCtx } from './src/session';
import { clearCreds, loadCreds, saveCreds } from './src/storage';
import { C } from './src/theme';

type Tab = 'pad' | 'screen' | 'keys' | 'files' | 'home' | 'power';
const TABS: { key: Tab; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'pad', label: 'Тачпад', icon: 'finger-print-outline' },
  { key: 'screen', label: 'Экран', icon: 'desktop-outline' },
  { key: 'keys', label: 'Ввод', icon: 'keypad-outline' },
  { key: 'files', label: 'Файлы', icon: 'folder-open-outline' },
  { key: 'home', label: 'Обзор', icon: 'speedometer-outline' },
  { key: 'power', label: 'Питание', icon: 'power-outline' },
];

function Root() {
  const insets = useSafeAreaInsets();
  const deps = useMemo<Deps>(() => ({ fetch: globalThis.fetch.bind(globalThis), rng: (n) => Crypto.getRandomBytes(n) }), []);
  const [boot, setBoot] = useState(true);
  const [client, setClient] = useState<Client | null>(null);
  const [tab, setTab] = useState<Tab>('pad');
  const [status, setStatus] = useState<'ok' | 'offline' | 'paused'>('ok');
  const [toast, setToast] = useState('');
  const [searching, setSearching] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastToast = useRef(0);

  useEffect(() => {
    loadCreds().then((c) => {
      if (c) setClient(new Client(c, deps));
      setBoot(false);
    });
  }, [deps]);

  const notify = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 2600);
  }, []);

  const disconnect = useCallback(async () => {
    await clearCreds();
    setClient(null);
    setStatus('ok');
  }, []);

  const call = useCallback(
    async (body: Record<string, unknown>) => {
      if (!client) return null;
      try {
        const r = await client.call(body);
        setStatus('ok');
        return r;
      } catch (e) {
        if (e instanceof ApiError) {
          if (e.kind === 'network' || e.kind === 'timeout') setStatus('offline');
          else if (e.kind === 'paused') setStatus('paused');
          else if (e.kind === 'auth' || e.kind === 'blocked') { notify(e.message); disconnect(); }
          else if (Date.now() - lastToast.current > 2500) { lastToast.current = Date.now(); notify(e.message); }
        }
        return null;
      }
    },
    [client, notify, disconnect],
  );

  const onPaired = async (c: Creds) => {
    await saveCreds(c);
    setClient(new Client(c, deps));
    notify('Подключено');
  };

  const onDemo = () => setClient(new Client({ base: 'demo', devid: 'demo', k: '' }, deps));

  const search = async () => {
    if (!client) return;
    setSearching(true);
    const found = await findLaptop(client, deps);
    setSearching(false);
    if (found) {
      client.setBase(found);
      await saveCreds(client.creds);
      setStatus('ok');
      notify('Ноутбук найден: ' + found.replace('http://', ''));
    } else {
      notify('Ноутбук не найден. Проверь Wi-Fi и что DaSync запущен.');
    }
  };

  const session: Session | null = useMemo(() => (client ? { call, notify, disconnect, host: client.base, client } : null), [call, notify, disconnect, client]);

  if (boot) return <View style={{ flex: 1, backgroundColor: C.bg, alignItems: 'center', justifyContent: 'center' }}><ActivityIndicator color={C.accent} /></View>;
  if (!client || !session) return <PairScreen deps={deps} onPaired={onPaired} onDemo={onDemo} />;

  return (
    <SessionCtx.Provider value={session}>
      <LinearGradient colors={[C.bg2, C.bg]} style={{ flex: 1, paddingTop: insets.top }}>
        <View style={s.header}>
          <Logo size={30} />
          <Text style={s.brand}>DaSync</Text>
          <View style={[s.dot, { backgroundColor: status === 'ok' ? C.ok : status === 'paused' ? C.warn : C.bad }]} />
          <Text style={s.state}>{client.isDemo ? 'Демо-режим' : status === 'ok' ? 'На связи' : status === 'paused' ? 'Пауза на ноуте' : 'Нет связи'}</Text>
        </View>
        {status === 'offline' && (
          <View style={s.banner}>
            <Text style={{ color: C.ink, flex: 1 }}>Ноутбук не отвечает</Text>
            <Pressable onPress={search} disabled={searching}>
              <Text style={{ color: C.accent, fontWeight: '600' }}>{searching ? 'Ищу…' : 'Найти в сети'}</Text>
            </Pressable>
          </View>
        )}
        <View style={{ flex: 1 }}>
          {tab === 'pad' && <PadScreen />}
          {tab === 'screen' && <ScreenScreen />}
          {tab === 'keys' && <KeysScreen />}
          {tab === 'files' && <FilesScreen />}
          {tab === 'home' && <OverviewScreen />}
          {tab === 'power' && <PowerScreen />}
        </View>
        {!!toast && <View style={[s.toast, { bottom: insets.bottom + 78 }]}><Text style={{ color: C.ink, textAlign: 'center' }}>{toast}</Text></View>}
        <View style={[s.tabs, { paddingBottom: insets.bottom + 6 }]}>
          {TABS.map((t) => (
            <Pressable key={t.key} onPress={() => setTab(t.key)} style={s.tab}>
              <Ionicons name={t.icon} size={22} color={tab === t.key ? C.accent : C.dim} />
              <Text style={{ color: tab === t.key ? C.accent : C.dim, fontSize: 10, marginTop: 2 }}>{t.label}</Text>
            </Pressable>
          ))}
        </View>
      </LinearGradient>
    </SessionCtx.Provider>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <Root />
    </SafeAreaProvider>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingVertical: 10 },
  brand: { color: C.ink, fontWeight: '800', fontSize: 18, flex: 1 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  state: { color: C.dim, fontSize: 13 },
  banner: { flexDirection: 'row', alignItems: 'center', marginHorizontal: 14, marginBottom: 6, padding: 12, borderRadius: 14, backgroundColor: 'rgba(255,122,138,.14)' },
  tabs: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: C.line, backgroundColor: C.bg, paddingTop: 8 },
  tab: { flex: 1, alignItems: 'center' },
  toast: { position: 'absolute', left: 24, right: 24, backgroundColor: '#232b4d', borderRadius: 14, padding: 12 },
});
