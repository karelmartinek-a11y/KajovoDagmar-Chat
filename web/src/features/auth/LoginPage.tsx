import { FormEvent, useState } from 'react';
import { ApiError } from '../../api/client';
import { useAuth } from './AuthContext';
import { Brand } from '../../components/Brand';

export function LoginPage() {
  const { login, username } = useAuth();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(password);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Přihlášení se nepodařilo dokončit.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="panel auth-card" aria-labelledby="login-title">
        <Brand />
        <h1 id="login-title">Přihlášení</h1>
        <p className="muted">Soukromý přístup pro administrátora {username}.</p>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <form className="stack" onSubmit={(event) => void submit(event)}>
          <label>
            Uživatelské jméno
            <input value={username} readOnly autoComplete="username" />
          </label>
          <label>
            Heslo
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? 'Ověřuji přístup…' : 'Přihlásit se'}
          </button>
        </form>
        <a href="/forgot-password">Zapomenuté heslo</a>
      </section>
    </main>
  );
}
