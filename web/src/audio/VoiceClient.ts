import { api } from '../api/client';
import {
  transition,
  type AudioContextState,
  type BackgroundState,
  type CaptureState,
  type ConnectionState,
  type DeviceState,
  type PermissionState,
  type TrackState,
  type TurnState,
  type VoiceState,
} from './voiceState';

export type TranscriptItem = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  final: boolean;
  interrupted?: boolean;
};
export type ActionProposal = {
  id: string;
  name: string;
  state: string;
  preview: Record<string, unknown>;
  expires_at?: string | null;
  version: number;
  result?: Record<string, unknown> | null;
  error_code?: string | null;
};
export type VoiceSnapshot = {
  state: VoiceState;
  stateMessage: string;
  transcript: TranscriptItem[];
  partialTranscript: string;
  error: string | null;
  microphoneActive: boolean;
  permissionState: PermissionState;
  deviceState: DeviceState;
  trackState: TrackState;
  captureState: CaptureState;
  audioContextState: AudioContextState;
  connectionState: ConnectionState;
  turnState: TurnState;
  backgroundState: BackgroundState;
  wakeLockState: 'unsupported' | 'released' | 'acquired' | 'blocked';
  lastAudioFrameAt: number | null;
  audioRetryAvailable: boolean;
  conversationId: string | null;
  actions: ActionProposal[];
};

