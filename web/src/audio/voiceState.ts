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
