import { FormEvent, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../../api/client';
import { Feedback } from '../../components/Feedback';
import './settings.css';

type Setting = {
  value: unknown;
  version: number;
  label: string;
  description: string;
  effect_boundary: string;
  type: string;
  choices: string[];
  minimum: number | null;
  maximum: number | null;
};
type Settings = Record<string, Record<string, Setting>>;
type Model = {
  id: string;
  external_id: string;
  display_name: string;
  capabilities: Record<string, boolean>;
  available: boolean;
};
type Provider = {
  id: string;
  provider_type: string;
  display_name: string;
  base_url: string;
  enabled: boolean;
  verification_state: string;
  secret_present: boolean;
  secret_hint: string | null;
  version: number;
  models: Model[];
};
type ExportRecord = {
  id: string;
  kind: 'history' | 'memory' | 'configuration' | 'audit';
  state: string;
  format: 'json' | 'markdown';
  file_digest: string | null;
  expires_at: string | null;
  completed_at: string | null;
};
type OperationStatus = {
  checked_at: string;
  components: Record<
    string,
    {
      state: 'ready' | 'limited' | 'error' | 'unknown';
      impact: string | null;
      action: string | null;
    }
  >;
};
type AuditEvent = {
  id: number;
  occurred_at: string;
  area: string;
  event_name: string;
  actor_type: string;
  target_type: string | null;
  result: string;
  correlation_id: string | null;
  details: Record<string, unknown>;
};
type BackupRecord = {
  id: string;
  backup_type: string;
  state: string;
  started_at: string;
  completed_at: string | null;
  backup_label: string | null;
  verified_at: string | null;
  restore_tested_at: string | null;
  size_bytes: number | null;
  error_code: string | null;
  version: number;
};
const areaNames: Record<string, string> = {
  general: 'Obecné',
  conversation: 'Konverzace',
  models: 'Modely a poskytovatelé',
  voice: 'Hlas a zvuk',
  memory: 'Paměť',
  history: 'Historie',
  diagnostics: 'Diagnostika',
  backups: 'Zálohování',
};

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({});
  const [draft, setDraft] = useState<Settings>({});
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeArea, setActiveArea] = useState('general');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState({
    display_name: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    api_key: '',
  });
  const [smtp, setSmtp] = useState({
    host: '',
    port: 587,
    username: '',
    password: '',
    sender: '',
    use_starttls: true,
  });
  const [emailState, setEmailState] = useState<Record<string, unknown>>({ configured: false });
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [operationStatus, setOperationStatus] = useState<OperationStatus | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [auditArea, setAuditArea] = useState('');
  const [auditResult, setAuditResult] = useState('');
  const [selectedAudit, setSelectedAudit] = useState<AuditEvent | null>(null);

  async function load() {
    setError(null);
    try {
      const [all, providerResult, email, exportResult] = await Promise.all([
        api<Settings>('/settings'),
        api<{ items: Provider[] }>('/providers'),
        api<Record<string, unknown>>('/notifications/email'),
        api<{ items: ExportRecord[] }>('/exports'),
      ]);
      setSettings(all);
      setDraft(structuredClone(all));
      setProviders(providerResult.items);
      setEmailState(email);
      setExports(exportResult.items);
      if (email.configured)
        setSmtp({
          host: stringValue(email.host),
          port: Number(email.port ?? 587),
          username: stringValue(email.username),
          password: '',
          sender: stringValue(email.sender),
          use_starttls: Boolean(email.use_starttls ?? true),
        });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Nastavení se nepodařilo načíst.');
    }
  }
  useEffect(() => {
    void load();
  }, []);

  const availableModels = useMemo(
    () =>
      providers.flatMap((provider) =>
        provider.models
          .filter((model) => model.available)
          .map((model) => ({ ...model, provider: provider.display_name })),
      ),
    [providers],
  );

  function change(area: string, key: string, value: unknown) {
    setDraft((current) => ({
      ...current,
      [area]: { ...current[area], [key]: { ...current[area]![key]!, value } },
    }));
  }

  async function saveArea(area: string) {
    const areaDraft = draft[area];
    if (!areaDraft) return;
    const changes: Record<string, { value: unknown; version: number }> = {};
    Object.entries(areaDraft).forEach(([key, value]) => {
      const original = settings[area]?.[key];
      if (!original || JSON.stringify(original.value) !== JSON.stringify(value.value))
        changes[key] = { value: value.value, version: original?.version ?? 0 };
    });
    if (Object.keys(changes).length === 0) {
      setNotice('V této oblasti nejsou neuložené změny.');
      return;
    }
    try {
      await api(`/settings/${area}`, { method: 'PUT', body: JSON.stringify({ changes }) });
      setNotice('Nastavení bylo trvale uloženo. Účinnost jednotlivých změn je uvedena u polí.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Nastavení se nepodařilo uložit.');
    }
  }

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await api('/providers', {
        method: 'PUT',
        body: JSON.stringify({
          provider_type: 'openai',
          display_name: providerForm.display_name,
          base_url: providerForm.base_url,
          api_key: providerForm.api_key,
          expected_version: 0,
        }),
      });
      setProviderForm({ ...providerForm, api_key: '' });
      setNotice('Poskytovatel byl uložen. Před použitím proveďte skutečný test spojení.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Poskytovatele se nepodařilo uložit.');
    }
  }

  async function verifyProvider(provider: Provider) {
    try {
      await api(`/providers/${provider.id}/verify`, { method: 'POST' });
      setNotice('Spojení a oprávnění poskytovatele byly ověřeny.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Ověření poskytovatele selhalo.');
    }
  }

  async function saveEmail(event: FormEvent) {
    event.preventDefault();
    try {
      await api('/notifications/email', {
        method: 'PUT',
        body: JSON.stringify({
          display_name: 'Odchozí e-mail',
          ...smtp,
          username: smtp.username || null,
          password: smtp.password || null,
        }),
      });
      setSmtp({ ...smtp, password: '' });
      setNotice('Konfigurace e-mailu byla uložena; připravenost potvrdí až test doručení.');
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : 'Konfiguraci e-mailu se nepodařilo uložit.',
      );
    }
  }

  async function requestExport(kind: ExportRecord['kind'], format: ExportRecord['format']) {
    try {
      await api('/exports', {
        method: 'POST',
        body: JSON.stringify({ kind, format, scope: { all: true } }),
      });
      setNotice('Export byl zařazen do auditovatelné fronty. Stav se obnoví po načtení stránky.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Export se nepodařilo vytvořit.');
    }
  }

  async function testEmail() {
    const recipient = window
      .prompt('Adresa pro skutečný test doručení', stringValue(emailState.sender, smtp.sender))
      ?.trim();
    if (!recipient) return;
    try {
      await api('/notifications/email/test', {
        method: 'POST',
        body: JSON.stringify({ recipient }),
      });
      setNotice('Testovací e-mail byl skutečně předán SMTP serveru.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Test doručení selhal.');
    }
  }

  async function loadOperations() {
    setError(null);
    try {
      const parameters = new URLSearchParams();
      if (auditArea) parameters.set('area', auditArea);
      if (auditResult) parameters.set('result', auditResult);
      const query = parameters.size ? `?${parameters.toString()}` : '';
      const [status, audit, backupResult] = await Promise.all([
        api<OperationStatus>('/operations/status'),
        api<{ items: AuditEvent[] }>(`/operations/audit${query}`),
        api<{ items: BackupRecord[] }>('/operations/backups'),
      ]);
      setOperationStatus(status);
      setAuditEvents(audit.items);
      setBackups(backupResult.items);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Provozní stav se nepodařilo načíst.');
    }
  }

  async function createBackup() {
    const purpose = window.prompt('Účel ručního obnovovacího bodu')?.trim();
    if (!purpose) return;
    try {
      await api('/operations/backups', {
        method: 'POST',
        body: JSON.stringify({ purpose, idempotency_key: crypto.randomUUID() }),
      });
      setNotice('Ruční záloha byla zařazena do chráněné provozní fronty.');
      await loadOperations();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Zálohu se nepodařilo spustit.');
    }
  }

  async function backupAction(record: BackupRecord, action: 'verify' | 'restore-test') {
    if (
      action === 'restore-test' &&
      window.prompt('Pro potvrzení opište: OBNOVIT DO IZOLOVANÉHO PROSTŘEDÍ') !==
        'OBNOVIT DO IZOLOVANÉHO PROSTŘEDÍ'
    )
      return;
    try {
      await api(`/operations/backups/${record.id}/${action}`, {
        method: 'POST',
        body: JSON.stringify({
          expected_version: record.version,
          idempotency_key: crypto.randomUUID(),
          ...(action === 'restore-test'
            ? { confirmation: 'OBNOVIT DO IZOLOVANÉHO PROSTŘEDÍ' }
            : {}),
        }),
      });
      setNotice(
        action === 'verify'
          ? 'Kontrola integrity zálohy byla zařazena do fronty.'
          : 'Izolovaný restore test byl potvrzen a zařazen do fronty.',
      );
      await loadOperations();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Provozní operace selhala.');
    }
  }

  return (
    <section className="stack" aria-labelledby="settings-title">
      <header className="page-header">
        <h1 id="settings-title">Nastavení</h1>
        <p className="muted">
          Jediné místo běžné konfigurace aplikace. Tajné hodnoty se po uložení nezobrazují.
        </p>
      </header>
      {error && <Feedback kind="error">{error}</Feedback>}
      {notice && <Feedback kind="success">{notice}</Feedback>}
      <div className="settings-layout">
        <nav className="panel settings-nav" aria-label="Oblasti nastavení">
          {Object.keys(areaNames).map((area) => (
            <button
              key={area}
              className={activeArea === area ? 'active' : ''}
              onClick={() => setActiveArea(area)}
            >
              {areaNames[area]}
            </button>
          ))}
          <button
            className={activeArea === 'email' ? 'active' : ''}
            onClick={() => setActiveArea('email')}
          >
            E-mail a oznámení
          </button>
          <button
            className={activeArea === 'privacy' ? 'active' : ''}
            onClick={() => setActiveArea('privacy')}
          >
            Soukromí a data
          </button>
          <button
            className={activeArea === 'operations' ? 'active' : ''}
            onClick={() => {
              setActiveArea('operations');
              void loadOperations();
            }}
          >
            Provoz a audit
          </button>
        </nav>
        <div className="stack">
          {activeArea === 'models' && (
            <section className="panel stack">
              <h2>Modely a poskytovatelé</h2>
              <p className="muted">Model lze zvolit teprve po skutečném ověření poskytovatele.</p>
              {providers.map((provider) => (
                <article className="provider-card" key={provider.id}>
                  <div>
                    <strong>{provider.display_name}</strong>
                    <small>{provider.base_url}</small>
                  </div>
                  <span className="status">
                    {provider.verification_state === 'verified' ? 'Ověřeno' : 'Není ověřeno'}
                  </span>
                  <span>
                    {provider.secret_present
                      ? `Klíč uložen ${provider.secret_hint ?? ''}`
                      : 'Klíč chybí'}
                  </span>
                  <button onClick={() => void verifyProvider(provider)}>
                    Ověřit spojení a katalog
                  </button>
                </article>
              ))}
              <form className="stack provider-form" onSubmit={(e) => void saveProvider(e)}>
                <h3>Přidat poskytovatele</h3>
                <label>
                  Název
                  <input
                    value={providerForm.display_name}
                    onChange={(e) =>
                      setProviderForm({ ...providerForm, display_name: e.target.value })
                    }
                    required
                  />
                </label>
                <label>
                  Základní URL API
                  <input
                    type="url"
                    value={providerForm.base_url}
                    onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                    required
                  />
                </label>
                <label>
                  API klíč
                  <input
                    type="password"
                    value={providerForm.api_key}
                    onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                    required
                  />
                  <small>Po uložení bude dostupná pouze maskovaná informace.</small>
                </label>
                <button className="primary">Bezpečně uložit poskytovatele</button>
              </form>
              {renderArea('models', draft.models, change, availableModels)}
              <button className="primary" onClick={() => void saveArea('models')}>
                Uložit výběr modelů
              </button>
            </section>
          )}
          {activeArea !== 'models' &&
            activeArea !== 'email' &&
            activeArea !== 'privacy' &&
            activeArea !== 'operations' && (
              <section className="panel stack">
                <h2>{areaNames[activeArea]}</h2>
                {renderArea(activeArea, draft[activeArea], change, availableModels)}
                <div className="row">
                  <button className="primary" onClick={() => void saveArea(activeArea)}>
                    Uložit změny
                  </button>
                  <button onClick={() => setDraft(structuredClone(settings))}>
                    Zahodit neuložené změny
                  </button>
                </div>
              </section>
            )}
          {activeArea === 'email' && (
            <section className="panel stack">
              <h2>E-mail a oznámení</h2>
              <div className="status">
                {stringValue(emailState.verification_state, 'Není nastaveno')}
              </div>
              <form className="settings-fields" onSubmit={(e) => void saveEmail(e)}>
                <label>
                  SMTP server
                  <input
                    value={smtp.host}
                    onChange={(e) => setSmtp({ ...smtp, host: e.target.value })}
                    required
                  />
                </label>
                <label>
                  Port
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    value={smtp.port}
                    onChange={(e) => setSmtp({ ...smtp, port: Number(e.target.value) })}
                    required
                  />
                </label>
                <label>
                  Uživatelské jméno
                  <input
                    value={smtp.username}
                    onChange={(e) => setSmtp({ ...smtp, username: e.target.value })}
                  />
                </label>
                <label>
                  Heslo SMTP
                  <input
                    type="password"
                    value={smtp.password}
                    onChange={(e) => setSmtp({ ...smtp, password: e.target.value })}
                  />
                  <small>Prázdná hodnota ponechá stávající uložené heslo.</small>
                </label>
                <label>
                  Adresa odesílatele
                  <input
                    type="email"
                    value={smtp.sender}
                    onChange={(e) => setSmtp({ ...smtp, sender: e.target.value })}
                    required
                  />
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={smtp.use_starttls}
                    onChange={(e) => setSmtp({ ...smtp, use_starttls: e.target.checked })}
                  />
                  Použít STARTTLS
                </label>
                <button className="primary">Uložit konfiguraci</button>
                <button type="button" onClick={() => void testEmail()}>
                  Provést skutečný test doručení
                </button>
              </form>
            </section>
          )}
          {activeArea === 'privacy' && (
            <section className="panel stack">
              <h2>Soukromí a data</h2>
              <p>
                Konverzace, paměť a profil jsou soukromá data jediného administrátora. Externím
                poskytovatelům se předává pouze obsah nezbytný pro potvrzenou funkci. Surový zvuk se
                neukládá do provozních logů.
              </p>
              <div className="row">
                <button
                  onClick={() =>
                    void api('/operations/status').then((status) =>
                      setNotice(JSON.stringify(status, null, 2)),
                    )
                  }
                >
                  Načíst provozní stav
                </button>
                <button onClick={() => void requestExport('history', 'markdown')}>
                  Export historie
                </button>
                <button onClick={() => void requestExport('memory', 'json')}>Export paměti</button>
                <button onClick={() => void requestExport('configuration', 'json')}>
                  Export netajné konfigurace
                </button>
              </div>
              <h3>Exportní artefakty</h3>
              {exports.length === 0 ? (
                <div className="empty-state">Dosud nebyl vytvořen žádný export.</div>
              ) : (
                <div className="stack">
                  {exports.map((item) => (
                    <article className="provider-card" key={item.id}>
                      <div>
                        <strong>{item.kind}</strong>
                        <small>
                          {item.format} · {item.state}
                        </small>
                      </div>
                      <span>
                        {item.completed_at
                          ? new Date(item.completed_at).toLocaleString('cs-CZ')
                          : 'Čeká na dokončení'}
                      </span>
                      {item.state === 'completed' && (
                        <a className="button-link" href={`/api/v1/exports/${item.id}/download`}>
                          Bezpečně stáhnout
                        </a>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}
          {activeArea === 'operations' && (
            <section className="panel stack" aria-labelledby="operations-title">
              <div className="row">
                <div>
                  <h2 id="operations-title">Provoz, zálohy a audit</h2>
                  <p className="muted">
                    Stav schopností vychází z typovaných kontrol, nikoli z posledního textu logu.
                  </p>
                </div>
                <button onClick={() => void loadOperations()}>Obnovit stav</button>
              </div>
              <div className="operations-grid">
                {operationStatus &&
                  Object.entries(operationStatus.components).map(([name, component]) => (
                    <article className="operation-card" key={name}>
                      <div className={`capability-state ${component.state}`}>{component.state}</div>
                      <strong>{name}</strong>
                      <span>{component.impact ?? 'Schopnost je připravena.'}</span>
                      {component.action && <small>{component.action}</small>}
                    </article>
                  ))}
              </div>
              <div className="row">
                <h3>Zálohy a izolované restore testy</h3>
                <button className="primary" onClick={() => void createBackup()}>
                  Vytvořit ruční obnovovací bod
                </button>
              </div>
              {backups.length === 0 ? (
                <div className="empty-state">Dosud není evidována žádná záloha.</div>
              ) : (
                <div className="stack">
                  {backups.map((record) => (
                    <article className="backup-card" key={record.id}>
                      <div>
                        <strong>{record.backup_label ?? record.backup_type}</strong>
                        <small>
                          {new Date(record.started_at).toLocaleString('cs-CZ')} · {record.state}
                        </small>
                      </div>
                      <span>
                        {record.size_bytes ? `${record.size_bytes} B` : 'velikost neznámá'}
                      </span>
                      <span>{record.verified_at ? 'Integrita ověřena' : 'Čeká na ověření'}</span>
                      <span>
                        {record.restore_tested_at ? 'Obnova otestována' : 'Obnova netestována'}
                      </span>
                      {record.state === 'completed' && (
                        <>
                          <button onClick={() => void backupAction(record, 'verify')}>
                            Ověřit integritu
                          </button>
                          <button onClick={() => void backupAction(record, 'restore-test')}>
                            Obnovit izolovaně
                          </button>
                        </>
                      )}
                    </article>
                  ))}
                </div>
              )}
              <div className="row">
                <h3>Auditní stopa</h3>
                <button onClick={() => void requestExport('audit', 'json')}>
                  Exportovat filtrovaný audit
                </button>
              </div>
              <form
                className="audit-filters"
                onSubmit={(event) => {
                  event.preventDefault();
                  void loadOperations();
                }}
              >
                <label>
                  Oblast
                  <input value={auditArea} onChange={(event) => setAuditArea(event.target.value)} />
                </label>
                <label>
                  Výsledek
                  <select
                    value={auditResult}
                    onChange={(event) => setAuditResult(event.target.value)}
                  >
                    <option value="">Všechny výsledky</option>
                    <option value="success">Úspěch</option>
                    <option value="failure">Selhání</option>
                  </select>
                </label>
                <button>Filtrovat audit</button>
              </form>
              <div className="audit-table">
                <table aria-label="Auditní události">
                  <thead>
                    <tr>
                      <th>Čas</th>
                      <th>Oblast</th>
                      <th>Událost</th>
                      <th>Výsledek</th>
                      <th>Původce</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditEvents.map((event) => (
                      <tr key={event.id}>
                        <td>{new Date(event.occurred_at).toLocaleString('cs-CZ')}</td>
                        <td>{event.area}</td>
                        <td>{event.event_name}</td>
                        <td>{event.result}</td>
                        <td>{event.actor_type}</td>
                        <td>
                          <button
                            onClick={() => setSelectedAudit(event)}
                            aria-label={`Detail události ${event.event_name}`}
                          >
                            Otevřít
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selectedAudit && (
                <article className="audit-detail">
                  <h4>Dopad události {selectedAudit.event_name}</h4>
                  <p>
                    Akce skončila výsledkem {selectedAudit.result} a týkala se objektu{' '}
                    {selectedAudit.target_type ?? 'bez konkrétního cíle'}.
                  </p>
                  <small>Korelace: {selectedAudit.correlation_id ?? 'není k dispozici'}</small>
                  <pre>{JSON.stringify(selectedAudit.details, null, 2)}</pre>
                </article>
              )}
            </section>
          )}
        </div>
      </div>
    </section>
  );
}

function renderArea(
  area: string,
  values: Record<string, Setting> | undefined,
  change: (area: string, key: string, value: unknown) => void,
  models: Array<Model & { provider: string }>,
) {
  if (!values)
    return <div className="empty-state">Tato oblast zatím nemá žádné spravovatelné hodnoty.</div>;
  return (
    <div className="settings-fields">
      {Object.entries(values).map(([key, item]) => (
        <label key={key}>
          {item.label}
          {area === 'models' ? (
            <select value={String(item.value)} onChange={(e) => change(area, key, e.target.value)}>
              <option value="">Nenastaveno – schopnost je blokována</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.provider}: {model.display_name}
                </option>
              ))}
            </select>
          ) : item.type === 'boolean' ? (
            <span className="toggle">
              <input
                type="checkbox"
                checked={Boolean(item.value)}
                onChange={(e) => change(area, key, e.target.checked)}
              />
              {item.value ? 'Zapnuto' : 'Vypnuto'}
            </span>
          ) : item.choices?.length ? (
            <select value={String(item.value)} onChange={(e) => change(area, key, e.target.value)}>
              {item.choices.map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          ) : item.type === 'integer' ? (
            <input
              type="number"
              min={item.minimum ?? undefined}
              max={item.maximum ?? undefined}
              value={Number(item.value)}
              onChange={(e) => change(area, key, Number(e.target.value))}
            />
          ) : (
            <input value={String(item.value)} onChange={(e) => change(area, key, e.target.value)} />
          )}
          <small>
            {item.description} Účinnost: {effectLabel(item.effect_boundary)}.
          </small>
        </label>
      ))}
    </div>
  );
}
function effectLabel(value: string) {
  return (
    (
      {
        immediate: 'okamžitě',
        next_turn: 'od další repliky',
        new_voice_session: 'od nové hlasové relace',
        next_login: 'od dalšího přihlášení',
        service_restart: 'po řízeném restartu služby',
      } as Record<string, string>
    )[value] ?? value
  );
}
