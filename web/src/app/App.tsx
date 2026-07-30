import type { ReactNode } from 'react';
import { Redirect, Route, Switch } from 'wouter';
import { useAuth } from '../features/auth/AuthContext';
import { InitializePage } from '../features/auth/InitializePage';
import { LoginPage } from '../features/auth/LoginPage';
import { ForgotPasswordPage, ResetPasswordPage } from '../features/auth/RecoveryPages';
import { AppShell } from './AppShell';
import { ChatPage } from '../features/chat/ChatPage';
import { HistoryPage } from '../features/history/HistoryPage';
import { MemoryPage } from '../features/memory/MemoryPage';
import { SettingsPage } from '../features/settings/SettingsPage';
import { ProfilePage, VerifyEmailPage } from '../features/profile/ProfilePage';

export function App() {
  const { loading, instanceState, user } = useAuth();
  if (loading || instanceState === 'loading')
    return (
      <main className="centered" aria-busy="true">
        Načítám bezpečný stav aplikace…
      </main>
    );
  if (instanceState === 'uninitialized') return <InitializePage />;
  return (
    <Switch>
      <Route path="/forgot-password" component={ForgotPasswordPage} />
      <Route path="/reset-password" component={ResetPasswordPage} />
      <Route path="/verify-email" component={VerifyEmailPage} />
      <Route path="/login">{user ? <Redirect to="/chat" replace /> : <LoginPage />}</Route>
      <Route path="/chat">
        <Protected user={user}>
          <ChatPage />
        </Protected>
      </Route>
      <Route path="/history">
        <Protected user={user}>
          <HistoryPage />
        </Protected>
      </Route>
      <Route path="/memory">
        <Protected user={user}>
          <MemoryPage />
        </Protected>
      </Route>
      <Route path="/settings">
        <Protected user={user}>
          <SettingsPage />
        </Protected>
      </Route>
      <Route path="/profile">
        <Protected user={user}>
          <ProfilePage />
        </Protected>
      </Route>
      <Route>
        <Redirect to={user ? '/chat' : '/login'} replace />
      </Route>
    </Switch>
  );
}

function Protected({ user, children }: { user: unknown; children: ReactNode }) {
  return user ? <AppShell>{children}</AppShell> : <Redirect to="/login" replace />;
}
