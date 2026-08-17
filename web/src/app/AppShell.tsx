import type { ReactNode } from 'react';
import { Link, useLocation } from 'wouter';
import { Brand } from '../components/Brand';
import { useAuth } from '../features/auth/AuthContext';
import { ServiceAccessNoticeModal } from '../features/auth/ServiceAccessNoticeModal';
import { cs } from '../i18n/cs';
import './shell.css';

const links = [
  ['/chat', cs.nav.chat, 'chat'],
  ['/history', cs.nav.history, 'history'],
  ['/memory', cs.nav.memory, 'memory'],
  ['/settings', cs.nav.settings, 'settings'],
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout, refresh } = useAuth();
  const [location] = useLocation();
  return (
    <>
      {user?.username === 'Karmar78' && user.service_access_notice && (
        <ServiceAccessNoticeModal
          notice={user.service_access_notice}
          onAcknowledged={() => void refresh()}
        />
      )}
      <div className="app-shell">
        <aside className="sidebar">
          <Brand />
          <nav aria-label="Hlavní navigace">
            {links.map(([to, label, icon]) => (
              <Link key={to} href={to} className={location === to ? 'active' : ''}>
                <span aria-hidden="true" className={`nav-icon ${icon}`} />
                {label}
              </Link>
            ))}
          </nav>
          <div className="account-area">
            <Link href="/profile" className={location === '/profile' ? 'active' : ''}>
              <span>{user?.profile.display_name}</span>
              <small>{cs.nav.profile}</small>
            </Link>
            <button onClick={() => void logout()}>Odhlásit se</button>
          </div>
        </aside>
        <div className="mobile-header">
          <Brand />
          <details>
            <summary>Navigace</summary>
            <nav>
              {links.map(([to, label]) => (
                <Link key={to} href={to}>
                  {label}
                </Link>
              ))}
              <Link href="/profile">Profil</Link>
            </nav>
          </details>
        </div>
        <main className="content">{children}</main>
      </div>
    </>
  );
}
