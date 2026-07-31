import { VoiceClient } from './VoiceClient';

// The session is application-scoped so route changes do not dispose an active call.
let activeClient: VoiceClient | null = null;

export function getVoiceClient(): VoiceClient {
  activeClient ??= new VoiceClient();
  return activeClient;
}

export async function endVoiceSession(): Promise<void> {
  await activeClient?.end();
}
