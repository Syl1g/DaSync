import { createContext, useContext } from 'react';
import type { Client } from './protocol';

export type Session = {
  call: (body: Record<string, unknown>) => Promise<any | null>;
  notify: (msg: string) => void;
  disconnect: () => void;
  host: string;
  client: Client;
};

export const SessionCtx = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(SessionCtx);
  if (!s) throw new Error('Нет сессии');
  return s;
}
