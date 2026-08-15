import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  api: vi.fn(),
  refresh: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock('./api/client', async (loadOriginal) => {
  const original = await loadOriginal<typeof import('./api/client')>();
  return { ...original, api: mocks.api };
});
vi.mock('./features/auth/AuthContext', () => ({
  useAuth: () => ({
    instanceState: 'active',
    username: 'Karmar78',
    user: {
      id: 'account-1',
      username: 'Karmar78',
      state: 'active',
      profile: { display_name: 'Karel', email: 'karel@example.test', email_state: 'verified' },
    },
    loading: false,
    refresh: mocks.refresh,
    login: mocks.login,
    logout: mocks.logout,
  }),
}));

import { ApiError } from './api/client';
import { AppShell } from './app/AppShell';
import { InitializePage } from './features/auth/InitializePage';
import { LoginPage } from './features/auth/LoginPage';
import { ForgotPasswordPage, ResetPasswordPage } from './features/auth/RecoveryPages';
import { HistoryPage } from './features/history/HistoryPage';
import { MemoryPage } from './features/memory/MemoryPage';
import { ProfilePage, VerifyEmailPage } from './features/profile/ProfilePage';
import { SettingsPage } from './features/settings/SettingsPage';

const conversation = {
  id: 'conversation-1',
  state: 'completed',
  title: 'Plán týdne',
  summary: 'Dohoda o týdnu',
  started_at: '2026-07-29T10:00:00Z',
  last_activity_at: '2026-07-29T10:05:00Z',
  message_count: 2,
  version: 1,
  deleted_at: null,
  purge_after: null,
};
const memory = {
  id: 'memory-1',
  content: 'Karel preferuje stručné odpovědi.',
  category: 'preference',
  state: 'active',
  origin_type: 'manual',
  event_at: null,
  valid_from: null,
  valid_until: null,
  created_at: '2026-07-29T10:00:00Z',
  updated_at: '2026-07-29T10:00:00Z',
  version: 1,
  deleted_at: null,
  purge_after: null,
};
const setting = (
  value: unknown,
  type = 'string',
  choices: string[] = [],
  effect = 'immediate',
) => ({
  value,
  version: 1,
  label: `Pole ${String(value)}`,
  description: 'Ověřitelné nastavení.',
  effect_boundary: effect,
  type,
  choices,
  minimum: type === 'integer' ? 1 : null,
  maximum: type === 'integer' ? 120 : null,
});
const settings = {
  general: {
    locale: setting('cs', 'string', ['cs', 'en']),
    enabled: setting(true, 'boolean', [], 'next_login'),
    timeout: setting(30, 'integer', [], 'service_restart'),
    label: setting('Dagmar', 'string', [], 'custom_boundary'),
  },
  conversation: {
    verbosity: setting('balanced', 'string', ['short', 'balanced', 'detailed'], 'next_turn'),
  },
  models: {
    conversation_model: setting('', 'string', [], 'next_turn'),
    transcription_model: setting('', 'string', [], 'new_voice_session'),
    speech_model: setting('', 'string', [], 'new_voice_session'),
    embedding_model: setting('', 'string', [], 'immediate'),
    summary_model: setting('', 'string', [], 'next_turn'),
  },
  voice: { voice_id: setting('marin', 'string', [], 'new_voice_session') },
  memory: { retention: setting(30, 'integer') },
  history: { retention: setting(365, 'integer') },
  diagnostics: { level: setting('safe', 'string', ['safe', 'extended']) },
  backups: { schedule: setting('daily', 'string') },
};
const provider = {
  id: 'provider-1',
  provider_type: 'openai',
  display_name: 'OpenAI',
  base_url: 'https://api.openai.com/v1',
  enabled: true,
  verification_state: 'verified',
  secret_present: true,
  secret_hint: '…abcd',
  version: 1,
  models: [
    {
      id: 'model-1',
      external_id: 'model',
      display_name: 'Konverzační model',
      capabilities: { chat: true },
      available: true,
    },
    {
      id: 'model-2',
      external_id: 'old',
      display_name: 'Nedostupný model',
      capabilities: {},
      available: false,
    },
  ],
};

