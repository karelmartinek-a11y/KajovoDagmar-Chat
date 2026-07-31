import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { PropsWithChildren } from 'react';
import { api, setCsrfToken } from '../../api/client';
import { endVoiceSession } from '../../audio/voiceSession';

type Profile = { display_name: string; email: string | null; email_state: string };
type User = { id: string; username: string; state: string; profile: Profile };
type InstanceState = 'loading' | 'uninitialized' | 'active';

type AuthContextValue = {
  instanceState: InstanceState;
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
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const state = await api<{ instance_state: 'uninitialized' | 'active' }>('/auth/state');
    setInstanceState(state.instance_state);
    if (state.instance_state === 'active') {
      try {
        setUser(await api<User>('/auth/me'));
      } catch {
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
        body: JSON.stringify({ username: 'Karmar78', password }),
      });
      setCsrfToken(response.csrf_token);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await endVoiceSession();
    await api<void>('/auth/logout', { method: 'POST' });
    setCsrfToken(null);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ instanceState, user, loading, refresh, login, logout }),
    [instanceState, user, loading, refresh, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('AuthProvider není dostupný.');
  return value;
}
