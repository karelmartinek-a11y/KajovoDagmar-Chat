import { FormEvent, useEffect, useState } from 'react';
import { api, ApiError } from '../../api/client';
import { Feedback } from '../../components/Feedback';
import './memory.css';

type MemoryItem = {
  id: string;
  content: string;
  category: string;
  state: string;
  origin_type: string;
  event_at: string | null;
  valid_from: string | null;
  valid_until: string | null;
  created_at: string;
  updated_at: string;
  version: number;
  deleted_at: string | null;
  purge_after: string | null;
};
const categories = [
  ['personal_fact', 'Osobní fakt'],
  ['preference', 'Preference'],
  ['rule', 'Dlouhodobé pravidlo'],
  ['decision', 'Rozhodnutí'],
  ['commitment', 'Závazek'],
  ['event', 'Událost'],
  ['note', 'Poznámka'],
  ['other', 'Jiná informace'],
] as const;

export function MemoryPage() {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [selected, setSelected] = useState<MemoryItem | null>(null);
  const [newContent, setNewContent] = useState('');
  const [newCategory, setNewCategory] = useState('note');
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function search(event?: FormEvent) {
    event?.preventDefault();
    setError(null);
    try {
      const result = await api<{ items: MemoryItem[] }>('/memory/search', {
        method: 'POST',
        body: JSON.stringify({
          query,
          categories: category ? [category] : [],
          states: includeDeleted
            ? ['active', 'pending_confirmation', 'outdated', 'merged', 'deleted']
            : ['active', 'pending_confirmation', 'outdated'],
          limit: 100,
        }),
      });
      setItems(result.items);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Paměť se nepodařilo načíst.');
    }
  }
  useEffect(() => {
    void search();
  }, [includeDeleted]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await api('/memory', {
        method: 'POST',
        body: JSON.stringify({
          content: newContent,
          category: newCategory,
          origin_type: 'manual',
          keywords: [],
          confirmed: true,
        }),
      });
      setNewContent('');
      setNotice('Paměťová položka byla bezpečně uložena.');
      await search();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Položku se nepodařilo uložit.');
    }
  }

  async function edit() {
    if (!selected) return;
    const content = window.prompt('Upravený obsah paměti', selected.content)?.trim();
    if (!content || content === selected.content) return;
    try {
      const updated = await api<MemoryItem>(`/memory/${selected.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          expected_version: selected.version,
          content,
          category: selected.category,
          mark_outdated: false,
        }),
      });
      setSelected(updated);
      setNotice('Změna byla uložena jako nová auditovatelná verze.');
      await search();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Změnu se nepodařilo uložit.');
    }
  }

  async function markOutdated() {
    if (!selected) return;
    const updated = await api<MemoryItem>(`/memory/${selected.id}`, {
      method: 'PUT',
      body: JSON.stringify({ expected_version: selected.version, mark_outdated: true }),
    });
    setSelected(updated);
    await search();
  }

  async function remove() {
    if (
      !selected ||
      !window.confirm(
        `Odstranit vzpomínku „${selected.content.slice(0, 120)}“? Okamžitě se přestane používat v odpovědích.`,
      )
    )
      return;
    const updated = await api<MemoryItem>(`/memory/${selected.id}`, {
      method: 'DELETE',
      body: JSON.stringify({ expected_version: selected.version }),
    });
    setSelected(updated);
    setNotice('Položka byla odstraněna a v retenční době ji lze obnovit.');
    await search();
  }

  async function restore() {
    if (!selected) return;
    const updated = await api<MemoryItem>(`/memory/${selected.id}/restore`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: selected.version }),
    });
    setSelected(updated);
    setNotice('Položka byla obnovena do aktivní paměti.');
    await search();
  }

  return (
    <section className="stack" aria-labelledby="memory-title">
      <header className="page-header">
        <h1 id="memory-title">Paměť</h1>
        <p className="muted">
          Řízené dlouhodobé informace s původem, stavem a historií změn. Nové hledání je vždy
          globální.
        </p>
      </header>
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      <form className="panel memory-create" onSubmit={(e) => void create(e)}>
        <label>
          Nová paměťová položka
          <textarea
            rows={3}
            value={newContent}
            onChange={(e) => setNewContent(e.target.value)}
            placeholder="Jedna srozumitelná informace"
            required
          />
        </label>
        <label>
          Kategorie
          <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
            {categories.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button className="primary">Uložit do paměti</button>
      </form>
      <form className="panel memory-search" onSubmit={(e) => void search(e)}>
        <label>
          Hledat v celé paměti
          <input value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <label>
          Kategorie
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Všechny kategorie</option>
            {categories.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
          />
          Zobrazit také odstraněné
        </label>
        <button className="primary">Hledat globálně</button>
      </form>
      <div className="memory-layout">
        <section className="panel memory-list">
          <h2>Uložené informace</h2>
          {items.length === 0 ? (
            <div className="empty-state">Paměť je prázdná nebo hledání nic nenašlo.</div>
          ) : (
            items.map((item) => (
              <button
                key={item.id}
                className={selected?.id === item.id ? 'selected' : ''}
                onClick={() => setSelected(item)}
              >
                <strong>{categoryLabel(item.category)}</strong>
                <span>{item.content}</span>
                <small>
                  {stateLabel(item.state)} · {new Date(item.updated_at).toLocaleString('cs-CZ')}
                </small>
              </button>
            ))
          )}
        </section>
        <section className="panel memory-detail">
          {!selected ? (
            <div className="empty-state">
              Vyberte položku pro kontrolu původu, platnosti a dostupných operací.
            </div>
          ) : (
            <>
              <h2>{categoryLabel(selected.category)}</h2>
              <p className="memory-content">{selected.content}</p>
              <dl>
                <dt>Stav</dt>
                <dd>{stateLabel(selected.state)}</dd>
                <dt>Původ</dt>
                <dd>{originLabel(selected.origin_type)}</dd>
                <dt>Vytvořeno</dt>
                <dd>{new Date(selected.created_at).toLocaleString('cs-CZ')}</dd>
                <dt>Poslední změna</dt>
                <dd>{new Date(selected.updated_at).toLocaleString('cs-CZ')}</dd>
                <dt>Verze</dt>
                <dd>{selected.version}</dd>
              </dl>
              <div className="row">
                {selected.state !== 'deleted' && selected.state !== 'merged' && (
                  <>
                    <button onClick={() => void edit()}>Opravit obsah</button>
                    <button onClick={() => void markOutdated()}>Označit jako neaktuální</button>
                    <button className="danger" onClick={() => void remove()}>
                      Odstranit vzpomínku
                    </button>
                  </>
                )}
                {selected.state === 'deleted' && (
                  <button className="primary" onClick={() => void restore()}>
                    Obnovit vzpomínku
                  </button>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
function categoryLabel(value: string) {
  return Object.fromEntries(categories)[value] ?? 'Jiná informace';
}
function stateLabel(value: string) {
  return (
    (
      {
        active: 'Aktivní',
        pending_confirmation: 'Čeká na potvrzení',
        outdated: 'Neaktuální',
        merged: 'Sloučená',
        deleted: 'Odstraněná',
      } as Record<string, string>
    )[value] ?? value
  );
}
function originLabel(value: string) {
  return (
    (
      {
        explicit_command: 'Výslovný pokyn v rozhovoru',
        manual: 'Ruční vložení',
        assistant_suggestion: 'Potvrzený návrh asistentky',
      } as Record<string, string>
    )[value] ?? value
  );
}