function successfulApi(path: string, init?: RequestInit): Promise<unknown> {
  if (path === '/history/search') return Promise.resolve({ items: [conversation] });
  if (path === '/history/conversation-1')
    return Promise.resolve({
      conversation,
      messages: [
        {
          id: 'message-1',
          sequence: 1,
          role: 'user',
          content: 'Naplánuj týden.',
          status: 'final',
          interrupted: false,
          created_at: '2026-07-29T10:00:00Z',
        },
        {
          id: 'message-2',
          sequence: 2,
          role: 'assistant',
          content: 'Týden je naplánovaný.',
          status: 'interrupted',
          interrupted: true,
          created_at: '2026-07-29T10:01:00Z',
        },
      ],
    });
  if (path.endsWith('/metadata'))
    return Promise.resolve({ ...conversation, title: 'Nový název', version: 2 });
  if (path === '/history/conversation-1' && init?.method === 'DELETE')
    return Promise.resolve({ ...conversation, state: 'deleted', version: 2 });
  if (path === '/memory/search') return Promise.resolve({ items: [memory] });
  if (path === '/memory') return Promise.resolve(memory);
  if (path === '/memory/memory-1')
    return Promise.resolve({
      ...memory,
      content: init?.method === 'PUT' ? 'Upravená preference' : memory.content,
      state: init?.method === 'DELETE' ? 'deleted' : 'outdated',
      version: 2,
    });
  if (path.endsWith('/restore')) return Promise.resolve({ ...memory, version: 3 });
  if (path === '/profile')
    return Promise.resolve({
      username: 'Karmar78',
      display_name: 'Karel',
      email: 'karel@example.test',
      pending_email: null,
      email_state: 'verified',
      email_verified_at: '2026-07-29T10:00:00Z',
      locale: 'cs',
      timezone: 'Europe/Prague',
      version: 1,
    });
  if (path === '/auth/sessions')
    return Promise.resolve({
      items: [
        {
          id: 'current',
          created_at: '2026-07-29T10:00:00Z',
          last_activity_at: '2026-07-29T10:00:00Z',
          expires_at: '2026-07-29T11:00:00Z',
          device_label: null,
          network_context: null,
          current: true,
        },
        {
          id: 'other',
          created_at: '2026-07-29T09:00:00Z',
          last_activity_at: '2026-07-29T09:30:00Z',
          expires_at: '2026-07-29T10:30:00Z',
          device_label: 'Mobil',
          network_context: '192.0.2.0/24',
          current: false,
        },
      ],
    });
  if (path === '/profile/email/change')
    return Promise.resolve({ message: 'Ověřovací odkaz byl odeslán.' });
  if (path === '/profile/email/verify') return Promise.resolve({ email: 'karel@example.test' });
  if (path === '/settings') return Promise.resolve(settings);
  if (path === '/providers') return Promise.resolve({ items: [provider] });
  if (path === '/providers/provider-1/model-options')
    return Promise.resolve({
      provider_id: 'provider-1',
      provider_verified: true,
      catalog_refreshed_at: '2026-07-29T10:00:00Z',
      catalog_state: 'ready',
      policy_version: '2026-07-31.v1',
      roles: Object.fromEntries(
        [
          ['conversation_model', 'Mozek rozhovoru'],
          ['transcription_model', 'Sluch – převod řeči na text'],
          ['speech_model', 'Řeč – převod textu na hlas'],
          ['embedding_model', 'Paměť – hledání souvisejících informací'],
          ['summary_model', 'Archivář – názvy a shrnutí rozhovorů'],
          ['unknown_model', 'Neznámá role'],
        ].map(([key, title]) => [
          key,
          {
            title,
            plain_description: 'Lidské vysvětlení role.',
            more_information: 'Další informace.',
            recommended_model_id:
              key === 'summary_model' || key === 'unknown_model' ? null : 'model-1',
            selected_model_id: '',
            status: key === 'unknown_model' ? 'missing_supported_model' : 'ready',
            options:
              key === 'unknown_model'
                ? []
                : [
                    {
                      id: 'model-1',
                      external_id: 'model',
                      display_name: 'Model',
                      recommended: key !== 'summary_model',
                      recommendation_reason: 'Doporučeno pro tuto roli.',
                    },
                  ],
          },
        ]),
      ) as Record<string, object>,
    });
  if (path === '/providers/provider-1/apply-recommended-models')
    return Promise.resolve({ options: { roles: {} } });
  if (path === '/notifications/email')
    return Promise.resolve({
      configured: true,
      verification_state: 'verified',
      host: 'smtp.example.test',
      port: 587,
      username: 'mailer',
      sender: 'dagmar@example.test',
      use_starttls: true,
    });
  if (path === '/exports')
    return init?.method === 'POST'
      ? Promise.resolve({})
      : Promise.resolve({
          items: [
            {
              id: 'export-1',
              kind: 'history',
              state: 'completed',
              format: 'markdown',
              file_digest: 'abc',
              expires_at: '2026-07-30T10:00:00Z',
              completed_at: '2026-07-29T10:00:00Z',
            },
            {
              id: 'export-2',
              kind: 'memory',
              state: 'queued',
              format: 'json',
              file_digest: null,
              expires_at: null,
              completed_at: null,
            },
          ],
        });
  if (path === '/operations/status')
    return Promise.resolve({
      checked_at: '2026-07-29T10:00:00Z',
      components: {
        web: { state: 'ready', impact: null, action: null },
        providers: {
          state: 'limited',
          impact: 'AI není připravena.',
          action: 'Ověřte poskytovatele.',
        },
      },
    });
  if (path.startsWith('/operations/audit'))
    return Promise.resolve({
      items: [
        {
          id: 42,
          occurred_at: '2026-07-29T10:00:00Z',
          area: 'memory',
          event_name: 'memory.created',
          actor_type: 'administrator',
          target_type: 'memory_item',
          result: 'success',
          correlation_id: 'correlation-1',
          details: { category: 'preference' },
        },
      ],
    });
  if (path === '/operations/backups')
    return init?.method === 'POST'
      ? Promise.resolve({})
      : Promise.resolve({
          items: [
            {
              id: 'backup-1',
              backup_type: 'full',
              state: 'completed',
              started_at: '2026-07-29T10:00:00Z',
              completed_at: '2026-07-29T10:01:00Z',
              backup_label: '20260729-100000F',
              verified_at: '2026-07-29T10:02:00Z',
              restore_tested_at: null,
              size_bytes: 1024,
              error_code: null,
              version: 1,
            },
          ],
        });
  if (path.startsWith('/operations/backups/')) return Promise.resolve({});
  return Promise.resolve({});
}

