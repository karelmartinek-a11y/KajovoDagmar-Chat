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

it('rejects useAuth outside its provider', () => {
  expect(() => render(<Probe />)).toThrow('AuthProvider není dostupný.');
});
