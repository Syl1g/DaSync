import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import * as Haptics from 'expo-haptics';
import * as ImagePicker from 'expo-image-picker';
import * as Sharing from 'expo-sharing';
import { useCallback, useEffect, useState } from 'react';
import { Alert, RefreshControl, ScrollView, Text, View } from 'react-native';
import { Btn, Card } from '../components';
import { fsz } from '../format';
import { useSession } from '../session';
import { C } from '../theme';

type Remote = { name: string; size: number; ts: number };
type Pick = { uri: string; name: string };

export default function FilesScreen() {
  const { call, notify, client } = useSession();
  const [files, setFiles] = useState<Remote[]>([]);
  const [dir, setDir] = useState('');
  const [busy, setBusy] = useState('');
  const [pct, setPct] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    const r = await call({ a: 'files' });
    if (r?.files) { setFiles(r.files); setDir(r.dir ?? ''); }
  }, [call]);

  useEffect(() => { load(); }, [load]);

  const uploadOne = async (p: Pick): Promise<boolean> => {
    const info = await FileSystem.getInfoAsync(p.uri);
    if (!info.exists) { notify(`Не удалось прочитать ${p.name}`); return false; }
    // подпись считается до отправки: размер входит в неё, поэтому его нужно знать точно
    const { url, headers } = client.signUpload(p.name, info.size);
    const task = FileSystem.createUploadTask(
      url,
      p.uri,
      { httpMethod: 'POST', uploadType: FileSystem.FileSystemUploadType.BINARY_CONTENT, headers },
      (e) => setPct(e.totalBytesSent / Math.max(e.totalBytesExpectedToSend, 1)),
    );
    const res = await task.uploadAsync();
    if (res?.status === 200) return true;
    if (res?.status === 403) notify('Нет разрешения на файлы. Включи в DaSync на ноуте → Устройства.');
    else if (res?.status === 401) notify('Ноутбук не принял подпись. Подключи устройство заново.');
    else notify(`Ошибка загрузки (${res?.status ?? 'нет связи'})`);
    return false;
  };

  const uploadAll = async (picks: Pick[]) => {
    let ok = 0;
    for (let i = 0; i < picks.length; i++) {
      setBusy(`${i + 1} из ${picks.length}: ${picks[i].name}`);
      setPct(0);
      try {
        if (await uploadOne(picks[i])) ok++; else break;
      } catch {
        notify('Нет связи с ноутбуком.');
        break;
      }
    }
    setBusy('');
    if (ok) { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); notify(`Отправлено файлов: ${ok}`); }
    load();
  };

  const pickFiles = async () => {
    const r = await DocumentPicker.getDocumentAsync({ multiple: true, copyToCacheDirectory: true });
    if (!r.canceled) uploadAll(r.assets.map((a) => ({ uri: a.uri, name: a.name })));
  };

  const pickMedia = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images', 'videos'], allowsMultipleSelection: true, quality: 1 });
    if (!r.canceled) uploadAll(r.assets.map((a) => ({ uri: a.uri, name: a.fileName ?? a.uri.split('/').pop() ?? 'file' })));
  };

  const download = async (name: string) => {
    setBusy(`Скачиваю ${name}`);
    setPct(0);
    try {
      const local = (FileSystem.cacheDirectory ?? '') + name.replace(/[\\/:*?"<>|]/g, '_');
      const r = await FileSystem.downloadAsync(client.signedFileUrl(name), local);
      if (r.status !== 200) notify(r.status === 403 ? 'Нет разрешения на файлы.' : `Ошибка скачивания (${r.status})`);
      else if (await Sharing.isAvailableAsync()) await Sharing.shareAsync(r.uri);
      else notify('Файл сохранён во временную папку приложения.');
    } catch {
      notify('Не удалось скачать файл.');
    }
    setBusy('');
  };

  const remove = (name: string) =>
    Alert.alert('Удалить файл?', `«${name}» будет удалён с ноутбука.`, [
      { text: 'Отмена', style: 'cancel' },
      { text: 'Удалить', style: 'destructive', onPress: async () => { if (await call({ a: 'file_del', name })) load(); } },
    ]);

  return (
    <ScrollView
      contentContainerStyle={{ padding: 14, gap: 12 }}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={C.accent} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
    >
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <Btn title="Файл с телефона" kind="primary" onPress={pickFiles} disabled={!!busy} style={{ flex: 1 }} />
        <Btn title="Фото и видео" onPress={pickMedia} disabled={!!busy} style={{ flex: 1 }} />
      </View>

      {!!busy && (
        <Card>
          <Text style={{ color: C.ink }} numberOfLines={1}>{busy}</Text>
          <View style={{ height: 8, borderRadius: 4, backgroundColor: C.line, marginTop: 10, overflow: 'hidden' }}>
            <View style={{ width: `${Math.round(pct * 100)}%`, height: '100%', backgroundColor: C.accent }} />
          </View>
        </Card>
      )}

      <Card>
        <Text style={{ color: C.dim, fontSize: 13, marginBottom: 6 }}>Файлы на ноутбуке</Text>
        {files.length === 0 && <Text style={{ color: C.dim, textAlign: 'center', paddingVertical: 18 }}>Папка пуста. Отправь сюда файл с телефона.</Text>}
        {files.map((f, i) => (
          <View key={f.name} style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10, borderTopWidth: i ? 1 : 0, borderTopColor: C.line }}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: C.ink, fontWeight: '600' }} numberOfLines={1}>{f.name}</Text>
              <Text style={{ color: C.dim, fontSize: 12 }}>
                {fsz(f.size)} · {new Date(f.ts * 1000).toLocaleString('ru', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
              </Text>
            </View>
            <Btn title="Скачать" onPress={() => download(f.name)} disabled={!!busy} style={{ minHeight: 38, paddingHorizontal: 12 }} />
            <Btn title="✕" kind="danger" onPress={() => remove(f.name)} style={{ minHeight: 38, minWidth: 40, paddingHorizontal: 0 }} />
          </View>
        ))}
      </Card>

      <Btn title="Открыть папку на ноутбуке" onPress={() => call({ a: 'open_folder' })} />
      {!!dir && <Text style={{ color: C.dim, fontSize: 12, textAlign: 'center' }}>{dir}</Text>}
    </ScrollView>
  );
}
