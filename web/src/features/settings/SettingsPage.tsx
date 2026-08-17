import { FormEvent, useEffect, useMemo, useState } from 'react';
import { api, apiBlob, apiEventStream, ApiError } from '../../api/client';
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
  choice_labels?: string[];
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
  catalog_refreshed_at?: string | null;
  catalog_state?: string;
};
type ModelOption = {
  id: string;
  external_id: string;
  display_name: string;
  recommended: boolean;
  recommendation_reason: string;
};
type ModelRoleOptions = {
  title: string;
  plain_description: string;
  more_information: string;
  recommended_model_id: string | null;
  selected_model_id: string | null;
  status: string;
  options: ModelOption[];
};
type ModelOptions = {
  policy_version: string;
  provider_verified: boolean;
  catalog_refreshed_at: string | null;
  catalog_state: string;
  roles: Record<string, ModelRoleOptions>;
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
  conversation: 'Konverzace',
  models: 'Modely a poskytovatelé',
  voice: 'Hlas a zvuk',
  memory: 'Paměť',
  history: 'Historie',
  diagnostics: 'Diagnostika',
  backups: 'Zálohování',
};

const OPENAI_BASE_URL = 'https://api.openai.com/v1';
const VOICE_LABELS: Record<string, string> = {
  marin: 'Marin – klidný a přirozený hlas',
  cedar: 'Cedar – hlubší a vyrovnaný hlas',
  coral: 'Coral – jasný a přátelský hlas',
  alloy: 'Alloy – neutrální hlas',
  echo: 'Echo – výraznější hlas',
  fable: 'Fable – měkký hlas',
  onyx: 'Onyx – pevný hlas',
  nova: 'Nova – živý hlas',
  shimmer: 'Shimmer – jemný hlas',
};

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

