import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  auth: {
    instanceState: 'active',
    user: null as null | {
      id: string;
      username: string;
      state: string;
      profile: { display_name: string; email: string | null; email_state: string };
    },
    loading: false,
    refresh: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
  listeners: new Set<(snapshot: unknown) => void>(),
  start: vi.fn(),
  startAndSendText: vi.fn(),
  sendText: vi.fn(),
  finishTurn: vi.fn(),
  interrupt: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  end: vi.fn(),
  confirmAction: vi.fn(),
}));

vi.mock('./features/auth/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('./audio/VoiceClient', () => ({
  VoiceClient: class {
    subscribe(listener: (snapshot: unknown) => void) {
      mocks.listeners.add(listener);
      return () => mocks.listeners.delete(listener);
    }
    start = mocks.start;
    startAndSendText = mocks.startAndSendText;
    sendText = mocks.sendText;
    finishTurn = mocks.finishTurn;
    interrupt = mocks.interrupt;
    pause = mocks.pause;
    resume = mocks.resume;
    end = mocks.end;
    confirmAction = mocks.confirmAction;
  },
}));

import { App } from './app/App';
import { ChatPage } from './features/chat/ChatPage';
import type { VoiceSnapshot } from './audio/VoiceClient';

const user = {
  id: 'account-1',
  username: 'Karmar78',
  state: 'active',
  profile: { display_name: 'Karel', email: null, email_state: 'not_set' },
};
const baseSnapshot: VoiceSnapshot = {
  state: 'ready',
  stateMessage: 'Připraveno',
  transcript: [],
  partialTranscript: '',
  error: null,
  microphoneActive: false,
  permissionState: 'unknown',
  deviceState: 'unknown',
  trackState: 'unavailable',
  captureState: 'idle',
  audioContextState: 'unknown',
  connectionState: 'disconnected',
  turnState: 'idle',
  backgroundState: 'foreground',
  wakeLockState: 'unsupported',
  lastAudioFrameAt: null,
  audioRetryAvailable: false,
  conversationId: null,
  actions: [],
};
function emit(snapshot: Partial<VoiceSnapshot>) {
  const value = { ...baseSnapshot, ...snapshot };
  mocks.listeners.forEach((listener) => listener(value));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.listeners.clear();
  mocks.auth.instanceState = 'active';
  mocks.auth.user = null;
  mocks.auth.loading = false;
  window.history.replaceState({}, '', '/login');
});

describe('application routing', () => {
  it('shows loading, initialization and login states', () => {
    mocks.auth.loading = true;
    const view = render(<App />);
    expect(screen.getByText(/Načítám bezpečný stav/)).toHaveAttribute('aria-busy', 'true');
    mocks.auth.loading = false;
    mocks.auth.instanceState = 'uninitialized';
    view.rerender(<App />);
    expect(screen.getByRole('heading', { name: 'Bezpečné první spuštění' })).toBeInTheDocument();
    mocks.auth.instanceState = 'active';
    view.rerender(<App />);
    expect(screen.getByRole('heading', { name: 'Přihlášení' })).toBeInTheDocument();
  });

  it('protects private pages and renders chat for an authenticated user', async () => {
    window.history.replaceState({}, '', '/chat');
    const view = render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    mocks.auth.user = user;
    window.history.replaceState({}, '', '/chat');
    view.rerender(<App />);
    expect(screen.getByRole('heading', { name: 'Chat' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Hlavní navigace' })).toBeInTheDocument();
  });
});

describe('chat screen behavior', () => {
  it('starts voice and sends a first text conversation', async () => {
    render(<ChatPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Zahájit rozhovor' }));
    expect(mocks.start).toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Textová zpráva'), { target: { value: 'Ahoj Dagmar' } });
    fireEvent.click(screen.getByRole('button', { name: 'Odeslat zprávu' }));
    expect(mocks.startAndSendText).toHaveBeenCalledWith('Ahoj Dagmar');
  });

  it('renders transcript, partial text and all state-specific controls', async () => {
    render(<ChatPage />);
    await waitFor(() => expect(mocks.listeners.size).toBe(1));
    act(() =>
      emit({
        state: 'listening',
        stateMessage: 'Naslouchám',
        microphoneActive: true,
        conversationId: 'conversation-1',
        partialTranscript: 'průběžný text',
        transcript: [
          { id: 'u1', role: 'user', text: 'Dotaz', final: true },
          { id: 'a1', role: 'assistant', text: 'Odpověď', final: true, interrupted: true },
        ],
      }),
    );
    expect(screen.getByText('průběžný text')).toBeInTheDocument();
    expect(screen.getByText('Odpověď byla přerušena.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Stav asistentky: listening/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Dokončit repliku' }));
    fireEvent.click(screen.getByRole('button', { name: 'Pozastavit mikrofon' }));
    expect(mocks.finishTurn).toHaveBeenCalled();
    expect(mocks.pause).toHaveBeenCalled();
    act(() =>
      emit({ state: 'paused', stateMessage: 'Pozastaveno', conversationId: 'conversation-1' }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Obnovit mikrofon' }));
    act(() =>
      emit({ state: 'responding', stateMessage: 'Odpovídám', conversationId: 'conversation-1' }),
    );
    fireEvent.click(screen.getByRole('button', { name: /Stav asistentky: responding/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Přerušit odpověď' }));
    fireEvent.change(screen.getByLabelText('Textová zpráva'), {
      target: { value: 'Navazující zpráva' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Odeslat zprávu' }));
    fireEvent.click(screen.getByRole('button', { name: 'Ukončit rozhovor' }));
    expect(mocks.resume).toHaveBeenCalled();
    expect(mocks.interrupt).toHaveBeenCalled();
    expect(mocks.sendText).toHaveBeenCalledWith('Navazující zpráva');
    expect(mocks.end).toHaveBeenCalled();
  });

  it('confirms pending actions and reports completed actions and errors', async () => {
    render(<ChatPage />);
    await waitFor(() => expect(mocks.listeners.size).toBe(1));
    act(() =>
      emit({
        state: 'error',
        stateMessage: 'Vyžaduje pozornost',
        error: 'Spojení selhalo.',
        conversationId: 'conversation-1',
        actions: [
          {
            id: 'pending',
            name: 'memory.create',
            state: 'pending_confirmation',
            preview: {
              operation: 'Uložit vzpomínku',
              content: 'Obsah',
              target: 'Paměť',
              impact: 'Vratné',
            },
            version: 3,
          },
          {
            id: 'completed',
            name: 'history.export',
            state: 'completed',
            preview: {},
            version: 2,
          },
          {
            id: 'fallback',
            name: 'memory.update',
            state: 'pending_confirmation',
            preview: { operation: { invalid: true }, content: 42, target: null, impact: false },
            version: 1,
          },
        ],
      }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Spojení selhalo.');
    expect(screen.getByRole('status')).toHaveTextContent('bezpečně dokončena');
    const confirmations = screen.getAllByRole('button', { name: 'Potvrdit operaci' });
    fireEvent.click(confirmations[0]!);
    fireEvent.click(confirmations[1]!);
    expect(mocks.confirmAction).toHaveBeenCalledWith('pending', 3);
    expect(screen.getByText('Navržená změna')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Stav asistentky: error/ }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Zahájit rozhovor' })[0]!);
    expect(mocks.start).toHaveBeenCalled();
  });
});
