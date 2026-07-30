import type { VoiceState } from '../../audio/voiceState';
import './chat.css';

export function Orb({ state, onActivate }: { state: VoiceState; onActivate: () => void }) {
  return (
    <button
      className={`orb orb-${state}`}
      aria-label={`Stav asistentky: ${state}. Aktivovat hlavní akci.`}
      onClick={onActivate}
    >
      <span className="orb-core" aria-hidden="true" />
      <span className="orb-ring ring-one" aria-hidden="true" />
      <span className="orb-ring ring-two" aria-hidden="true" />
    </button>
  );
}
