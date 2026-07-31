export type VoiceState =
  | 'ready'
  | 'connecting'
  | 'listening'
  | 'processing'
  | 'responding'
  | 'paused'
  | 'reconnecting'
  | 'error'
  | 'ended';

export type PermissionState = 'unknown' | 'prompt' | 'granted' | 'denied';
export type DeviceState = 'available' | 'missing' | 'busy' | 'changed' | 'unknown';
export type TrackState = 'live' | 'muted_by_system' | 'ended' | 'disabled_by_app' | 'unavailable';
export type CaptureState =
  | 'idle'
  | 'requesting'
  | 'capturing'
  | 'temporarily_suspended'
  | 'paused_by_user'
  | 'recovering'
  | 'failed';
export type AudioContextState = 'running' | 'suspended' | 'interrupted' | 'closed' | 'unknown';
export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'offline';
export type TurnState =
  | 'idle'
  | 'listening'
  | 'transcribing'
  | 'thinking'
  | 'speaking'
  | 'waiting_for_confirmation';
export type BackgroundState = 'foreground' | 'hidden' | 'frozen' | 'restoring';

const allowed: Record<VoiceState, readonly VoiceState[]> = {
  ready: ['connecting'],
  connecting: ['listening', 'error', 'ended'],
  listening: ['processing', 'paused', 'reconnecting', 'error', 'ended'],
  processing: ['responding', 'listening', 'paused', 'reconnecting', 'error', 'ended'],
  responding: ['listening', 'processing', 'paused', 'reconnecting', 'error', 'ended'],
  paused: ['listening', 'reconnecting', 'error', 'ended'],
  reconnecting: ['listening', 'paused', 'error', 'ended'],
  error: ['connecting', 'ready', 'ended'],
  ended: ['ready', 'connecting'],
};

export function transition(current: VoiceState, next: VoiceState): VoiceState {
  if (current === next) return current;
  if (!allowed[current].includes(next))
    throw new Error(`Nepovolený přechod hlasového stavu ${current} → ${next}`);
  return next;
}
