import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ api: vi.fn(), setCsrfToken: vi.fn() }));
vi.mock('./api/client', () => ({ api: mocks.api, setCsrfToken: mocks.setCsrfToken }));

import { AuthProvider, useAuth } from './features/auth/AuthContext';

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span>{auth.loading ? 'loading' : auth.instanceState}</span>
      <span>{auth.user?.username ?? 'anonymous'}</span>
      <button onClick={() => void auth.login('safe password')}>login</button>
      <button onClick={() => void auth.logout()}>logout</button>
      <button onClick={() => void auth.refresh()}>refresh</button>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it('refreshes active identity, logs in and logs out with CSRF rotation', async () => {
  mocks.api.mockImplementation((path: string) => {
    if (path === '/auth/state') return Promise.resolve({ instance_state: 'active' });
    if (path === '/auth/me')
      return Promise.resolve({
        id: 'account-1',
        username: 'Karmar78',
        state: 'active',
        profile: { display_name: 'Karel', email: null, email_state: 'not_set' },
      });
    if (path === '/auth/login') return Promise.resolve({ csrf_token: 'csrf-value' });
    return Promise.resolve(undefined);
  });
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  expect(await screen.findByText('Karmar78')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'login' }));
  await waitFor(() => expect(mocks.setCsrfToken).toHaveBeenCalledWith('csrf-value'));
  fireEvent.click(screen.getByRole('button', { name: 'logout' }));
  await waitFor(() => expect(mocks.setCsrfToken).toHaveBeenCalledWith(null));
  expect(screen.getByText('anonymous')).toBeInTheDocument();
});

it('handles uninitialized state and a failed current-user lookup', async () => {
  mocks.api.mockResolvedValueOnce({ instance_state: 'uninitialized' });
  const view = render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  expect(await screen.findByText('uninitialized')).toBeInTheDocument();
  mocks.api
    .mockResolvedValueOnce({ instance_state: 'active' })
    .mockRejectedValueOnce(new Error('expired'));
  fireEvent.click(screen.getByRole('button', { name: 'refresh' }));
  await waitFor(() => expect(screen.getByText('anonymous')).toBeInTheDocument());
  view.unmount();
});

it('does not let an older state response overwrite a newer refresh', async () => {
  let resolveInitialState: ((value: unknown) => void) | undefined;
  const initialState = new Promise((resolve) => {
    resolveInitialState = resolve;
  });
  let stateCalls = 0;
  let userCalls = 0;
  mocks.api.mockImplementation((path: string) => {
    if (path === '/auth/state') {
      stateCalls += 1;
      return stateCalls === 1
        ? initialState
        : Promise.resolve({ instance_state: 'active', username: 'acceptance-race' });
    }
    if (path === '/auth/me')
      return Promise.resolve({
        id: 'account-race',
        username: 'acceptance-race',
        state: 'active',
        profile: { display_name: 'Synthetic', email: null, email_state: 'not_set' },
      });
    return Promise.resolve(undefined);
  });

  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'refresh' }));
  expect(await screen.findByText('acceptance-race')).toBeInTheDocument();
  resolveInitialState?.({ instance_state: 'uninitialized', username: 'Karmar78' });
  await waitFor(() => expect(screen.getByText('active')).toBeInTheDocument());
  expect(screen.getByText('acceptance-race')).toBeInTheDocument();
});

it('does not let an older user response overwrite a newer refresh', async () => {
  let resolveInitialUser: ((value: unknown) => void) | undefined;
  const initialUser = new Promise((resolve) => {
    resolveInitialUser = resolve;
  });
  let stateCalls = 0;
  let userCalls = 0;
  mocks.api.mockImplementation((path: string) => {
    if (path === '/auth/state') {
      stateCalls += 1;
      return stateCalls === 1
        ? Promise.resolve({ instance_state: 'active', username: 'acceptance-user-race' })
        : Promise.resolve({ instance_state: 'uninitialized', username: 'Karmar78' });
    }
    if (path === '/auth/me') {
      userCalls += 1;
      return initialUser;
    }
    return Promise.resolve(undefined);
  });

  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await waitFor(() => expect(userCalls).toBe(1));
  fireEvent.click(screen.getByRole('button', { name: 'refresh' }));
  await waitFor(() => expect(stateCalls).toBe(2));
  resolveInitialUser?.({
    id: 'account-user-race',
    username: 'acceptance-user-race',
    state: 'active',
    profile: { display_name: 'Synthetic', email: null, email_state: 'not_set' },
  });
  await waitFor(() => expect(screen.getByText('uninitialized')).toBeInTheDocument());
  expect(screen.getByText('anonymous')).toBeInTheDocument();
});

it('rejects useAuth outside its provider', () => {
  expect(() => render(<Probe />)).toThrow('AuthProvider není dostupný.');
});
