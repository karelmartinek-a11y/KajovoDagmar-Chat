import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, setCsrfToken } from './client';

const fetchMock = vi.fn<typeof fetch>();

describe('API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    setCsrfToken(null);
  });

  it('returns JSON and applies same-origin credentials', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ value: 42 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await expect(api<{ value: number }>('/state')).resolves.toEqual({ value: 42 });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/state',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
  });

  it('sets JSON and CSRF headers only for state-changing requests', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    setCsrfToken('csrf-token');

    await expect(api('/memory', { method: 'POST', body: '{}' })).resolves.toBeUndefined();
    const request = fetchMock.mock.calls[0]?.[1];
    const headers = new Headers(request?.headers);
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(headers.get('X-CSRF-Token')).toBe('csrf-token');

    setCsrfToken(null);
    expect(sessionStorage.getItem('kajovodagmar.csrf')).toBeNull();
  });

  it('throws the versioned server error and safe fallback error', async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: { code: 'conflict', message: 'Data byla změněna.', details: { version: 2 } },
          }),
          { status: 409 },
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 500 }));

    await expect(api('/memory')).rejects.toEqual(
      new ApiError('conflict', 'Data byla změněna.', 409, { version: 2 }),
    );
    await expect(api('/memory')).rejects.toMatchObject({
      code: 'request_failed',
      status: 500,
    });
  });
});
