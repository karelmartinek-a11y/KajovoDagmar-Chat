import { FormEvent, useState } from 'react';
import { api, ApiError } from '../../api/client';
import { Brand } from '../../components/Brand';
import { useAuth } from './AuthContext';

export function InitializePage() {
  const { refresh } = useAuth();
  const [form, setForm] = useState({
    secret: '',
    password: '',
    confirmation: '',
    displayName: 'Karel',
    email: '',
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordChecks = [
    { text: '14 až 128 znaků', pass: form.password.length >= 14 && form.password.length <= 128 },
    { text: 'Není shodné s Karmar78', pass: form.password.toLocaleLowerCase() !== 'karmar78' },
    {
      text: 'Potvrzení se shoduje',
      pass: form.password.length > 0 && form.password === form.confirmation,
    },
  ];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api('/auth/initialize', {
        method: 'POST',
        body: JSON.stringify({
          username: 'Karmar78',
          initialization_secret: form.secret,
          password: form.password,
          password_confirmation: form.confirmation,
          display_name: form.displayName,
          email: form.email || null,
        }),
      });
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : 'Inicializaci se nepodařilo dokončit.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="panel auth-card" aria-labelledby="init-title">
        <Brand />
        <h1 id="init-title">Bezpečné první spuštění</h1>
        <p className="muted">
          Jednorázově nastavte administrátorský účet. Inicializační tajemství po úspěchu přestane
          platit.
        </p>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <form className="stack" onSubmit={(event) => void submit(event)}>
          <label>
            Uživatelské jméno
            <input value="Karmar78" readOnly />
          </label>
          <label>
            Inicializační tajemství
            <input
              type="password"
              value={form.secret}
              onChange={(e) => setForm({ ...form, secret: e.target.value })}
              required
            />
          </label>
          <label>
            Jméno pro zobrazení
            <input
              value={form.displayName}
              onChange={(e) => setForm({ ...form, displayName: e.target.value })}
              required
            />
          </label>
          <label>
            Kontaktní e-mail
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </label>
          <label>
            První heslo
            <input
              type="password"
              autoComplete="new-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              required
            />
          </label>
          <label>
            Potvrzení hesla
            <input
              type="password"
              autoComplete="new-password"
              value={form.confirmation}
              onChange={(e) => setForm({ ...form, confirmation: e.target.value })}
              required
            />
          </label>
          <ul className="password-checks">
            {passwordChecks.map((item) => (
              <li key={item.text} className={item.pass ? 'pass' : ''}>
                {item.pass ? 'Splněno: ' : 'Požadavek: '}
                {item.text}
              </li>
            ))}
          </ul>
          <button className="primary" disabled={busy || passwordChecks.some((item) => !item.pass)}>
            {busy ? 'Dokončuji inicializaci…' : 'Aktivovat účet'}
          </button>
        </form>
      </section>
    </main>
  );
}