export function SettingsPage() {
  const [settings, setSettings] = useState<Settings>({});
  const [draft, setDraft] = useState<Settings>({});
  const [providers, setProviders] = useState<Provider[]>([]);
  const [modelOptions, setModelOptions] = useState<Record<string, ModelOptions>>({});
  const [activeArea, setActiveArea] = useState('conversation');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState({
    id: undefined as string | undefined,
    expected_version: 0,
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
  const [emailTestRecipient, setEmailTestRecipient] = useState('');
  const [backupPurpose, setBackupPurpose] = useState('');
  const [restoreCandidate, setRestoreCandidate] = useState<string | null>(null);
  const [emailState, setEmailState] = useState<Record<string, unknown>>({ configured: false });
  const [exports, setExports] = useState<ExportRecord[]>([]);
  const [operationStatus, setOperationStatus] = useState<OperationStatus | null>(null);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [backups, setBackups] = useState<BackupRecord[]>([]);
  const [auditArea, setAuditArea] = useState('');
  const [auditResult, setAuditResult] = useState('');
  const [selectedAudit, setSelectedAudit] = useState<AuditEvent | null>(null);
  const [providerBusy, setProviderBusy] = useState(false);
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [apiKeyValue, setApiKeyValue] = useState('');
  const [forensic, setForensic] = useState<{ title: string; steps: string[]; error?: string } | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

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
      const aiProviders = providerResult.items.filter((provider) => provider.provider_type !== 'smtp');
      setProviders(aiProviders);
      const primaryProvider = aiProviders[0];
      if (primaryProvider && !providerForm.api_key) {
        setProviderForm((current) => ({
          ...current,
          id: primaryProvider.id,
          expected_version: primaryProvider.version,
          display_name: primaryProvider.display_name,
          base_url: OPENAI_BASE_URL,
        }));
      }
      const optionEntries = await Promise.all(
        providerResult.items
          .filter((provider) => provider.verification_state === 'verified')
          .map(async (provider) => {
            try {
              const result = await api<ModelOptions>(`/providers/${provider.id}/model-options`);
              if (!result || !result.roles) return [provider.id, null] as const;
              return [provider.id, result] as const;
            } catch {
              return [provider.id, null] as const;
            }
          }),
      );
      setModelOptions(
        Object.fromEntries(
          optionEntries.filter((entry): entry is [string, ModelOptions] => entry[1] !== null),
        ),
      );
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
          id: providerForm.id,
          display_name: 'OpenAI',
          base_url: OPENAI_BASE_URL,
          api_key: providerForm.api_key,
          expected_version: providerForm.expected_version,
        }),
      });
      setProviderForm({ ...providerForm, api_key: '' });
      setNotice('API klíč byl uložen a ověřen proti OpenAI.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Poskytovatele se nepodařilo uložit.');
    }
  }

  async function verifyProvider(provider: Provider) {
    setProviderBusy(true);
    setForensic({ title: 'Ověřování OpenAI API klíče', steps: ['Probíhá připojení…'] });
    try {
      await api(`/providers/${provider.id}/verify`, { method: 'POST' });
      setForensic({ title: 'Ověřování OpenAI API klíče', steps: ['Skutečné ověření klíče a načtení katalogu OpenAI: hotovo'] });
      setNotice('Spojení a oprávnění OpenAI byly ověřeny.');
      await load();
    } catch (reason) {
      setForensic({ title: 'Ověřování OpenAI API klíče', steps: ['Test selhal'], error: reason instanceof ApiError ? reason.message : 'Ověření selhalo.' });
      setError(reason instanceof ApiError ? reason.message : 'Ověření poskytovatele selhalo.');
    } finally {
      setProviderBusy(false);
    }
  }

  async function revealProviderKey(provider: Provider) {
    if (!window.confirm('Opravdu chcete dočasně zobrazit uložený API klíč?')) return;
    try {
      const result = await api<{ api_key: string }>(`/providers/${provider.id}/key/reveal`, { method: 'POST' });
      setApiKeyValue(result.api_key);
      setApiKeyVisible(true);
      window.setTimeout(() => setApiKeyVisible(false), 30_000);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'API klíč se nepodařilo zobrazit.');
    }
  }

  async function revokeProviderKey(provider: Provider) {
    if (!window.confirm('Smazat uložený API klíč a zneaktivnit OpenAI?')) return;
    try {
      await api(`/providers/${provider.id}/key`, { method: 'DELETE' });
      setApiKeyValue('');
      setApiKeyVisible(false);
      setNotice('API klíč byl smazán a OpenAI je zneaktivněné.');
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'API klíč se nepodařilo smazat.');
    }
  }

  async function applyRecommended(provider: Provider) {
    try {
      const result = await api<{ options: ModelOptions }>(
        `/providers/${provider.id}/apply-recommended-models`,
        { method: 'POST' },
      );
      setNotice(
        'API klíč byl ověřen a nabídka modelů byla aktualizována. Nastavili jsme doporučenou sestavu pro rychlý a kvalitní hlasový rozhovor.',
      );
      if (result.options)
        setModelOptions((current) => ({ ...current, [provider.id]: result.options }));
      await load();
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : 'Doporučenou sestavu se nepodařilo použít.',
      );
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
    const recipient = emailTestRecipient.trim() || stringValue(emailState.sender, smtp.sender);
    if (!recipient) return;
    setForensic({ title: 'Test SMTP odesílání', steps: ['Připravuji bezpečný test…'] });
    try {
      await apiEventStream('/notifications/email/test/stream', {
        method: 'POST',
        body: JSON.stringify({ recipient }),
      }, (event) => {
        setForensic((current) => ({ title: 'Test SMTP odesílání', steps: [...(current?.steps ?? []), stringValue(event.stage, 'Neznámý krok')] }));
        if (event.delivered === false) throw new Error('SMTP server test odmítl.');
      });
      setNotice('Testovací e-mail byl skutečně předán SMTP serveru.');
      await load();
    } catch (reason) {
      setForensic({ title: 'Test SMTP odesílání', steps: ['Test selhal'], error: reason instanceof ApiError ? reason.message : 'Test doručení selhal.' });
      setError(reason instanceof ApiError ? reason.message : 'Test doručení selhal.');
    }
  }

  async function deleteEmail() {
    if (!window.confirm('Smazat celou SMTP konfiguraci včetně uloženého hesla?')) return;
    try {
      await api('/notifications/email', { method: 'DELETE' });
      setEmailState({ configured: false });
      setSmtp({ host: '', port: 587, username: '', password: '', sender: '', use_starttls: true });
      setNotice('SMTP konfigurace byla smazána.');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'SMTP konfiguraci se nepodařilo smazat.');
    }
  }

  async function previewVoice() {
    setPreviewBusy(true);
    try {
      const blob = await apiBlob('/voice/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ language: stringValue(draft.conversation?.language?.value, 'cs'), voice: stringValue(draft.voice?.voice_id?.value, 'marin') }) });
      const url = URL.createObjectURL(blob);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(url);
      setNotice('Náhled hlasu je připraven k přehrání.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Náhled hlasu selhal.');
    } finally {
      setPreviewBusy(false);
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
    const purpose = backupPurpose.trim();
    if (!purpose) return;
    try {
      await api('/operations/backups', {
        method: 'POST',
        body: JSON.stringify({ purpose, idempotency_key: crypto.randomUUID() }),
      });
      setNotice('Ruční záloha byla zařazena do chráněné provozní fronty.');
      setBackupPurpose('');
      await loadOperations();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Zálohu se nepodařilo spustit.');
    }
  }

  async function backupAction(record: BackupRecord, action: 'verify' | 'restore-test') {
    if (action === 'restore-test' && restoreCandidate !== record.id) {
      setRestoreCandidate(record.id);
      return;
    }
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
      setRestoreCandidate(null);
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
          Jediné místo běžné konfigurace aplikace. Tajné hodnoty jsou běžně maskované a odhalují se jen na výslovné potvrzení.
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
              <div className="settings-split">
                <section className="settings-subsection" aria-labelledby="openai-title">
                  <h3 id="openai-title">OpenAI API klíč</h3>
                  <p className="muted">Jeden bezpečně uložený klíč pro běžný provoz i testování aplikace.</p>
                  <div className="api-key-row">
                    <input aria-label="OpenAI API klíč" type={apiKeyVisible ? 'text' : 'password'} value={apiKeyVisible ? apiKeyValue : (providers[0]?.secret_hint ?? '')} readOnly={!apiKeyVisible} placeholder="Klíč není uložen" />
                    {providers[0]?.secret_present && <button type="button" onClick={() => { if (providers[0]) void revealProviderKey(providers[0]); }}>{apiKeyVisible ? 'Skrýt' : 'Zobrazit'}</button>}
                  </div>
                  <small>Klíč se při běžném zobrazení maskuje. Odhalení je dočasné a auditované.</small>
                  <div className="row">
                    <button className="primary" type="button" disabled={providerBusy} onClick={() => void (providers[0] ? verifyProvider(providers[0]) : undefined)}>Ověřit klíč</button>
                    {providers[0]?.secret_present && <button type="button" onClick={() => { if (providers[0]) void revokeProviderKey(providers[0]); }}>Smazat klíč</button>}
                  </div>
                </section>
                <section className="settings-subsection" aria-labelledby="models-title">
                  <h3 id="models-title">Doporučené modely</h3>
                  <p className="muted">Modely se načítají online z OpenAI a u každé role se zobrazí jen použitelné možnosti.</p>
                  <button type="button" disabled={providerBusy || !providers[0]} onClick={() => void (providers[0] ? verifyProvider(providers[0]) : undefined)}>Aktualizovat modely</button>
                </section>
              </div>
              <div className="model-explainer" role="note">
                <h3>Proč je modelů více?</h3>
                <p>
                  Dagmar nepoužívá jeden model na všechno. Jiný model rozumí obsahu rozhovoru, jiný
                  převádí váš hlas na text, jiný vytváří mluvenou odpověď a další pomáhá hledat v
                  historii a paměti. Díky tomu lze pro každou činnost vybrat model, který je
                  přesnější, rychlejší nebo hospodárnější.
                </p>
              </div>
              <p className="muted">
                Nabídky pocházejí z aktuálního katalogu ověřeného vaším API klíčem. Každá role má
                vlastní bezpečně filtrované možnosti.
              </p>
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
                    Znovu ověřit klíč a nabídku modelů
                  </button>
                  <button onClick={() => void applyRecommended(provider)}>
                    Použít doporučenou sestavu
                  </button>
                </article>
              ))}
              <form className="stack provider-form" onSubmit={(e) => void saveProvider(e)}>
                <h3>{providers[0]?.secret_present ? 'Nahradit API klíč' : 'Zadat API klíč'}</h3>
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
                  API klíč
                  <input
                    type="password"
                    value={providerForm.api_key}
                    onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                    required
                  />
                  <small>Po uložení bude dostupná pouze maskovaná informace.</small>
                </label>
                <button className="primary">Uložit nový API klíč</button>
              </form>
              {Object.entries(modelOptions).map(([providerId, options]) => (
                <div className="model-role-grid" key={providerId}>
                  {Object.entries(options.roles).map(([role, roleOptions]) => {
                    const setting = draft.models?.[role];
                    if (!setting) return null;
                    return (
                      <article className="model-role-card" key={role}>
                        <div className="row row-wrap">
                          <h3>{roleOptions.title}</h3>
                          {roleOptions.recommended_model_id && (
                            <span className="recommendation-badge">Doporučeno</span>
                          )}
                        </div>
                        <p>{roleOptions.plain_description}</p>
                        <details>
                          <summary>Více informací</summary>
                          <p>{roleOptions.more_information}</p>
                        </details>
                        <label htmlFor={`model-${providerId}-${role}`}>Vybraný model</label>
                        <select
                          id={`model-${providerId}-${role}`}
                          aria-describedby={`model-help-${providerId}-${role}`}
                          value={String(setting.value)}
                          onChange={(event) => change('models', role, event.target.value)}
                        >
                          <option value="">Nenastaveno – tato schopnost je blokována</option>
                          {roleOptions.options.map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.display_name}
                              {option.recommended ? ' · Doporučeno' : ''}
                            </option>
                          ))}
                        </select>
                        <small id={`model-help-${providerId}-${role}`}>
                          {roleOptions.options.find(
                            (option) => option.id === roleOptions.recommended_model_id,
                          )?.recommendation_reason ??
                            'Pro tuto roli není v katalogu dostupný podporovaný model.'}{' '}
                          Technický název:{' '}
                          {roleOptions.options.find((option) => option.id === String(setting.value))
                            ?.external_id ?? '—'}
                          . Změna: {effectLabel(setting.effect_boundary)}.
                        </small>
                        <span className={`capability-state ${roleOptions.status}`}>
                          {roleOptions.status === 'ready' ? 'Připraveno' : 'Chybí vhodný model'}
                        </span>
                      </article>
                    );
                  })}
                </div>
              ))}
              <section className="settings-subsection" aria-labelledby="smtp-title">
                <h3 id="smtp-title">SMTP odesílání</h3>
                <p className="muted">Samostatné nastavení odchozí pošty. SMTP není poskytovatel AI.</p>
                <form className="settings-fields" onSubmit={(e) => void saveEmail(e)}>
                  <label>SMTP server<input value={smtp.host} onChange={(e) => setSmtp({ ...smtp, host: e.target.value })} required /></label>
                  <label>Port<input type="number" min={1} max={65535} value={smtp.port} onChange={(e) => setSmtp({ ...smtp, port: Number(e.target.value) })} required /><small>465 = SSL/TLS, 587 = STARTTLS.</small></label>
                  <label>Uživatelské jméno<input value={smtp.username} onChange={(e) => setSmtp({ ...smtp, username: e.target.value })} /></label>
                  <label>Heslo SMTP<input type="password" value={smtp.password} onChange={(e) => setSmtp({ ...smtp, password: e.target.value })} /><small>Prázdné heslo zachová stávající.</small></label>
                  <label>Adresa odesílatele<input type="email" value={smtp.sender} onChange={(e) => setSmtp({ ...smtp, sender: e.target.value })} required /></label>
                  <label>Testovací příjemce<input type="email" value={emailTestRecipient} onChange={(e) => setEmailTestRecipient(e.target.value)} placeholder={stringValue(emailState.sender, smtp.sender)} /></label>
                  <div className="row"><button className="primary">Uložit SMTP</button><button type="button" onClick={() => void deleteEmail()}>Smazat</button><button type="button" disabled={!emailState.configured && !smtp.host} onClick={() => void testEmail()}>Otestovat odeslání</button></div>
                </form>
              </section>
              <button className="primary" onClick={() => void saveArea('models')}>
                Uložit výběr modelů
              </button>
              <button type="button" onClick={() => providers[0] && void applyRecommended(providers[0])} disabled={!providers[0]}>Obnovit doporučené modely</button>
            </section>
          )}
          {activeArea !== 'models' &&
            activeArea !== 'privacy' &&
            activeArea !== 'operations' && (
              <section className="panel stack">
                <h2>{areaNames[activeArea]}</h2>
                {activeArea === 'voice' ? (
                  <>
                    <div className="settings-fields">
                      {draft.voice?.voice_id && <label>Hlas Dagmar<select value={String(draft.voice.voice_id.value)} onChange={(event) => change('voice', 'voice_id', event.target.value)}>{Object.entries(VOICE_LABELS).map(([voice, label]) => <option key={voice} value={voice}>{label}</option>)}</select><small>Technické jméno: {String(draft.voice.voice_id.value)}.</small></label>}
                    </div>
                    <div className="row"><button type="button" onClick={() => void previewVoice()} disabled={previewBusy}>{previewBusy ? 'Připravuji náhled…' : 'Poslechnout vybraný hlas'}</button>{previewUrl && <audio controls src={previewUrl} aria-label="Náhled vybraného hlasu" />}</div>
                    {renderArea('voice', Object.fromEntries(Object.entries(draft.voice ?? {}).filter(([key]) => key !== 'voice_id')), change, availableModels)}
                  </>
                ) : renderArea(activeArea, draft[activeArea], change, availableModels)}
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
                    void api('/operations/status')
                      .then((status) => setNotice(JSON.stringify(status, null, 2)))
                      .catch((reason) =>
                        setError(
                          reason instanceof ApiError
                            ? reason.message
                            : 'Provozní stav se nepodařilo načíst.',
                        ),
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
                <label>
                  Účel ruční zálohy
                  <input value={backupPurpose} onChange={(e) => setBackupPurpose(e.target.value)} />
                </label>
                <button
                  className="primary"
                  onClick={() => void createBackup()}
                  disabled={!backupPurpose.trim()}
                >
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
                            {restoreCandidate === record.id
                              ? 'Klikněte znovu pro restore test'
                              : 'Obnovit izolovaně'}
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
      {forensic && (
        <div className="forensic-backdrop" role="presentation" onClick={() => setForensic(null)}>
          <section className="forensic-modal" role="dialog" aria-modal="true" aria-labelledby="forensic-title" onClick={(event) => event.stopPropagation()}>
            <div className="row"><h2 id="forensic-title">{forensic.title}</h2><button type="button" aria-label="Zavřít forenzní okno" onClick={() => setForensic(null)}>×</button></div>
            <ol>{forensic.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            <p className="muted">Citlivé údaje jsou během testu redigované. Klíče, hesla a obsah zpráv se nezobrazují.</p>
            {forensic.error && <Feedback kind="error">{forensic.error}</Feedback>}
          </section>
        </div>
      )}
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
                  {item.choice_labels?.[item.choices.indexOf(choice)] ?? choice}
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
            {item.description}{item.type === 'integer' && (key.includes('seconds') ? ' Hodnota se zadává v sekundách.' : '')}{item.minimum !== null && item.maximum !== null ? ` Povolený rozsah: ${item.minimum}–${item.maximum}.` : ''} Účinnost: {effectLabel(item.effect_boundary)}.
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