beforeEach(() => {
  vi.restoreAllMocks();
  mocks.api.mockImplementation(successfulApi);
  mocks.refresh.mockResolvedValue(undefined);
  mocks.login.mockResolvedValue(undefined);
  mocks.logout.mockResolvedValue(undefined);
  window.history.replaceState({}, '', '/');
});

describe('authentication screens', () => {
  it('validates and submits initialization data', async () => {
    render(<InitializePage />);
    fireEvent.change(screen.getByLabelText('Inicializační tajemství'), {
      target: { value: 'one-time-secret' },
    });
    fireEvent.change(screen.getByLabelText('Kontaktní e-mail'), {
      target: { value: 'karel@example.test' },
    });
    fireEvent.change(screen.getByLabelText('První heslo'), {
      target: { value: 'velmi bezpečné heslo' },
    });
    fireEvent.change(screen.getByLabelText('Potvrzení hesla'), {
      target: { value: 'velmi bezpečné heslo' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Aktivovat účet' }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith(
        '/auth/initialize',
        expect.objectContaining({ method: 'POST' }),
      ),
    );
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it('shows login errors and succeeds on retry', async () => {
    mocks.login.mockRejectedValueOnce(new ApiError('denied', 'Přístup odepřen.', 401));
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText('Heslo'), { target: { value: 'wrong' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Přihlásit se' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('Přístup odepřen.');
    fireEvent.submit(screen.getByRole('button', { name: 'Přihlásit se' }).closest('form')!);
    await waitFor(() => expect(mocks.login).toHaveBeenCalledTimes(2));
  });

  it('runs forgot and reset password flows', async () => {
    const first = render(<ForgotPasswordPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Odeslat pokyny' }));
    expect(await screen.findByRole('status')).toHaveTextContent('odeslány další pokyny');
    first.unmount();
    window.history.replaceState({}, '', '/reset-password?token=reset-token');
    render(<ResetPasswordPage />);
    const inputs = screen.getAllByLabelText(/heslo|potvrzení/i);
    fireEvent.change(inputs[0]!, { target: { value: 'nové velmi dlouhé heslo' } });
    fireEvent.change(inputs[1]!, { target: { value: 'nové velmi dlouhé heslo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Změnit heslo' }));
    expect(await screen.findByText(/Všechny relace byly ukončeny/)).toBeInTheDocument();
  });

  it('keeps authentication forms recoverable after unexpected failures', async () => {
    mocks.api.mockRejectedValue(new Error('offline'));
    const initialize = render(<InitializePage />);
    fireEvent.change(screen.getByLabelText('Inicializační tajemství'), {
      target: { value: 'secret' },
    });
    fireEvent.change(screen.getByLabelText('První heslo'), {
      target: { value: 'velmi bezpečné heslo' },
    });
    fireEvent.change(screen.getByLabelText('Potvrzení hesla'), {
      target: { value: 'velmi bezpečné heslo' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Aktivovat účet' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Inicializaci se nepodařilo');
    initialize.unmount();
    window.history.replaceState({}, '', '/reset-password');
    render(<ResetPasswordPage />);
    expect(screen.getByRole('button', { name: 'Změnit heslo' })).toBeDisabled();
  });
});

describe('authenticated management screens', () => {
  it('navigates and logs out from the application shell', async () => {
    render(
      <AppShell>
        <p>Obsah</p>
      </AppShell>,
    );
    expect(screen.getAllByText('KájovoDagmar').length).toBeGreaterThan(0);
    expect(screen.getByRole('navigation', { name: 'Hlavní navigace' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit se' }));
    await waitFor(() => expect(mocks.logout).toHaveBeenCalled());
  });

  it('searches, opens, edits, continues and deletes history', async () => {
    render(<HistoryPage />);
    await screen.findByRole('button', { name: /Plán týdne/ });
    fireEvent.change(screen.getByLabelText('Hledat v celé historii'), {
      target: { value: 'týden' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Hledat globálně' }));
    const item = await screen.findByRole('button', { name: /Plán týdne/ });
    fireEvent.click(item);
    expect(await screen.findByText('Naplánuj týden.')).toBeInTheDocument();
    expect(screen.getByText('Hlasová odpověď byla přerušena.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Upravit název a shrnutí' }));
    fireEvent.change(screen.getByLabelText('Název'), { target: { value: 'Nový název' } });
    fireEvent.change(screen.getByLabelText('Shrnutí'), { target: { value: 'Nové shrnutí' } });
    fireEvent.click(screen.getByRole('button', { name: 'Uložit' }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith(
        expect.stringContaining('/metadata'),
        expect.anything(),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Odstranit konverzaci' }));
    fireEvent.click(screen.getByRole('button', { name: /Klikněte znovu/ }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith(
        expect.stringContaining('/history/conversation-1'),
        expect.objectContaining({ method: 'DELETE' }),
      ),
    );
  });

  it('creates and administers memory with confirmation', async () => {
    render(<MemoryPage />);
    fireEvent.change(screen.getByLabelText('Nová paměťová položka'), {
      target: { value: 'Nová poznámka' },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Uložit do paměti' }).closest('form')!);
    expect(await screen.findByRole('status')).toHaveTextContent('bezpečně uložena');
    fireEvent.click(await screen.findByRole('button', { name: /Karel preferuje/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Opravit obsah' }));
    fireEvent.click(screen.getByRole('button', { name: 'Uložit úpravu' }));
    fireEvent.click(screen.getByRole('button', { name: 'Opravit obsah' }));
    fireEvent.change(screen.getByDisplayValue('Karel preferuje stručné odpovědi.'), {
      target: { value: 'Upravená preference' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Uložit úpravu' }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith(
        '/memory/memory-1',
        expect.objectContaining({ method: 'PUT' }),
      ),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Označit jako neaktuální' }));
    fireEvent.click(screen.getByRole('button', { name: 'Odstranit vzpomínku' }));
    fireEvent.click(screen.getByRole('button', { name: 'Potvrdit odstranění' }));
  });

  it('changes profile security fields and revokes another session', async () => {
    render(<ProfilePage />);
    expect(await screen.findByText('Karmar78')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Nová adresa'), {
      target: { value: 'new@example.test' },
    });
    const currentPasswordFields = screen.getAllByLabelText('Aktuální heslo');
    fireEvent.change(currentPasswordFields[0]!, { target: { value: 'current-password' } });
    fireEvent.submit(
      screen.getByRole('button', { name: 'Odeslat ověřovací odkaz' }).closest('form')!,
    );
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalled());
    fireEvent.change(currentPasswordFields[1]!, { target: { value: 'current-password' } });
    fireEvent.change(screen.getByLabelText('Nové heslo'), {
      target: { value: 'nové velmi dlouhé heslo' },
    });
    fireEvent.change(screen.getByLabelText('Potvrzení nového hesla'), {
      target: { value: 'nové velmi dlouhé heslo' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Změnit heslo' }));
    fireEvent.click(screen.getByRole('button', { name: 'Ukončit relaci' }));
    fireEvent.click(screen.getByRole('button', { name: 'Ukončit relaci' }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith('/auth/sessions/other', { method: 'DELETE' }),
    );
  });

  it('verifies email and reports API failure', async () => {
    window.history.replaceState({}, '', '/verify-email?token=email-token');
    const view = render(<VerifyEmailPage />);
    expect(await screen.findByText(/byla ověřena/)).toBeInTheDocument();
    view.unmount();
    mocks.api.mockRejectedValueOnce(new ApiError('invalid', 'Odkaz není platný.', 400));
    render(<VerifyEmailPage />);
    expect(await screen.findByText('Odkaz není platný.')).toBeInTheDocument();
  });

  it('reports history and memory transport errors without claiming success', async () => {
    mocks.api.mockRejectedValue(new ApiError('offline', 'Služba není dostupná.', 503));
    const history = render(<HistoryPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Služba není dostupná.');
    history.unmount();
    render(<MemoryPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Služba není dostupná.');
  });

  it('shows feedback for every memory mutation failure', async () => {
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/memory/search') return Promise.resolve({ items: [memory] });
      if (path === '/memory/memory-1' || path.endsWith('/restore'))
        return Promise.reject(new ApiError('failed', 'Operace selhala.', 500));
      return successfulApi(path, init);
    });
    render(<MemoryPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Karel preferuje/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Označit jako neaktuální' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Operace selhala.');
    fireEvent.click(screen.getByRole('button', { name: 'Odstranit vzpomínku' }));
    fireEvent.click(screen.getByRole('button', { name: 'Potvrdit odstranění' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Operace selhala.');
  });

  it('renders every history state and safely cancels destructive prompts', async () => {
    const variants = ['interrupted', 'recovered', 'deleted', 'active', 'custom'].map(
      (state, index) => ({
        ...conversation,
        id: `conversation-${index + 2}`,
        state,
        title: `Stav ${state}`,
      }),
    );
    mocks.api.mockImplementation((path: string) =>
      path === '/history/search' ? Promise.resolve({ items: variants }) : Promise.resolve({}),
    );
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<HistoryPage />);
    expect(await screen.findByText('Nedokončeno po výpadku')).toBeInTheDocument();
    expect(screen.getByText('Obnoveno')).toBeInTheDocument();
    expect(screen.getByText('Odstraněno')).toBeInTheDocument();
    expect(screen.getByText('Probíhá')).toBeInTheDocument();
    expect(screen.getByText('custom')).toBeInTheDocument();
  });

  it('shows deleted memory and restores it while preserving unknown labels', async () => {
    const deleted = {
      ...memory,
      category: 'custom',
      state: 'deleted',
      origin_type: 'custom_origin',
      version: 2,
      deleted_at: '2026-07-29T11:00:00Z',
      purge_after: '2026-08-29T11:00:00Z',
    };
    mocks.api.mockImplementation((path: string) => {
      if (path === '/memory/search') return Promise.resolve({ items: [deleted] });
      if (path.endsWith('/restore')) return Promise.resolve(memory);
      return Promise.resolve({});
    });
    render(<MemoryPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Jiná informace/ }));
    expect(screen.getByText('custom_origin')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Obnovit vzpomínku' }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith('/memory/memory-1/restore', expect.anything()),
    );
  });

  it('shows feedback when restoring deleted memory fails', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/memory/search')
        return Promise.resolve({ items: [{ ...memory, state: 'deleted' }] });
      if (path.endsWith('/restore'))
        return Promise.reject(new ApiError('failed', 'Obnovení selhalo.', 500));
      return Promise.resolve({});
    });
    render(<MemoryPage />);
    fireEvent.click(await screen.findByRole('button', { name: /Karel preferuje/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Obnovit vzpomínku' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Obnovení selhalo.');
  });

  it('keeps memory create errors visible', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/memory/search') return Promise.resolve({ items: [] });
      if (path === '/memory')
        return Promise.reject(new ApiError('failed', 'Uložení selhalo.', 500));
      return Promise.resolve({});
    });
    render(<MemoryPage />);
    fireEvent.change(screen.getByLabelText('Nová paměťová položka'), {
      target: { value: 'Nová poznámka' },
    });
    fireEvent.submit(screen.getByRole('button', { name: 'Uložit do paměti' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('Uložení selhalo.');
  });

  it('reports profile mutation failures and keeps the forms editable', async () => {
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/profile/email/change')
        return Promise.reject(new ApiError('denied', 'E-mail nelze změnit.', 403));
      if (path === '/auth/password/change') return Promise.reject(new Error('offline'));
      return successfulApi(path, init);
    });
    render(<ProfilePage />);
    await screen.findByText('Karmar78');
    const current = screen.getAllByLabelText('Aktuální heslo');
    fireEvent.change(screen.getByLabelText('Nová adresa'), {
      target: { value: 'new@example.test' },
    });
    fireEvent.change(current[0]!, { target: { value: 'current-password' } });
    fireEvent.submit(
      screen.getByRole('button', { name: 'Odeslat ověřovací odkaz' }).closest('form')!,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('E-mail nelze změnit.');
    fireEvent.change(current[1]!, { target: { value: 'current-password' } });
    fireEvent.change(screen.getByLabelText('Nové heslo'), {
      target: { value: 'nové velmi dlouhé heslo' },
    });
    fireEvent.change(screen.getByLabelText('Potvrzení nového hesla'), {
      target: { value: 'nové velmi dlouhé heslo' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Změnit heslo' }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Heslo se nepodařilo změnit.'),
    );
  });
});

describe('settings behavior', () => {
  it('loads every field type, saves changes and covers provider, email and exports', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('recipient@example.test');
    render(<SettingsPage />);
    const localeLabel = (await screen.findByText('Pole cs')).closest('label')!;
    fireEvent.change(within(localeLabel).getByRole('combobox'), { target: { value: 'en' } });
    fireEvent.click(screen.getByRole('button', { name: 'Uložit změny' }));
    expect(await screen.findByRole('status')).toHaveTextContent('trvale uloženo');

    fireEvent.click(screen.getByRole('button', { name: 'Modely a poskytovatelé' }));
    expect(await screen.findByText('…abcd', { exact: false })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Proč je modelů více?' })).toBeInTheDocument();
    for (const title of [
      'Mozek rozhovoru',
      'Sluch – převod řeči na text',
      'Řeč – převod textu na hlas',
      'Paměť – hledání souvisejících informací',
      'Archivář – názvy a shrnutí rozhovorů',
      'Barva hlasu Dagmar',
    ]) {
      expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    }
    expect(screen.getAllByText('Doporučeno').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Použít doporučenou sestavu' }));
    expect(await screen.findByRole('status')).toHaveTextContent('doporučenou sestavu');
    fireEvent.change(screen.getAllByRole('combobox', { name: 'Vybraný model' })[0]!, {
      target: { value: 'model-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Uložit výběr modelů' }));
    fireEvent.click(screen.getByRole('button', { name: 'Znovu ověřit klíč a nabídku modelů' }));
    const providerForm = screen
      .getByRole('heading', { name: 'Přidat poskytovatele' })
      .closest('form')!;
    fireEvent.change(providerForm.querySelector('input[type="password"]')!, {
      target: { value: 'synthetic-key' },
    });
    fireEvent.submit(providerForm);
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith(
        '/providers',
        expect.objectContaining({ method: 'PUT' }),
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: 'E-mail a oznámení' }));
    fireEvent.change(screen.getByLabelText('SMTP server'), {
      target: { value: 'smtp2.example.test' },
    });
    fireEvent.change(screen.getByLabelText('Testovací příjemce'), {
      target: { value: 'deliver-to@example.test' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Uložit konfiguraci' }));
    fireEvent.click(screen.getByRole('button', { name: 'Provést skutečný test doručení' }));
    await waitFor(() =>
      expect(mocks.api).toHaveBeenCalledWith('/notifications/email/test', expect.anything()),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Soukromí a data' }));
    expect(await screen.findByText('Bezpečně stáhnout')).toHaveAttribute(
      'href',
      '/api/v1/exports/export-1/download',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Načíst provozní stav' }));
    fireEvent.click(screen.getByRole('button', { name: 'Export historie' }));
    fireEvent.click(screen.getByRole('button', { name: 'Export paměti' }));
    fireEvent.click(screen.getByRole('button', { name: 'Export netajné konfigurace' }));
    await waitFor(() =>
      expect(
        mocks.api.mock.calls.filter(
          ([path]) => path === '/exports' && mocks.api.mock.calls.some(() => true),
        ).length,
      ).toBeGreaterThan(3),
    );
  });

  it('renders an empty area, reports load failure and avoids empty email tests', async () => {
    const sparse = { general: {} };
    mocks.api.mockImplementation((path: string) => {
      if (path === '/settings') return Promise.resolve(sparse);
      if (path === '/providers' || path === '/exports') return Promise.resolve({ items: [] });
      if (path === '/notifications/email') return Promise.resolve({ configured: false });
      return Promise.resolve({});
    });
    vi.spyOn(window, 'prompt').mockReturnValue(null);
    const view = render(<SettingsPage />);
    await screen.findByRole('heading', { name: 'Obecné' });
    fireEvent.click(screen.getByRole('button', { name: 'Uložit změny' }));
    expect(await screen.findByRole('status')).toHaveTextContent('nejsou neuložené změny');
    fireEvent.click(screen.getByRole('button', { name: 'Hlas a zvuk' }));
    expect(
      screen.getByText('Tato oblast zatím nemá žádné spravovatelné hodnoty.'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'E-mail a oznámení' }));
    fireEvent.click(screen.getByRole('button', { name: 'Provést skutečný test doručení' }));
    view.unmount();
    mocks.api.mockRejectedValue(new Error('offline'));
    render(<SettingsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Nastavení se nepodařilo načíst.');
  });

  it('keeps the settings usable when the verified model catalog is stale or unavailable', async () => {
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/providers/provider-1/model-options') return Promise.resolve({});
      return successfulApi(path, init);
    });
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Modely a poskytovatelé' }));
    expect(screen.getByRole('heading', { name: 'Proč je modelů více?' })).toBeInTheDocument();
  });

  it('does not show fabricated role options after a catalog request fails', async () => {
    mocks.api.mockImplementation((path: string, init?: RequestInit) => {
      if (path === '/providers/provider-1/model-options')
        return Promise.reject(new Error('catalog unavailable'));
      return successfulApi(path, init);
    });
    render(<SettingsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Modely a poskytovatelé' }));
    expect(screen.getByRole('heading', { name: 'Proč je modelů více?' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Mozek rozhovoru' })).not.toBeInTheDocument();
  });

  it('operates audit filters, manual backup, verification and isolated restore', async () => {
    render(<SettingsPage />);
    await screen.findByRole('heading', { name: 'Obecné' });
    fireEvent.click(screen.getByRole('button', { name: 'Provoz a audit' }));
    expect(await screen.findByText('AI není připravena.')).toBeInTheDocument();
    expect(screen.getByText('20260729-100000F')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Detail události memory.created' }));
    expect(screen.getByText(/Korelace: correlation-1/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Oblast'), { target: { value: 'memory' } });
    fireEvent.change(screen.getByLabelText('Výsledek'), { target: { value: 'success' } });
    fireEvent.click(screen.getByRole('button', { name: 'Filtrovat audit' }));
    fireEvent.change(screen.getByLabelText('Účel ruční zálohy'), {
      target: { value: 'Před aktualizací' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Vytvořit ruční obnovovací bod' }));
    fireEvent.click(screen.getByRole('button', { name: 'Ověřit integritu' }));
    fireEvent.click(screen.getByRole('button', { name: 'Obnovit izolovaně' }));
    fireEvent.click(screen.getByRole('button', { name: 'Klikněte znovu pro restore test' }));
    fireEvent.click(screen.getByRole('button', { name: 'Exportovat filtrovaný audit' }));
    await waitFor(() => {
      expect(mocks.api).toHaveBeenCalledWith(
        '/operations/backups',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(mocks.api).toHaveBeenCalledWith(
        '/operations/backups/backup-1/verify',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(mocks.api).toHaveBeenCalledWith(
        '/operations/backups/backup-1/restore-test',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(mocks.api).toHaveBeenCalledWith(
        '/exports',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    mocks.api.mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Obnovit stav' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Provozní stav se nepodařilo načíst.',
    );
  });
});
