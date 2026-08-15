import { FormEvent, useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client';
import { Feedback } from '../../components/Feedback';
import './history.css';

type Conversation = {
  id: string;
  state: string;
  title: string | null;
  summary: string | null;
  started_at: string;
  last_activity_at: string;
  message_count: number;
  version: number;
  deleted_at: string | null;
  purge_after: string | null;
};
type Message = {
  id: string;
  sequence: number;
  role: 'user' | 'assistant';
  content: string;
  status: string;
  interrupted: boolean;
  created_at: string;
};

export function HistoryPage() {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<{
    conversation: Conversation;
    messages: Message[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editSummary, setEditSummary] = useState('');
  const [deleteArmed, setDeleteArmed] = useState(false);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ items: Conversation[] }>('/history/search', {
        method: 'POST',
        body: JSON.stringify({
          query,
          states: ['completed', 'interrupted', 'recovered'],
          limit: 50,
          offset: 0,
        }),
      });
      setItems(result.items);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Historii se nepodařilo načíst.');
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void search();
  }, []);

  async function open(id: string) {
    setBusy(true);
    setError(null);
    try {
      setSelected(await api(`/history/${id}`));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Detail se nepodařilo načíst.');
    } finally {
      setBusy(false);
    }
  }

  async function saveMetadata() {
    if (!selected) return;
    setError(null);
    try {
      const updated = await api<Conversation>(`/history/${selected.conversation.id}/metadata`, {
        method: 'PUT',
        body: JSON.stringify({
          expected_version: selected.conversation.version,
          title: editTitle.trim(),
          summary: editSummary.trim(),
        }),
      });
      setSelected({ ...selected, conversation: updated });
      setEditing(false);
      await search();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Metadata se nepodařilo uložit.');
    }
  }

  async function remove() {
    if (!selected) return;
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    setError(null);
    try {
      const updated = await api<Conversation>(`/history/${selected.conversation.id}`, {
        method: 'DELETE',
        body: JSON.stringify({ expected_version: selected.conversation.version }),
      });
      setSelected({ ...selected, conversation: updated });
      setDeleteArmed(false);
      await search();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Konverzaci se nepodařilo odstranit.');
    }
  }

  return (
    <section className="stack" aria-labelledby="history-title">
      <header className="page-header">
        <h1 id="history-title">Historie</h1>
        <p className="muted">
          Chronologický přehled potvrzených rozhovorů. Hledání vždy začíná globálně.
        </p>
      </header>
      {error && <Feedback kind="error">{error}</Feedback>}
      <form className="panel history-search" onSubmit={(e) => void search(e)}>
        <label>
          Hledat v celé historii
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Téma, slovo nebo obsah rozhovoru"
          />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? 'Hledám…' : 'Hledat globálně'}
        </button>
      </form>
      <div className="history-layout">
        <section className="panel history-list" aria-label="Seznam konverzací">
          <h2>Konverzace</h2>
          {items.length === 0 ? (
            <div className="empty-state">
              <p>Žádná konverzace neodpovídá hledání.</p>
              <button
                onClick={() => {
                  setQuery('');
                  void search();
                }}
              >
                Zrušit filtry
              </button>
            </div>
          ) : (
            items.map((item) => (
              <button
                key={item.id}
                className={`history-item ${selected?.conversation.id === item.id ? 'selected' : ''}`}
                onClick={() => void open(item.id)}
              >
                <strong>{item.title ?? 'Rozhovor bez názvu'}</strong>
                <span>{new Date(item.last_activity_at).toLocaleString('cs-CZ')}</span>
                <small>{item.summary ?? `${item.message_count} replik`}</small>
                <em>{labelState(item.state)}</em>
              </button>
            ))
          )}
        </section>
        <section className="panel history-detail" aria-label="Detail konverzace">
          {!selected ? (
            <div className="empty-state">Vyberte konverzaci pro zobrazení úplného kontextu.</div>
          ) : (
            <>
              <header>
                <h2>{selected.conversation.title ?? 'Rozhovor bez názvu'}</h2>
                {editing ? (
                  <form
                    className="stack"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void saveMetadata();
                    }}
                  >
                    <label>
                      Název
                      <input
                        value={editTitle}
                        onChange={(event) => setEditTitle(event.target.value)}
                        required
                      />
                    </label>
                    <label>
                      Shrnutí
                      <textarea
                        value={editSummary}
                        onChange={(event) => setEditSummary(event.target.value)}
                        required
                      />
                    </label>
                    <div className="row">
                      <button className="primary">Uložit</button>
                      <button type="button" onClick={() => setEditing(false)}>
                        Zrušit
                      </button>
                    </div>
                  </form>
                ) : (
                  <p>{selected.conversation.summary ?? 'Shrnutí zatím není dostupné.'}</p>
                )}
                <div className="row">
                  {!editing && (
                    <button
                      onClick={() => {
                        setEditTitle(selected.conversation.title ?? '');
                        setEditSummary(selected.conversation.summary ?? '');
                        setEditing(true);
                      }}
                    >
                      Upravit název a shrnutí
                    </button>
                  )}
                  <button
                    onClick={() =>
                      void api(`/history/${selected.conversation.id}/continue`, {
                        method: 'POST',
                      }).then(() => {
                        location.href = '/chat';
                      })
                    }
                  >
                    Navázat novým rozhovorem
                  </button>
                  <button className="danger" onClick={() => void remove()}>
                    {deleteArmed
                      ? 'Klikněte znovu pro definitivní odstranění'
                      : 'Odstranit konverzaci'}
                  </button>
                </div>
              </header>
              <div className="history-transcript">
                {selected.messages.map((message) => (
                  <article key={message.id} className={`message ${message.role}`}>
                    <strong>{message.role === 'user' ? 'Karel' : 'KájovoDagmar'}</strong>
                    <time>{new Date(message.created_at).toLocaleString('cs-CZ')}</time>
                    <p>{message.content}</p>
                    {message.interrupted && <small>Hlasová odpověď byla přerušena.</small>}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}

function labelState(state: string): string {
  return (
    (
      {
        completed: 'Dokončeno',
        interrupted: 'Nedokončeno po výpadku',
        recovered: 'Obnoveno',
        deleted: 'Odstraněno',
        active: 'Probíhá',
      } as Record<string, string>
    )[state] ?? state
  );
}
