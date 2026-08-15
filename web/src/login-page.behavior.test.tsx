import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

const login = vi.fn();

vi.mock('./features/auth/AuthContext', () => ({
  useAuth: () => ({ login, username: 'acceptance-synthetic' }),
}));

import { LoginPage } from './features/auth/LoginPage';

it('uses the initialized username instead of a hard-coded login identity', () => {
  render(<LoginPage />);

  expect(screen.getByLabelText('Uživatelské jméno')).toHaveValue('acceptance-synthetic');
  expect(screen.getByText(/administrátora acceptance-synthetic/)).toBeInTheDocument();
});
