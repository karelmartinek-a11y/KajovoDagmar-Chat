import { FormEvent, useEffect, useMemo, useState } from 'react';
import type { VoiceSnapshot } from '../../audio/VoiceClient';
import { getVoiceClient } from '../../audio/voiceSession';
import { Orb } from './Orb';
import { Feedback } from '../../components/Feedback';
import './chat.css';

function displayValue(value: unknown): string | null {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : null;
}

export function ChatPage() {
  const client = useMemo(() => getVoiceClient(), []);
  const [snapshot, setSnapshot] = useState<VoiceSnapshot>(initialSnapshot);
  const [text, setText] = useState('');
  const [textBusy, setTextBusy] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);
  const [interruptionRequested, setInterruptionRequested] = useState(false);
  useEffect(() => client.subscribe(setSnapshot), [client]);

  async function mainAction() {
    if (snapshot.state === 'ready' || snapshot.state === 'ended' || snapshot.state === 'error')
      await client.start();
    else if (snapshot.state === 'listening') client.finishTurn();
    else if (snapshot.state === 'responding') client.interrupt();
  }
  async function submitText(event: FormEvent) {
    event.preventDefault();
    const draft = text.trim();
    if (
      !draft ||
      textBusy ||
      ['processing', 'reconnecting'].includes(snapshot.state) ||
      (snapshot.state === 'responding' && !interruptionRequested)
    )
      return;
    setTextBusy(true);
    setTextError(null);
    try {
      if (!snapshot.conversationId) await client.startAndSendText(draft);
      else await client.sendText(draft);
      setText('');
    } catch (error) {
      setTextError(error instanceof Error ? error.message : 'Zprávu se nepodařilo odeslat.');
    } finally {
      setTextBusy(false);
    }
  }

  return (
    <section className="chat-page" aria-labelledby="chat-title">
      <header className="page-header">
        <h1 id="chat-title">Chat</h1>
        <p className="muted">Přirozený hlasový a textový rozhovor s KájovoDagmar.</p>
      </header>
      {snapshot.error && <Feedback kind="error">{snapshot.error}</Feedback>}
      {textError && <Feedback kind="error">{textError}</Feedback>}
      <div className="chat-grid">
        <section className="panel voice-panel" aria-label="Hlasová komunikace">
          <Orb state={snapshot.state} onActivate={() => void mainAction()} />
          <div className="status voice-status" aria-live="polite">
            <strong>{snapshot.stateMessage}</strong>
            <span>{microphoneMessage(snapshot)}</span>
            <span>Stav spojení: {connectionMessage(snapshot.connectionState)}</span>
            {snapshot.wakeLockState === 'acquired' && (
              <span>Obrazovka zůstane během rozhovoru zapnutá</span>
            )}
            {snapshot.wakeLockState === 'blocked' && (
              <span>Telefon nepovolil udržení obrazovky</span>
            )}
          </div>
          <div className="row controls">
            {(snapshot.state === 'ready' ||
              snapshot.state === 'ended' ||
              snapshot.state === 'error') && (
              <button className="primary" onClick={() => void client.start()}>
                Zahájit rozhovor
              </button>
            )}
            {snapshot.state === 'listening' && (
              <>
                <button className="primary" onClick={() => client.finishTurn()}>
                  Dokončit repliku
                </button>
                <button onClick={() => void client.pause()}>Pozastavit mikrofon</button>
              </>
            )}
            {snapshot.state === 'paused' && (
              <button className="primary" onClick={() => void client.resume()}>
                Obnovit mikrofon
              </button>
            )}
            {snapshot.audioRetryAvailable && snapshot.state !== 'paused' && (
              <button className="primary" onClick={() => client.retrySpeech()}>
                Zkusit přehrát hlas znovu
              </button>
            )}
            {snapshot.state === 'responding' && (
              <button
                onClick={() => {
                  setInterruptionRequested(true);
                  client.interrupt();
                }}
              >
                Přerušit odpověď
              </button>
            )}
            {snapshot.conversationId && (
              <button className="danger" onClick={() => void client.end()}>
                Ukončit rozhovor
              </button>
            )}
          </div>
          <div className="quick-settings" aria-label="Aktivní nastavení">
            <span>Jazyk: čeština</span>
            <span>Hlas: dle Nastavení</span>
            <span>Stručnost: dle Nastavení</span>
          </div>
        </section>
        <section className="panel transcript-panel" aria-label="Průběžný přepis">
          <h2>Přepis</h2>
          <div className="transcript" role="log" aria-live="polite">
            {snapshot.transcript.length === 0 && !snapshot.partialTranscript && (
              <div className="empty-state">
                <p>Zatím zde není žádná replika.</p>
                <span>Začněte hlasem nebo napište zprávu.</span>
              </div>
            )}
            {snapshot.transcript.map((item) => (
              <article key={item.id} className={`message ${item.role}`}>
                <strong>{item.role === 'user' ? 'Karel' : 'KájovoDagmar'}</strong>
                <p>{item.text}</p>
                {item.interrupted && <small>Odpověď byla přerušena.</small>}
              </article>
            ))}
            {snapshot.partialTranscript && (
              <article className="message user partial">
                <strong>Průběžný přepis</strong>
                <p>{snapshot.partialTranscript}</p>
              </article>
            )}
            {snapshot.actions
              .filter((action) => action.state === 'pending_confirmation')
              .map((action) => (
                <article
                  key={action.id}
                  className="action-proposal"
                  aria-label="Potvrzení navržené operace"
                >
                  <strong>Vyžaduje potvrzení</strong>
                  <p>{displayValue(action.preview.operation) ?? 'Navržená změna'}</p>
                  {displayValue(action.preview.content) && (
                    <p>{displayValue(action.preview.content)}</p>
                  )}
                  {displayValue(action.preview.target) && (
                    <p>Cíl: {displayValue(action.preview.target)}</p>
                  )}
                  {displayValue(action.preview.impact) && (
                    <small>{displayValue(action.preview.impact)}</small>
                  )}
                  <button
                    className="primary"
                    onClick={() => void client.confirmAction(action.id, action.version)}
                  >
                    Potvrdit operaci
                  </button>
                </article>
              ))}
            {snapshot.actions
              .filter((action) => action.state === 'completed')
              .map((action) => (
                <Feedback key={action.id} kind="success">
                  Operace byla bezpečně dokončena.
                </Feedback>
              ))}
          </div>
          <form className="text-entry" onSubmit={(event) => void submitText(event)}>
            <label className="sr-only" htmlFor="chat-text">
              Textová zpráva
            </label>
            <textarea
              id="chat-text"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Napište zprávu…"
            />
            <button
              className="primary"
              disabled={
                !text.trim() ||
                textBusy ||
                ['processing', 'reconnecting'].includes(snapshot.state) ||
                (snapshot.state === 'responding' && !interruptionRequested)
              }
            >
              Odeslat zprávu
            </button>
          </form>
        </section>
      </div>
    </section>
  );
}

