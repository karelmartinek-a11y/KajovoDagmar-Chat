import { FormEvent, useState } from 'react';
import { api, ApiError } from '../../api/client';
import { Brand } from '../../components/Brand';

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api('/auth/password/forgot', {
        method: 'POST',
        body: JSON.stringify({ username: 'Karmar78' }),
      });
      setSent(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="panel auth-card">
        <Brand />
        <h1>Zapomenuté heslo</h1>
        {sent ? (
          <div className="success" role="status">
            Pokud je bezpečná e-mailová obnova připravena, byly odeslány další pokyny.
          </div>
        ) : (
          <form className="stack" onSubmit={(e) => void submit(e)}>
            <label>
              Uživatelské jméno
              <input value="Karmar78" readOnly />
            </label>
            <button className="primary" disabled={busy}>
              {busy ? 'Zpracovávám…' : 'Odeslat pokyny'}
            </button>
          </form>
        )}
        <a href="/login">Zpět k přihlášení</a>
      </section>
    </main>
  );
}

export function ResetPasswordPage() {
  const token = new URLSearchParams(window.location.search).get('token') ?? '';
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api('/auth/password/reset', {
        method: 'POST',
        body: JSON.stringify({ token, new_password: password, confirmation }),
      });
      setResult('Heslo bylo změněno. Všechny relace byly ukončeny; přihlaste se znovu.');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Obnovu se nepodařilo dokončit.');
    }
  }
  return (
    <main className="auth-page">
      <section className="panel auth-card">
        <Brand />
        <h1>Nastavení nového hesla</h1>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {result ? (
          <div className="success">{result}</div>
        ) : (
          <form className="stack" onSubmit={(e) => void submit(e)}>
            <label>
              Nové heslo
              <input
                type="password"
                minLength={14}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            <label>
              Potvrzení
              <input
                type="password"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                required
              />
            </label>
            <button
              className="primary"
              disabled={!token || password !== confirmation || password.length < 14}
            >
              Změnit heslo
            </button>
          </form>
        )}
        <a href="/login">Přihlášení</a>
      </section>
    </main>
  );
}
