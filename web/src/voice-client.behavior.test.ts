import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => vi.fn());
vi.mock('./api/client', () => ({ api: apiMock }));

import { VoiceClient, type VoiceSnapshot } from './audio/VoiceClient';

class FakeTrack {
  enabled = true;
  muted = false;
  readyState = 'live';
  events = new Map<string, () => void>();
  addEventListener = vi.fn((name: string, handler: () => void) => this.events.set(name, handler));
  stop = vi.fn();
}
class FakePort {
  onmessage: ((event: MessageEvent<ArrayBuffer>) => void) | null = null;
}
class FakeWorkletNode {
  port = new FakePort();
  disconnect = vi.fn();
}
class FakeMediaStream {
  track = new FakeTrack();
  getAudioTracks() {
    return [this.track];
  }
  getTracks() {
    return [this.track];
  }
}
class FakeSource {
  connect = vi.fn();
  disconnect = vi.fn();
}
class FakeBufferSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  connect = vi.fn();
  start = vi.fn(() => this.onended?.());
  stop = vi.fn();
}
class FakeGain {
  connect = vi.fn();
}
class FakeAudioContext {
  state = 'running';
  onstatechange: (() => void) | null = null;
  destination = {};
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
  createMediaStreamSource = vi.fn(() => new FakeSource());
  createBuffer = vi.fn((_channels: number, length: number) => {
    const data = new Float32Array(length);
    return { getChannelData: () => data } as unknown as AudioBuffer;
  });
  createBufferSource = vi.fn(() => new FakeBufferSource() as unknown as AudioBufferSourceNode);
  createGain = vi.fn(() => new FakeGain() as unknown as GainNode);
  resume = vi.fn().mockResolvedValue(undefined);
  close = vi.fn().mockResolvedValue(undefined);
}
class FakeWebSocket {
  static readonly OPEN = 1;
  readonly OPEN = 1;
  readyState = 1;
  bufferedAmount = 0;
  binaryType = '';
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: Array<string | ArrayBufferLike | Blob | ArrayBufferView> = [];
  constructor(
    readonly url: URL,
    readonly protocol: string,
  ) {
    window.setTimeout(() => this.onopen?.(), 0);
  }
  send(data: string | ArrayBufferLike | Blob | ArrayBufferView) {
    this.sent.push(data);
    if (typeof data === 'string') {
      const envelope = JSON.parse(data) as { type: string };
      if (envelope.type === 'session.start')
        window.setTimeout(
          () =>
            this.onmessage?.(
              new MessageEvent('message', {
                data: JSON.stringify({
                  version: '1.0',
                  event_id: 'started',
                  sequence: 1,
                  type: 'session.started',
                  conversation_id: 'conversation-1',
                  payload: {},
                }),
              }),
            ),
          0,
        );
    }
  }
  close = vi.fn();
}

function latest(client: VoiceClient): VoiceSnapshot {
  let value: VoiceSnapshot | undefined;
  const unsubscribe = client.subscribe((snapshot) => {
    value = snapshot;
  });
  unsubscribe();
  return value!;
}

async function deliver(
  client: VoiceClient,
  sequence: number,
  type: string,
  payload: Record<string, unknown> = {},
) {
  const onMessage = Reflect.get(client, 'onMessage') as (
    this: VoiceClient,
    event: MessageEvent,
  ) => Promise<void>;
  await onMessage.call(
    client,
    new MessageEvent('message', {
      data: JSON.stringify({
        version: '1.0',
        event_id: `event-${sequence}`,
        sequence,
        type,
        conversation_id: 'conversation-1',
        payload,
      }),
    }),
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  apiMock.mockReset();
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { getUserMedia: vi.fn().mockResolvedValue(new FakeMediaStream()) },
    configurable: true,
  });
  vi.stubGlobal('AudioContext', FakeAudioContext);
  vi.stubGlobal('AudioWorkletNode', FakeWorkletNode);
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

