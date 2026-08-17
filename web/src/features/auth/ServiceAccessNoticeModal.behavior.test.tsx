import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => vi.fn());
vi.mock('../../api/client', () => ({ api: apiMock }));

import { ServiceAccessNoticeModal } from './ServiceAccessNoticeModal';

const notice = {
  id: 'notice-1',
  occurred_at: '2026-08-15T10:00:00.000Z',
  result: 'accepted',
  endpoint: 'realtime.ticket',
  network_context: '127.0.0.0/24',
  correlation_id: 'corr-1',
};

beforeEach(() => vi.clearAllMocks());

it('shows service access details and acknowledges the notice', async () => {
  const acknowledged = vi.fn();
  apiMock.mockResolvedValue(undefined);
  render(<ServiceAccessNoticeModal notice={notice} onAcknowledged={acknowledged} />);
  expect(screen.getByRole('dialog')).toHaveTextContent('Použití servisního přístupu');
  expect(screen.getByRole('dialog')).toHaveTextContent('realtime.ticket');
  fireEvent.click(screen.getByRole('button', { name: 'Rozumím' }));
  await waitFor(() =>
    expect(apiMock).toHaveBeenCalledWith('/auth/service-access-notices/notice-1/ack', {
      method: 'POST',
    }),
  );
  expect(acknowledged).toHaveBeenCalled();
});