const initialSnapshot: VoiceSnapshot = {
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

function microphoneMessage(snapshot: VoiceSnapshot): string {
  if (snapshot.backgroundState !== 'foreground')
    return 'Rozhovor pokračuje, mikrofon může být systémem pozastaven';
  if (snapshot.permissionState === 'denied') return 'Povolte mikrofon v nastavení prohlížeče';
  if (snapshot.deviceState === 'missing') return 'Mikrofon nebyl nalezen';
  if (snapshot.trackState === 'muted_by_system' || snapshot.audioContextState === 'interrupted')
    return 'Telefon dočasně pozastavil mikrofon';
  if (snapshot.captureState === 'paused_by_user') return 'Mikrofon je pozastavený';
  if (snapshot.microphoneActive) return 'Mikrofon naslouchá';
  if (snapshot.turnState === 'speaking') return 'Dagmar odpovídá – mikrofon zůstává připravený';
  if (snapshot.trackState === 'live') return 'Mikrofon je připravený – právě čekám na odpověď';
  if (snapshot.captureState === 'recovering') return 'Obnovuji mikrofon a hlasové spojení';
  return 'Klepnutím obnovte mikrofon';
}

function connectionMessage(state: VoiceSnapshot['connectionState']): string {
  return {
    connected: 'připojeno',
    connecting: 'připojování',
    reconnecting: 'obnovuje se',
    offline: 'offline',
    disconnected: 'odpojeno',
  }[state];
}