describe('VoiceClient', () => {
  it('starts a real client lifecycle, controls microphone and closes resources', async () => {
    apiMock.mockResolvedValueOnce({ ticket: 'ticket', websocket_path: '/api/v1/realtime' });
    const client = new VoiceClient();
    const snapshots: VoiceSnapshot[] = [];
    const unsubscribe = client.subscribe((snapshot) => snapshots.push(snapshot));
    await client.start('cs');
    expect(latest(client)).toMatchObject({
      state: 'listening',
      conversationId: 'conversation-1',
      microphoneActive: false,
    });
    await client.pause();
    expect(latest(client).state).toBe('paused');
    await client.resume();
    expect(latest(client).state).toBe('listening');
    client.finishTurn();
    client.interrupt();
    const socket = Reflect.get(client, 'socket') as FakeWebSocket;
    socket.onclose?.();
    expect(latest(client).state).toBe('reconnecting');
    socket.onerror?.();
    expect(latest(client).state).toBe('error');
    await client.end();
    expect(latest(client)).toMatchObject({ state: 'ended', conversationId: null });
    expect(snapshots.length).toBeGreaterThan(5);
    unsubscribe();
  });

  it('wraps microphone PCM in ordered packets and enforces bounded backpressure', async () => {
    apiMock.mockResolvedValueOnce({ ticket: 'ticket', websocket_path: '/api/v1/realtime' });
    const client = new VoiceClient();
    await client.start('cs');
    const socket = Reflect.get(client, 'socket') as FakeWebSocket;
    const recorder = Reflect.get(client, 'recorder') as FakeWorkletNode;
    recorder.port.onmessage?.(new MessageEvent('message', { data: new ArrayBuffer(960) }));
    expect(latest(client).microphoneActive).toBe(true);
    const packet = socket.sent.at(-1);
    expect(packet).toBeInstanceOf(ArrayBuffer);
    const header = new DataView(packet as ArrayBuffer);
    expect(new TextDecoder().decode(new Uint8Array(packet as ArrayBuffer, 0, 4))).toBe('KDV1');
    expect(header.getUint32(4)).toBe(1);
    expect((packet as ArrayBuffer).byteLength).toBe(976);

    socket.bufferedAmount = 48_000;
    recorder.port.onmessage?.(new MessageEvent('message', { data: new ArrayBuffer(960) }));
    expect(latest(client).stateMessage).toContain('pomalé');
    socket.bufferedAmount = 96_000;
    recorder.port.onmessage?.(new MessageEvent('message', { data: new ArrayBuffer(960) }));
    expect(latest(client)).toMatchObject({ state: 'paused', microphoneActive: false });

    socket.bufferedAmount = 0;
    Reflect.set(client, 'snapshot', { ...latest(client), state: 'listening' });
    recorder.port.onmessage?.(new MessageEvent('message', { data: new ArrayBuffer(10) }));
    expect(latest(client).error).toContain('neplatný zvukový rámec');
    await client.end();
  });

  it('sends text over REST, merges action proposals and confirms an action', async () => {
    apiMock
      .mockResolvedValueOnce({ id: 'conversation-rest' })
      .mockResolvedValueOnce({
        user: { id: 'u1', content: 'Ahoj' },
        assistant: { id: 'a1', content: 'Dobrý den' },
        actions: [
          {
            id: 'action-1',
            name: 'memory.create',
            state: 'pending_confirmation',
            preview: { operation: 'Uložit' },
            version: 1,
          },
        ],
      })
      .mockResolvedValueOnce({
        id: 'action-1',
        name: 'memory.create',
        state: 'completed',
        preview: { operation: 'Uložit' },
        version: 2,
      });
    const client = new VoiceClient();
    await client.startAndSendText('Ahoj');
    expect(latest(client).transcript).toHaveLength(2);
    expect(latest(client).actions[0]?.state).toBe('pending_confirmation');
    await client.confirmAction('action-1', 1);
    expect(latest(client).actions[0]?.state).toBe('completed');
  });

  it('processes ordered realtime state, transcript, action and error events', async () => {
    const client = new VoiceClient();
    await deliver(client, 1, 'connection.ready');
    await deliver(client, 2, 'session.started');
    await deliver(client, 3, 'state.changed', { state: 'processing' });
    await deliver(client, 4, 'transcript.partial', { text: 'Průběžně' });
    await deliver(client, 5, 'transcript.final', { text: 'Hotovo' });
    await deliver(client, 6, 'assistant.text', {
      text: 'Odpověď',
      message_id: 'assistant-1',
      actions: [
        {
          id: 'action-2',
          name: 'history.export',
          state: 'pending_confirmation',
          preview: {},
          version: 1,
        },
      ],
    });
    expect(latest(client).transcript.map((item) => item.text)).toEqual(['Hotovo', 'Odpověď']);
    await deliver(client, 7, 'assistant.audio.end');
    await deliver(client, 8, 'assistant.interrupted');
    await deliver(client, 9, 'session.ended');
    expect(latest(client).state).toBe('ended');
    await deliver(client, 9, 'error', { message: 'duplicate ignored' });
    expect(latest(client).error).toBeNull();
    await deliver(client, 11, 'error', { message: 'gap' });
    expect(latest(client).error).toContain('Posloupnost');
  });

  it('applies canonical resume snapshots, flow control and incomplete-turn guidance', async () => {
    const client = new VoiceClient();
    const stream = new FakeMediaStream();
    Reflect.set(client, 'mediaStream', stream);
    Reflect.set(client, 'snapshot', {
      ...latest(client),
      state: 'reconnecting',
      conversationId: 'conversation-1',
    });
    await deliver(client, 1, 'connection.ready', { resume_available: true });
    await deliver(client, 2, 'session.resumed', {
      partial_transcript: 'poslední potvrzená hypotéza',
      input_incomplete: true,
    });
    expect(latest(client)).toMatchObject({
      state: 'listening',
      microphoneActive: false,
      partialTranscript: 'poslední potvrzená hypotéza',
    });
    expect(stream.track.enabled).toBe(true);
    await deliver(client, 3, 'flow_control', { level: 'soft' });
    expect(latest(client).stateMessage).toContain('pomaleji');
    await deliver(client, 4, 'flow_control', { level: 'hard' });
    expect(latest(client)).toMatchObject({ state: 'paused', microphoneActive: false });
    await deliver(client, 5, 'turn.incomplete', { message: 'Zopakujte větu.' });
    expect(latest(client).stateMessage).toBe('Zopakujte větu.');
    await deliver(client, 6, 'turn.incomplete');
    expect(latest(client).stateMessage).toContain('zopakujte');
  });

  it('keeps text when speech synthesis fails and exposes an audio retry state', async () => {
    const client = new VoiceClient();
    await deliver(client, 1, 'assistant.text', { text: 'Text hotový', message_id: 'assistant-1' });
    await deliver(client, 2, 'assistant.audio.error', {
      code: 'provider_error',
      text_available: true,
    });
    expect(latest(client).transcript.at(-1)?.text).toBe('Text hotový');
    expect(latest(client).audioRetryAvailable).toBe(true);
    expect(latest(client).error).toContain('Textová odpověď');
  });

  it('recovers only an unfinished response and never revives a terminal session', async () => {
    vi.useFakeTimers();
    try {
      const recovered = new VoiceClient();
      await deliver(recovered, 1, 'assistant.text', { text: 'Čekám na zvuk' });
      await vi.advanceTimersByTimeAsync(20_000);
      expect(latest(recovered)).toMatchObject({ state: 'listening', turnState: 'listening' });

      const endedLocally = new VoiceClient();
      await deliver(endedLocally, 1, 'assistant.text', { text: 'Končím' });
      await endedLocally.end();
      await vi.advanceTimersByTimeAsync(20_000);
      expect(latest(endedLocally).state).toBe('ended');

      for (const event of ['session.ended', 'resync.required', 'error']) {
        const terminal = new VoiceClient();
        await deliver(terminal, 1, 'assistant.text', { text: 'Terminální stav' });
        await deliver(terminal, 2, event);
        await vi.advanceTimersByTimeAsync(20_000);
        expect(latest(terminal).state).toBe(event === 'session.ended' ? 'ended' : 'error');
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it('handles audio and page lifecycle without claiming a live microphone', async () => {
    apiMock.mockResolvedValueOnce({ ticket: 'ticket', websocket_path: '/api/v1/realtime' });
    const client = new VoiceClient();
    await client.start('cs');
    const stream = Reflect.get(client, 'mediaStream') as FakeMediaStream;
    const context = Reflect.get(client, 'audioContext') as FakeAudioContext;
    stream.track.muted = true;
    stream.track.events.get('mute')?.();
    expect(latest(client).microphoneActive).toBe(false);
    stream.track.muted = false;
    stream.track.events.get('unmute')?.();
    context.state = 'suspended';
    context.onstatechange?.();
    window.dispatchEvent(new Event('offline'));
    expect(latest(client).connectionState).toBe('offline');
    document.dispatchEvent(new Event('visibilitychange'));
    await client.end();
  });

  it('publishes actionable microphone errors and wake-lock outcomes', async () => {
    for (const name of [
      'NotAllowedError',
      'NotFoundError',
      'NotReadableError',
      'OverconstrainedError',
    ]) {
      Object.defineProperty(navigator, 'mediaDevices', {
        value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException(name, name)) },
        configurable: true,
      });
      const client = new VoiceClient();
      await client.start();
      expect(latest(client).error).toBeTruthy();
    }
    const sentinel = {
      addEventListener: vi.fn(),
      release: vi.fn().mockResolvedValue(undefined),
    };
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn().mockResolvedValue(new FakeMediaStream()) },
      configurable: true,
    });
    Object.defineProperty(navigator, 'wakeLock', {
      value: { request: vi.fn().mockResolvedValue(sentinel) },
      configurable: true,
    });
    apiMock.mockResolvedValueOnce({ ticket: 'ticket', websocket_path: '/api/v1/realtime' });
    const client = new VoiceClient();
    await client.start();
    expect(latest(client).wakeLockState).toBe('acquired');
    await client.end();
    expect(sentinel.release).toHaveBeenCalled();

    Object.defineProperty(navigator, 'wakeLock', {
      value: { request: vi.fn().mockRejectedValue(new Error('blocked')) },
      configurable: true,
    });
    apiMock.mockResolvedValueOnce({ ticket: 'ticket', websocket_path: '/api/v1/realtime' });
    const blockedClient = new VoiceClient();
    await blockedClient.start();
    expect(latest(blockedClient).wakeLockState).toBe('blocked');
    const blockedContext = Reflect.get(blockedClient, 'audioContext') as FakeAudioContext;
    blockedContext.resume.mockRejectedValueOnce(new Error('gesture'));
    await (
      Reflect.get(blockedClient, 'resumeAudioContext') as (this: VoiceClient) => Promise<void>
    ).call(blockedClient);
    expect(latest(blockedClient).audioRetryAvailable).toBe(true);
    await blockedClient.end();

    Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true });
    const unsupportedClient = new VoiceClient();
    await unsupportedClient.start();
    expect(latest(unsupportedClient).error).toContain('nepodporuje');

    Reflect.deleteProperty(navigator, 'wakeLock');
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: vi.fn().mockResolvedValue(new FakeMediaStream()) },
      configurable: true,
    });
    apiMock.mockResolvedValueOnce({ ticket: 'ticket', websocket_path: '/api/v1/realtime' });
    const unsupportedWakeLockClient = new VoiceClient();
    await unsupportedWakeLockClient.start();
    expect(latest(unsupportedWakeLockClient).wakeLockState).toBe('unsupported');
    const unsupportedTrack = Reflect.get(
      unsupportedWakeLockClient,
      'mediaStream',
    ) as FakeMediaStream;
    unsupportedTrack.track.readyState = 'ended';
    unsupportedTrack.track.events.get('ended')?.();
    expect(latest(unsupportedWakeLockClient).trackState).toBe('ended');
    await unsupportedWakeLockClient.end();

    const lifecycleClient = new VoiceClient();
    Reflect.set(lifecycleClient, 'snapshot', {
      ...latest(lifecycleClient),
      conversationId: 'conversation-1',
    });
    (Reflect.get(lifecycleClient, 'bindLifecycle') as (this: VoiceClient) => void).call(
      lifecycleClient,
    );
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    expect(latest(lifecycleClient).backgroundState).toBe('hidden');
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('online'));
    expect(latest(lifecycleClient).connectionState).toBe('connecting');
    await (
      Reflect.get(lifecycleClient, 'acquireWakeLock') as (this: VoiceClient) => Promise<void>
    ).call(lifecycleClient);
    await lifecycleClient.end();
  });

  it('opens a resumed socket with generation and acknowledged cursor', async () => {
    apiMock.mockResolvedValueOnce({ ticket: 'resume-ticket', websocket_path: '/api/v1/realtime' });
    const client = new VoiceClient();
    Reflect.set(client, 'snapshot', {
      ...latest(client),
      state: 'reconnecting',
      conversationId: 'conversation-1',
    });
    Reflect.set(client, 'lastServerSequence', 8);
    Reflect.set(client, 'sequence', 4);
    const connectSocket = Reflect.get(client, 'connectSocket') as (
      this: VoiceClient,
      resume: boolean,
    ) => Promise<void>;
    await connectSocket.call(client, true);
    const socket = Reflect.get(client, 'socket') as FakeWebSocket;
    expect(socket.url.searchParams.get('session_id')).toBe('conversation-1');
    expect(socket.url.searchParams.get('generation')).toBe('2');
    const sentResume = socket.sent.at(-1);
    expect(typeof sentResume).toBe('string');
    const resume = JSON.parse(sentResume as string) as Record<string, unknown>;
    expect(resume).toMatchObject({
      sequence: 5,
      type: 'session.resume',
      resume_cursor: 8,
    });
    await client.end();
  });

  it('plays PCM, handles resync and rejects invalid operations', async () => {
    const client = new VoiceClient();
    await expect(client.sendText('bez konverzace')).rejects.toThrow('není zahájena');
    Reflect.set(client, 'audioContext', new FakeAudioContext());
    const onMessage = Reflect.get(client, 'onMessage') as (
      this: VoiceClient,
      event: MessageEvent,
    ) => Promise<void>;
    await onMessage.call(
      client,
      new MessageEvent('message', { data: new Int16Array([0, 16384]).buffer }),
    );
    await onMessage.call(client, new MessageEvent('message', { data: new ArrayBuffer(0) }));
    await deliver(client, 1, 'resync.required');
    expect(latest(client).error).toContain('bezpečné obnovení');
  });

  it('covers realtime fallbacks, every state label and socket transport branches', async () => {
    const client = new VoiceClient();
    const socket = new FakeWebSocket(
      new URL('ws://localhost/realtime'),
      'kajovodagmar.realtime.v1',
    );
    Reflect.set(client, 'socket', socket);
    Reflect.set(client, 'snapshot', { ...latest(client), conversationId: 'conversation-1' });
    await client.sendText('přes websocket');
    expect(socket.sent.some((item) => typeof item === 'string' && item.includes('turn.text'))).toBe(
      true,
    );

    const states = [
      'ready',
      'connecting',
      'listening',
      'processing',
      'responding',
      'paused',
      'reconnecting',
      'error',
      'ended',
    ] as const;
    for (let index = 0; index < states.length; index += 1)
      await deliver(client, index + 1, 'state.changed', { state: states[index] });
    await deliver(client, 10, 'assistant.text', { text: 'Bez identifikátoru', actions: 'invalid' });
    expect(latest(client).transcript.at(-1)?.id).toBe('event-10');
    await deliver(client, 11, 'error', {});
    expect(latest(client).error).toBe('Hlasová komunikace selhala.');
    await deliver(client, 12, 'state.changed', { state: 'listening' });
    expect(latest(client)).toMatchObject({
      state: 'listening',
      error: 'Hlasová komunikace selhala.',
    });

    Reflect.set(client, 'snapshot', {
      ...latest(client),
      state: 'ended',
      microphoneActive: false,
    });
    expect(latest(client).state).toBe('ended');
    expect(latest(client).microphoneActive).toBe(false);
  });

  it('treats no-op controls and playback edge cases safely', async () => {
    const client = new VoiceClient();
    await client.pause();
    await client.resume();
    const playNext = Reflect.get(client, 'playNext') as (this: VoiceClient) => void;
    const stopPlayback = Reflect.get(client, 'stopPlayback') as (this: VoiceClient) => void;
    playNext.call(client);
    Reflect.set(client, 'audioContext', new FakeAudioContext());
    playNext.call(client);
    Reflect.set(client, 'playingSource', {
      stop: () => {
        throw new Error('already stopped');
      },
    });
    expect(() => stopPlayback.call(client)).not.toThrow();
    await client.end();
  });

  it('refuses microphone access on an insecure non-local origin', async () => {
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
    const original = window.location;
    Reflect.deleteProperty(window, 'location');
    Object.defineProperty(window, 'location', {
      value: { ...original, hostname: 'example.test' },
      configurable: true,
    });
    const client = new VoiceClient();
    await client.start();
    expect(latest(client).error).toContain('HTTPS');
  });
});
