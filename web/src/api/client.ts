export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
    public readonly details?: unknown,
  ) {
    super(message);
  }
}

let csrfToken: string | null = sessionStorage.getItem('kajovodagmar.csrf');

export function setCsrfToken(value: string | null): void {
  csrfToken = value;
  if (value) sessionStorage.setItem('kajovodagmar.csrf', value);
  else sessionStorage.removeItem('kajovodagmar.csrf');
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes((init.method ?? 'GET').toUpperCase())) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: 'same-origin' });
  } catch (cause) {
    throw new ApiError(
      'network_error',
      'Síťové spojení se nepodařilo navázat. Zkontrolujte připojení a zkuste to znovu.',
      0,
      cause instanceof Error ? { cause: cause.name } : undefined,
    );
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  let body: Record<string, unknown> = {};
  const raw = await response.text();
  if (contentType.includes('application/json') || raw.trimStart().startsWith('{')) {
    try {
      body = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      body = {};
    }
  } else if (raw) {
    body = { message: raw.slice(0, 500) };
  }
  if (!response.ok) {
    const error = body.error as { code?: string; message?: string; details?: unknown } | undefined;
    throw new ApiError(
      error?.code ?? 'request_failed',
      error?.message ?? 'Požadavek se nepodařilo dokončit.',
      response.status,
      error?.details ?? {
        correlation_id: response.headers.get('X-Correlation-ID'),
      },
    );
  }
  return body as T;
}
