import * as SecureStore from 'expo-secure-store';
import type { Creds } from './protocol';

const KEY = 'dasync.creds';

// Ключ устройства лежит в Keychain (iOS) / Keystore (Android), а не в обычном хранилище.
export async function loadCreds(): Promise<Creds | null> {
  try {
    const v = await SecureStore.getItemAsync(KEY);
    return v ? (JSON.parse(v) as Creds) : null;
  } catch {
    return null;
  }
}
export const saveCreds = (c: Creds) => SecureStore.setItemAsync(KEY, JSON.stringify(c));
export const clearCreds = () => SecureStore.deleteItemAsync(KEY);
