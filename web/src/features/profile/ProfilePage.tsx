import { FormEvent, useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client';
import { Feedback } from '../../components/Feedback';
import { useAuth } from '../auth/AuthContext';
import './profile.css';

type Profile = {
  username: string;
  display_name: string;
  email: string | null;
  pending_email: string | null;
  email_state: string;
  email_verified_at: string | null;
  locale: string;
  timezone: string;
  version: number;
};
type Session = {
  id: string;
  created_at: string;
  last_activity_at: string;
  expires_at: string;
  device_label: string | null;
  network_context: string | null;
  current: boolean;
};

export function ProfilePage() {
  const { refresh } = useAuth();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [email, setEmail] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [passwords, setPasswords] = useState({ current: '', next: '', confirmation: '' });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  async function load() {
    try {
      const [p, s] = await Promise.all([
        api<Profile>('/profile'),
        api<{ items: Session[] }>('/auth/sessions'),
      ]);
      setProfile(p);
      setSessions(s.items);
      setEmail(p.pending_email ?? p.email ?? '');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Profil se nepodařilo načíst.');
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function changeEmail(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const r = await api<{ message: string }>('/profile/email/change', {
        method: 'POST',
        body: JSON.stringify({ email, current_password: emailPassword }),
      });
      setNotice(r.message);
      setEmailPassword('');
      await load();
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : 'Změnu e-mailu se nepodařilo zahájit.',
      );
    }
  }
  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api('/auth/password/change', {
        method: 'POST',
        body: JSON.stringify({
          current_password: passwords.current,
          new_password: passwords.next,
          confirmation: passwords.confirmation,
        }),
      });
      setPasswords({ current: '', next: '', confirmation: '' });
      setNotice('Heslo bylo změněno a všechny ostatní relace byly ukončeny.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Heslo se nepodařilo změnit.');
    }
  }
  async function revoke(session: Session) {
    if (
      session.current ||
      !window.confirm(`Ukončit relaci zařízení „${session.device_label ?? 'Neznámé zařízení'}“?`)
    )
      return;
    await api(`/auth/sessions/${session.id}`, { method: 'DELETE' });
    setNotice('Vybraná relace byla zneplatněna.');
    await load();
  }
  return (
    <section className="stack" aria-labelledby="profile-title">
      <header className="page-header">
        <h1 id="profile-title">Profil</h1>
        <p className="muted">Identita, obnova přístupu a aktivní bezpečné relace.</p>
      </header>
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      <div className="profile-grid">
        <section className="panel stack">
          <h2>Administrátor</h2>
          <dl>
            <dt>Uživatelské jméno</dt>
            <dd>{profile?.username ?? 'Karmar78'}</dd>
            <dt>Jméno</dt>
            <dd>{profile?.display_name}</dd>
            <dt>E-mail</dt>
            <dd>{profile?.email ?? 'Nezadán'}</dd>
            <dt>Stav e-mailu</dt>
            <dd>{emailStateLabel(profile?.email_state)}</dd>
            <dt>Časové pásmo</dt>
            <dd>{profile?.timezone}</dd>
          </dl>
          <form className="stack" onSubmit={(e) => void changeEmail(e)}>
            <h3>Změna kontaktního e-mailu</h3>
            <label>
              Nová adresa
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
            <label>
              Aktuální heslo
              <input
                type="password"
                value={emailPassword}
                onChange={(e) => setEmailPassword(e.target.value)}
                required
              />
            </label>
            <button className="primary">Odeslat ověřovací odkaz</button>
          </form>
        </section>
        <section className="panel stack">
          <h2>Změna hesla</h2>
          <form className="stack" onSubmit={(e) => void changePassword(e)}>
            <label>
              Aktuální heslo
              <input
                type="password"
                autoComplete="current-password"
                value={passwords.current}
                onChange={(e) => setPasswords({ ...passwords, current: e.target.value })}
                required
              />
            </label>
            <label>
              Nové heslo
              <input
                type="password"
                minLength={14}
                maxLength={128}
                autoComplete="new-password"
                value={passwords.next}
                onChange={(e) => setPasswords({ ...passwords, next: e.target.value })}
                required
              />
            </label>
            <label>
              Potvrzení nového hesla
              <input
                type="password"
                autoComplete="new-password"
                value={passwords.confirmation}
                onChange={(e) => setPasswords({ ...passwords, confirmation: e.target.value })}
                required
              />
            </label>
            <button
              className="primary"
              disabled={passwords.next.length < 14 || passwords.next !== passwords.confirmation}
            >
              Změnit heslo
            </button>
          </form>
        </section>
      </div>
      <section className="panel stack">
        <h2>Aktivní relace</h2>
        <p className="muted">Síťový kontext je záměrně zkrácený a neobsahuje úplnou IP adresu.</p>
        <div className="sessions">
          {sessions.map((session) => (
            <article key={session.id}>
              <div>
                <strong>{session.device_label ?? 'Webový prohlížeč'}</strong>
                <small>
                  {session.current ? 'Tato relace' : 'Jiná relace'} ·{' '}
                  {session.network_context ?? 'Síť neurčena'}
                </small>
              </div>
              <span>
                Poslední aktivita {new Date(session.last_activity_at).toLocaleString('cs-CZ')}
              </span>
              {!session.current && (
                <button className="danger" onClick={() => void revoke(session)}>
                  Ukončit relaci
                </button>
              )}
            </article>
          ))}
        </div>
      </section>
    </section>
  );
}
function emailStateLabel(value: string | undefined) {
  return (
    (
      {
        not_set: 'E-mail není zadán',
        pending: 'Čeká na ověření',
        verified: 'Ověřen – obnova může být dostupná',
      } as Record<string, string>
    )[value ?? 'not_set'] ?? value
  );
}

export function VerifyEmailPage() {
  const token = new URLSearchParams(location.search).get('token') ?? '';
  const [message, setMessage] = useState('Ověřuji adresu…');
  useEffect(() => {
    void api<{ email: string }>('/profile/email/verify', {
      method: 'POST',
      body: JSON.stringify({ token }),
    })
      .then((r) => setMessage(`Adresa ${r.email} byla ověřena.`))
      .catch((reason) =>
        setMessage(reason instanceof ApiError ? reason.message : 'Ověření se nepodařilo.'),
      );
  }, [token]);
  return (
    <main className="auth-page">
      <section className="panel auth-card">
        <h1>Ověření e-mailu</h1>
        <p>{message}</p>
        <a href="/profile">Přejít do profilu</a>
      </section>
    </main>
  );
}
