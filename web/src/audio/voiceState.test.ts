import { describe, expect, it } from 'vitest';
import { transition, type VoiceState } from './voiceState';

describe('voice state machine', () => {
  it('accepts the complete expected conversation path', () => {
    const path: VoiceState[] = [
      'ready',
      'connecting',
      'listening',
      'processing',
      'responding',
      'paused',
      'reconnecting',
      'listening',
      'ended',
      'ready',
    ];
    for (let index = 1; index < path.length; index += 1) {
      expect(transition(path[index - 1]!, path[index]!)).toBe(path[index]);
    }
  });

  it('keeps idempotent state and rejects an invalid transition', () => {
    expect(transition('listening', 'listening')).toBe('listening');
    expect(() => transition('ready', 'responding')).toThrow('Nepovolený přechod');
  });
});