export const emptyVoiceSnapshot: VoiceSnapshot = {
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

type ServerEvent = {
  version: '1.0';
  event_id: string;
  sequence: number;
  type: string;
  conversation_id?: string;
  payload: Record<string, unknown>;
  ack_for?: string;
};

type Listener = (snapshot: VoiceSnapshot) => void;

const AUDIO_FRAME_BYTES = 960;
const AUDIO_PACKET_BYTES = 976;
const AUDIO_SOFT_BACKPRESSURE_BYTES = 48_000;
const AUDIO_HARD_BACKPRESSURE_BYTES = 96_000;

function uuid(): string {
  return crypto.randomUUID();
}

export class VoiceClient {
  private socket: WebSocket | null = null;
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private recorder: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private gain: GainNode | null = null;
  private sequence = 0;
  private lastServerSequence = 0;
  private frameSequence = 0;
  private generation = 1;
  private reconnectAttempts = 0;
  private reconnectTimer: number | null = null;
  private ending = false;
  private lifecycleBound = false;
  private wakeLock: WakeLockSentinel | null = null;
  private lastAudioFrameAt = 0;
  private language = 'cs';
  private listeners = new Set<Listener>();
  private playbackQueue: AudioBuffer[] = [];
  private lastAssistantText: string | null = null;
  private playingSource: AudioBufferSourceNode | null = null;
  private snapshot: VoiceSnapshot = { ...emptyVoiceSnapshot };

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.snapshot);
    return () => this.listeners.delete(listener);
  }

  private update(patch: Partial<VoiceSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener(this.snapshot));
  }

  private setMicrophoneState(patch: Partial<VoiceSnapshot> = {}): void {
    const track = this.mediaStream?.getAudioTracks()[0];
    const contextRunning = this.audioContext?.state === 'running';
    const recentFrame =
      this.lastAudioFrameAt > 0 && performance.now() - this.lastAudioFrameAt < 1500;
    const captureState = patch.captureState ?? this.snapshot.captureState;
    const actuallyReceiving = Boolean(
      track &&
        track.readyState === 'live' &&
        track.enabled &&
        !track.muted &&
        contextRunning &&
        recentFrame &&
        captureState === 'capturing',
    );
    this.update({ microphoneActive: actuallyReceiving, ...patch });
  }

  private publishTrackState(track: MediaStreamTrack): void {
    const trackState: TrackState =
      track.readyState === 'ended'
        ? 'ended'
        : !track.enabled
          ? 'disabled_by_app'
          : track.muted
            ? 'muted_by_system'
            : 'live';
    this.setMicrophoneState({
      trackState,
      deviceState: trackState === 'ended' ? 'changed' : 'available',
      captureState: trackState === 'live' ? this.snapshot.captureState : 'temporarily_suspended',
      audioRetryAvailable: trackState !== 'live',
    });
  }

  private bindTrack(track: MediaStreamTrack): void {
    if (typeof track.addEventListener === 'function')
      ['mute', 'unmute', 'ended'].forEach((event) => {
        track.addEventListener(event, () => this.publishTrackState(track));
      });
    this.publishTrackState(track);
  }

  private bindLifecycle(): void {
    if (this.lifecycleBound) return;
    this.lifecycleBound = true;
    const restore = () => void this.restoreAfterVisibility();
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.update({ backgroundState: 'hidden' });
      } else {
        this.update({ backgroundState: 'restoring' });
        restore();
      }
    });
    window.addEventListener('focus', restore);
    window.addEventListener('online', () => {
      this.update({ connectionState: 'connecting' });
      if (this.snapshot.conversationId && this.socket?.readyState !== WebSocket.OPEN)
        this.scheduleReconnect();
    });
    window.addEventListener('offline', () => this.update({ connectionState: 'offline' }));
    window.addEventListener('pageshow', restore);
    window.addEventListener('pagehide', () => this.update({ backgroundState: 'hidden' }));
    document.addEventListener('freeze', () => this.update({ backgroundState: 'frozen' }));
    document.addEventListener('resume', restore);
    navigator.mediaDevices?.addEventListener?.('devicechange', () => {
      this.update({ deviceState: 'changed' });
    });
  }

  private async restoreAfterVisibility(): Promise<void> {
    if (this.ending) return;
    this.update({ backgroundState: 'restoring' });
    if (this.audioContext && this.audioContext.state !== 'running') await this.resumeAudioContext();
    if (this.snapshot.conversationId && this.socket?.readyState !== WebSocket.OPEN)
      this.scheduleReconnect();
    const track = this.mediaStream?.getAudioTracks()[0];
    if (track) this.publishTrackState(track);
    await this.acquireWakeLock();
    this.update({ backgroundState: document.hidden ? 'hidden' : 'foreground' });
  }

  private async resumeAudioContext(): Promise<void> {
    if (!this.audioContext) return;
    try {
      await this.audioContext.resume();
      const state = this.audioContext.state as AudioContextState;
      this.update({ audioContextState: state });
      if (state !== 'running') this.update({ audioRetryAvailable: true });
      this.setMicrophoneState();
    } catch {
      this.update({
        audioContextState: 'interrupted',
        audioRetryAvailable: true,
        microphoneActive: false,
      });
    }
  }

  private async acquireWakeLock(): Promise<void> {
    if (!('wakeLock' in navigator) || document.hidden || !this.snapshot.conversationId) {
      if (!('wakeLock' in navigator)) this.update({ wakeLockState: 'unsupported' });
      return;
    }
    try {
      this.wakeLock = await navigator.wakeLock.request('screen');
      this.update({ wakeLockState: 'acquired' });
      this.wakeLock.addEventListener('release', () => {
        this.wakeLock = null;
        this.update({ wakeLockState: 'released' });
      });
    } catch {
      this.update({ wakeLockState: 'blocked' });
    }
  }

  private async releaseWakeLock(): Promise<void> {
    await this.wakeLock?.release().catch(() => undefined);
    this.wakeLock = null;
    this.update({ wakeLockState: 'released' });
  }

  private move(next: VoiceState, message: string): void {
    try {
      this.update({
        state: transition(this.snapshot.state, next),
        stateMessage: message,
      });
    } catch {
      this.update({ state: next, stateMessage: message });
    }
  }

  async start(language = 'cs', continuationOfId?: string): Promise<void> {
    try {
      if (!window.isSecureContext && location.hostname !== 'localhost')
        throw new Error('Mikrofon vyžaduje zabezpečené HTTPS připojení.');
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error('Tento prohlížeč nepodporuje mikrofon.');
      this.update({ error: null, captureState: 'requesting', permissionState: 'prompt' });
      this.move('connecting', 'Připojuji hlasovou komunikaci');
      this.ending = false;
      this.language = language;
      this.mediaStream ??= await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
        video: false,
      });
      const track = this.mediaStream.getAudioTracks()[0];
      if (!track) throw new Error('Mikrofon nebyl nalezen.');
      this.update({ permissionState: 'granted', deviceState: 'available', trackState: 'live' });
      this.bindTrack(track);
      this.audioContext ??= new AudioContext({ latencyHint: 'interactive' });
      this.update({ audioContextState: this.audioContext.state });
      this.audioContext.onstatechange = () => {
        this.update({ audioContextState: this.audioContext?.state as AudioContextState });
        this.setMicrophoneState();
      };
      await this.audioContext.audioWorklet.addModule(
        new URL('./recorder.worklet.js', import.meta.url),
      );
      this.source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.recorder = new AudioWorkletNode(this.audioContext, 'kajovodagmar-recorder', {
        numberOfInputs: 1,
        numberOfOutputs: 0,
      });
      this.recorder.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (this.socket?.readyState !== WebSocket.OPEN || this.snapshot.state !== 'listening')
          return;
        const buffered = this.socket.bufferedAmount ?? 0;
        if (buffered >= AUDIO_HARD_BACKPRESSURE_BYTES) {
          this.mediaStream?.getAudioTracks().forEach((track) => {
            track.enabled = false;
          });
          this.move('paused', 'Mikrofon byl bezpečně pozastaven kvůli pomalému spojení');
          this.update({ microphoneActive: false });
          return;
        }
        if (buffered >= AUDIO_SOFT_BACKPRESSURE_BYTES)
          this.update({ stateMessage: 'Spojení je pomalé, čekám na potvrzení zvuku' });
        const pcm = event.data;
        if (pcm.byteLength !== AUDIO_FRAME_BYTES) {
          this.fail('Mikrofon vytvořil neplatný zvukový rámec.');
          return;
        }
        this.frameSequence += 1;
        this.lastAudioFrameAt = performance.now();
        this.setMicrophoneState({
          lastAudioFrameAt: this.lastAudioFrameAt,
          captureState: 'capturing',
        });
        const packet = new ArrayBuffer(AUDIO_PACKET_BYTES);
        const header = new DataView(packet);
        header.setUint8(0, 0x4b);
        header.setUint8(1, 0x44);
        header.setUint8(2, 0x56);
        header.setUint8(3, 0x31);
        header.setUint32(4, this.frameSequence);
        header.setFloat64(8, performance.now());
        new Uint8Array(packet, 16).set(new Uint8Array(pcm));
        this.socket.send(packet);
      };
      this.source.connect(this.recorder);
      this.bindLifecycle();
      await this.acquireWakeLock();
      await this.connectSocket(false, continuationOfId);
      await this.waitForConversation();
    } catch (error) {
      this.stopPlayback();
      this.recorder?.disconnect();
      this.source?.disconnect();
      this.mediaStream?.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
      this.recorder = null;
      this.source = null;
      this.socket?.close(1000, 'start_failed');
      this.socket = null;
      const name = error instanceof DOMException ? error.name : '';
      const message =
        name === 'NotAllowedError' || name === 'SecurityError'
          ? 'Povolte mikrofon v nastavení prohlížeče.'
          : name === 'NotFoundError'
            ? 'Mikrofon nebyl nalezen.'
            : name === 'NotReadableError' || name === 'AbortError'
              ? 'Mikrofon je právě používán jinou aplikací.'
              : name === 'OverconstrainedError'
                ? 'Nastavení mikrofonu není v tomto zařízení dostupné.'
                : error instanceof Error
                  ? error.message
                  : 'Mikrofon se nepodařilo připravit.';
      this.update({
        error: message,
        captureState: 'failed',
        permissionState: name === 'NotAllowedError' ? 'denied' : this.snapshot.permissionState,
        microphoneActive: false,
      });
      this.move('error', 'Vyžaduje pozornost');
    }
  }

  private async connectSocket(resume: boolean, continuationOfId?: string): Promise<void> {
    const ticket = await api<{ ticket: string; websocket_path: string }>('/realtime/ticket', {
      method: 'POST',
    });
    const url = new URL(ticket.websocket_path, location.origin);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    url.searchParams.set('ticket', ticket.ticket);
    if (resume && this.snapshot.conversationId) {
      this.generation += 1;
      url.searchParams.set('session_id', this.snapshot.conversationId);
      url.searchParams.set('generation', String(this.generation));
      url.searchParams.set('cursor', String(this.lastServerSequence));
    }
    const socket = new WebSocket(url, 'kajovodagmar.realtime.v1');
    this.socket = socket;
    socket.binaryType = 'arraybuffer';
    socket.onmessage = (event) => void this.onMessage(event);
    socket.onclose = () => {
      if (this.socket !== socket || this.ending) return;
      this.stopPlayback();
      this.mediaStream?.getAudioTracks().forEach((track) => {
        track.enabled = false;
      });
      if (!['ended', 'ready'].includes(this.snapshot.state)) {
        this.move('reconnecting', 'Spojení bylo přerušeno, obnovuji relaci');
        this.scheduleReconnect();
      }
      this.update({
        microphoneActive: false,
        connectionState: 'reconnecting',
        captureState: 'temporarily_suspended',
      });
    };
    socket.onerror = () => this.fail('Hlasové spojení se nepodařilo navázat.');
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(
        () => reject(new Error('Navázání hlasového spojení překročilo časový limit.')),
        10000,
      );
      socket.onopen = () => {
        window.clearTimeout(timeout);
        resolve();
      };
    });
    this.update({ connectionState: 'connected' });
    if (resume) {
      this.sequence += 1;
      socket.send(
        JSON.stringify({
          version: '1.0',
          event_id: uuid(),
          sequence: this.sequence,
          type: 'session.resume',
          conversation_id: this.snapshot.conversationId,
          resume_cursor: this.lastServerSequence,
          payload: { generation: this.generation },
        }),
      );
    } else {
      this.send('session.start', { language: this.language, continuation_of_id: continuationOfId });
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.ending || !this.snapshot.conversationId) return;
    const delay = Math.min(500 * 2 ** this.reconnectAttempts, 4000);
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectAttempts += 1;
      void this.connectSocket(true)
        .then(() => {
          this.reconnectAttempts = 0;
        })
        .catch(() => {
          if (this.reconnectAttempts >= 5)
            this.fail('Hlasovou relaci se nepodařilo bezpečně obnovit.');
          else this.scheduleReconnect();
        });
    }, delay);
  }

  async startAndSendText(text: string, language = this.language): Promise<void> {
    if (!this.snapshot.conversationId) {
      const conversation = await api<{ id: string }>('/conversations', {
        method: 'POST',
        body: JSON.stringify({ input_mode: 'text', language }),
      });
      this.update({ conversationId: conversation.id });
    }
    await this.sendText(text);
  }

  private async waitForConversation(): Promise<void> {
    const startedAt = performance.now();
    while (!this.snapshot.conversationId) {
      if (performance.now() - startedAt > 10000)
        throw new Error('Zahájení konverzace překročilo časový limit.');
      await new Promise((resolve) => window.setTimeout(resolve, 25));
    }
  }

  async pause(): Promise<void> {
    if (this.snapshot.state !== 'listening') return;
    this.send('microphone.pause', {});
    this.mediaStream?.getAudioTracks().forEach((track) => {
      track.enabled = false;
    });
    this.move('paused', 'Mikrofon je pozastaven');
    this.setMicrophoneState({ captureState: 'paused_by_user', microphoneActive: false });
  }

  async resume(): Promise<void> {
    if (!this.snapshot.conversationId) return;
    this.mediaStream?.getAudioTracks().forEach((track) => {
      track.enabled = true;
    });
    if (this.socket?.readyState === WebSocket.OPEN) this.send('microphone.resume', {});
    await this.resumeAudioContext();
    this.move('listening', 'Mikrofon se obnovuje');
    this.setMicrophoneState({ captureState: 'recovering', audioRetryAvailable: false });
  }

  finishTurn(): void {
    if (this.snapshot.state === 'listening')
      this.send('turn.audio_end', { language: this.language });
  }

  async sendText(text: string): Promise<void> {
    if (!this.snapshot.conversationId) throw new Error('Konverzace není zahájena.');
    this.update({ error: null });
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.send('turn.text', { text });
      return;
    }
    this.move('processing', 'Připravuji odpověď');
    const response = await api<{
      user: { id: string; content: string };
      assistant: { id: string; content: string };
      actions?: ActionProposal[];
    }>(`/conversations/${this.snapshot.conversationId}/turns`, {
      method: 'POST',
      body: JSON.stringify({
        idempotency_key: uuid(),
        content: text,
        input_mode: 'text',
        language: this.language,
      }),
    });
    this.update({
      transcript: [
        ...this.snapshot.transcript,
        { id: response.user.id, role: 'user', text: response.user.content, final: true },
        {
          id: response.assistant.id,
          role: 'assistant',
          text: response.assistant.content,
          final: true,
        },
      ],
      actions: [
        ...this.snapshot.actions.filter((action) => action.state === 'pending_confirmation'),
        ...(response.actions ?? []),
      ],
    });
    this.move('ready', 'Připraveno');
  }

  async confirmAction(actionId: string, expectedVersion: number): Promise<void> {
    const result = await api<ActionProposal>(`/orchestration/actions/${actionId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion }),
    });
    this.update({
      actions: this.snapshot.actions.map((action) => (action.id === actionId ? result : action)),
    });
  }

  interrupt(): void {
    this.stopPlayback();
    this.send('assistant.interrupt', {});
    this.move('listening', 'Naslouchám');
  }

  retrySpeech(): void {
    if (this.socket?.readyState !== WebSocket.OPEN || !this.lastAssistantText) return;
    this.send('assistant.audio.retry', {});
    this.update({ error: null, audioRetryAvailable: false });
  }

  async end(): Promise<void> {
    const conversationId = this.snapshot.conversationId;
    this.ending = true;
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.socket?.readyState === WebSocket.OPEN) this.send('session.end', {});
    else if (conversationId) {
      try {
        await api(`/conversations/${conversationId}/end`, {
          method: 'POST',
          body: JSON.stringify({ reason: 'user_ended' }),
        });
      } catch {
        // Always release local media resources when the server is unavailable.
      }
    }
    this.stopPlayback();
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    this.source?.disconnect();
    this.recorder?.disconnect();
    await this.audioContext?.close();
    this.socket?.close(1000, 'user_ended');
    this.socket = null;
    this.audioContext = null;
    await this.releaseWakeLock();
    this.mediaStream = null;
    this.sequence = 0;
    this.lastServerSequence = 0;
    this.frameSequence = 0;
    this.generation = 1;
    this.lastAudioFrameAt = 0;
    this.lastAssistantText = null;
    this.playbackQueue = [];
    this.move('ended', 'Rozhovor byl ukončen');
    this.update({
      error: null,
      microphoneActive: false,
      conversationId: null,
      actions: [],
      captureState: 'idle',
      trackState: 'unavailable',
      connectionState: 'disconnected',
      turnState: 'idle',
      transcript: [],
      partialTranscript: '',
      audioRetryAvailable: false,
    });
  }

  private send(type: string, payload: Record<string, unknown>): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN)
      throw new Error('Realtime spojení není dostupné.');
    this.sequence += 1;
    this.socket.send(
      JSON.stringify({
        version: '1.0',
        event_id: uuid(),
        sequence: this.sequence,
        type,
        conversation_id: this.snapshot.conversationId,
        payload,
      }),
    );
  }

  private async onMessage(event: MessageEvent): Promise<void> {
    if (event.data instanceof ArrayBuffer) {
      await this.enqueuePcm(event.data);
      return;
    }
    let message: ServerEvent;
    try {
      message = JSON.parse(String(event.data)) as ServerEvent;
    } catch {
      this.fail('Server poslal neplatnou realtime událost. Spojení bude obnoveno.');
      this.socket?.close(4002, 'invalid_json');
      return;
    }
    if (
      message.version !== '1.0' ||
      typeof message.sequence !== 'number' ||
      typeof message.type !== 'string' ||
      !message.payload ||
      typeof message.payload !== 'object'
    ) {
      this.fail('Server poslal neplatnou realtime událost. Spojení bude obnoveno.');
      return;
    }
    if (message.sequence <= this.lastServerSequence) return;
    if (message.sequence !== this.lastServerSequence + 1) {
      if (this.socket) this.socket.close(4000, 'sequence_gap');
      else this.fail('Posloupnost realtime událostí není úplná. Připojení bude obnoveno.');
      return;
    }
    this.lastServerSequence = message.sequence;
    const text = typeof message.payload.text === 'string' ? message.payload.text : '';
    switch (message.type) {
      case 'connection.ready':
        this.move('connecting', 'Spojení je připraveno');
        break;
      case 'session.started':
        this.reconnectAttempts = 0;
        this.update({
          conversationId: message.conversation_id ?? null,
          turnState: 'listening',
          captureState: 'recovering',
        });
        this.move('listening', 'Naslouchám');
        this.setMicrophoneState();
        void this.acquireWakeLock();
        break;
      case 'session.resumed':
        this.reconnectAttempts = 0;
        this.mediaStream?.getAudioTracks().forEach((track) => {
          track.enabled = true;
        });
        this.update({
          conversationId: message.conversation_id ?? this.snapshot.conversationId,
          partialTranscript:
            typeof message.payload.partial_transcript === 'string'
              ? message.payload.partial_transcript
              : '',
          captureState: 'recovering',
          audioRetryAvailable: false,
        });
        this.move(
          'listening',
          message.payload.input_incomplete
            ? 'Spojení obnoveno; přerušenou repliku prosím zopakujte'
            : 'Spojení bylo obnoveno',
        );
        break;
      case 'state.changed': {
        const next = message.payload.state as VoiceState;
        const labels: Record<VoiceState, string> = {
          ready: 'Připraveno',
          connecting: 'Připojuji',
          listening: 'Naslouchám',
          processing: 'Připravuji odpověď',
          responding: 'Odpovídám',
          paused: 'Mikrofon je pozastaven',
          reconnecting: 'Obnovuji spojení',
          error: 'Vyžaduje pozornost',
          ended: 'Rozhovor byl ukončen',
        };
        this.move(next, labels[next]);
        const turnState: TurnState =
          next === 'processing'
            ? 'thinking'
            : next === 'responding'
              ? 'speaking'
              : next === 'listening'
                ? 'listening'
                : 'idle';
        this.update({ turnState });
        this.setMicrophoneState();
        break;
      }
      case 'transcript.partial':
        this.update({ partialTranscript: text });
        break;
      case 'transcript.final':
        this.update({
          partialTranscript: '',
          transcript: [
            ...this.snapshot.transcript,
            { id: message.event_id, role: 'user', text, final: true },
          ],
        });
        break;
      case 'assistant.text': {
        const payloadMessageId = message.payload.message_id;
        const messageId =
          typeof payloadMessageId === 'string' ? payloadMessageId : String(message.event_id);
        this.lastAssistantText = text;
        const actions = Array.isArray(message.payload.actions)
          ? (message.payload.actions as ActionProposal[])
          : [];
        this.update({
          transcript: [
            ...this.snapshot.transcript,
            {
              id: messageId,
              role: 'assistant',
              text,
              final: true,
            },
          ],
          actions: [
            ...this.snapshot.actions.filter((action) => action.state === 'pending_confirmation'),
            ...actions,
          ],
        });
        this.move('responding', 'Odpovídám');
        this.update({ turnState: 'speaking' });
        break;
      }
      case 'assistant.audio.end':
        this.move('listening', 'Naslouchám');
        this.setMicrophoneState({ turnState: 'listening' });
        break;
      case 'assistant.audio.error':
        this.update({
          error: 'Textová odpověď je hotová, ale hlas se nepodařilo vytvořit.',
          audioRetryAvailable: true,
        });
        this.move('listening', 'Textová odpověď je hotová');
        break;
      case 'assistant.interrupted':
        this.move('listening', 'Naslouchám');
        break;
      case 'flow_control':
        if (message.payload.level === 'hard') {
          this.mediaStream?.getAudioTracks().forEach((track) => {
            track.enabled = false;
          });
          this.move('paused', 'Mikrofon byl pozastaven serverem kvůli toku dat');
          this.update({ microphoneActive: false });
        } else {
          this.update({ stateMessage: 'Server zpracovává zvuk pomaleji' });
        }
        break;
      case 'turn.incomplete':
        this.update({
          partialTranscript: '',
          stateMessage:
            typeof message.payload.message === 'string'
              ? message.payload.message
              : 'Přerušenou repliku prosím zopakujte.',
        });
        break;
      case 'session.ended':
        this.move('ended', 'Rozhovor byl ukončen');
        break;
      case 'resync.required':
        this.fail('Realtime spojení vyžaduje bezpečné obnovení.');
        break;
      case 'error':
        this.fail(
          typeof message.payload.message === 'string'
            ? message.payload.message
            : 'Hlasová komunikace selhala.',
        );
        break;
    }
  }

  private async enqueuePcm(data: ArrayBuffer): Promise<void> {
    if (!this.audioContext || data.byteLength === 0) return;
    if (this.audioContext.state !== 'running') {
      this.update({
        audioRetryAvailable: true,
        error: 'Přehrávání vyžaduje klepnutí pro obnovení zvuku.',
      });
      return;
    }
    const samples = new Int16Array(data);
    const buffer = this.audioContext.createBuffer(1, samples.length, 24000);
    const target = buffer.getChannelData(0);
    for (let index = 0; index < samples.length; index += 1) target[index] = samples[index]! / 32768;
    this.playbackQueue.push(buffer);
    if (!this.playingSource) this.playNext();
  }

  private playNext(): void {
    if (!this.audioContext) return;
    const buffer = this.playbackQueue.shift();
    if (!buffer) {
      this.playingSource = null;
      return;
    }
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    this.gain ??= this.audioContext.createGain();
    this.gain.connect(this.audioContext.destination);
    source.connect(this.gain);
    source.onended = () => {
      this.playingSource = null;
      this.playNext();
    };
    this.playingSource = source;
    source.start();
  }

  private stopPlayback(): void {
    this.playbackQueue = [];
    try {
      this.playingSource?.stop();
    } catch {
      /* source was already stopped */
    }
    this.playingSource = null;
  }

  private fail(message: string): void {
    this.update({ error: message, microphoneActive: false, captureState: 'failed' });
    this.move('error', 'Vyžaduje pozornost');
  }
}
