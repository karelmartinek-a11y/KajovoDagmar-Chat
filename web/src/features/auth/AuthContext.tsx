import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { PropsWithChildren } from 'react';
import { api, setCsrfToken } from '../../api/client';
import { endVoiceSession } from '../../audio/voiceSession';

type Profile = { display_name: string; email: string | null; email_state: string };
type User = { id: string; username: string; state: string; profile: Profile };
type InstanceState = 'loading' | 'uninitialized' | 'active';

type AuthContextValue = {
  instanceState: InstanceState;
  username: string;
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [instanceState, setInstanceState] = useState<InstanceState>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [username, setUsername] = useState('Karmar78');
  const [loading, setLoading] = useState(true);
  const refreshSequence = useRef(0);

  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    setLoading(true);
    const state = await api<{
      instance_state: 'uninitialized' | 'active';
      username: string;
    }>('/auth/state');
    if (sequence !== refreshSequence.current) return;
    setUsername(state.username);
    setInstanceState(state.instance_state);
    if (state.instance_state === 'active') {
      try {
        const current = await api<User>('/auth/me');
        if (sequence !== refreshSequence.current) return;
        setUsername(current.username);
        setUser(current);
      } catch {
        if (sequence !== refreshSequence.current) return;
        setUser(null);
      }
    } else {
      setUser(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (password: string) => {
      const response = await api<{ csrf_token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      setCsrfToken(response.csrf_token);
      await refresh();
    },
    [refresh, username],
  );

  const logout = useCallback(async () => {
    await endVoiceSession();
    await api<void>('/auth/logout', { method: 'POST' });
    setCsrfToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ instanceState, username, user, loading, refresh, login, logout }),
    [instanceState, username, user, loading, refresh, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('AuthProvider není dostupný.');
  return value;
}
