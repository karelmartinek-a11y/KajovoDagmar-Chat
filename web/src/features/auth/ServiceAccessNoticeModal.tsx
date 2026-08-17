import { useState } from 'react';
import { api } from '../../api/client';
import type { ServiceAccessNotice } from './AuthContext';

export function ServiceAccessNoticeModal({
  notice,
  onAcknowledged,
}: {
  notice: ServiceAccessNotice;
  onAcknowledged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function acknowledge() {
    setBusy(true);
    try {
      await api<void>(`/auth/service-access-notices/${notice.id}/ack`, { method: 'POST' });
      onAcknowledged();
    } finally {
      setBusy(false);
    }
  }
  const occurred = new Date(notice.occurred_at).toLocaleString('cs-CZ');
  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="service-access-title"
      >
        <h2 id="service-access-title">Použití servisního přístupu</h2>
        <p>
          Byl použit technický hlasový API přístup. Tento přístup je určený pro forenzní ověřování
          hlasového chatu.
        </p>
        <dl className="notice-details">
          <dt>Čas</dt>
          <dd>{occurred}</dd>
          <dt>Výsledek</dt>
          <dd>{notice.result === 'accepted' ? 'přijatý požadavek' : notice.result}</dd>
          <dt>Endpoint</dt>
          <dd>{notice.endpoint}</dd>
          {notice.network_context && (
            <>
              <dt>Síť</dt>
              <dd>{notice.network_context}</dd>
            </>
          )}
          {notice.correlation_id && (
            <>
              <dt>Correlation ID</dt>
              <dd>{notice.correlation_id}</dd>
            </>
          )}
        </dl>
        <button className="primary" disabled={busy} onClick={() => void acknowledge()}>
          {busy ? 'Ukládám…' : 'Rozumím'}
        </button>
      </section>
    </div>
  );
}
