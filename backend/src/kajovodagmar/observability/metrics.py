from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "kajovodagmar_http_requests_total", "HTTP requests", ["method", "route", "status_class"]
)
HTTP_LATENCY = Histogram(
    "kajovodagmar_http_request_duration_seconds", "HTTP request latency", ["method", "route"]
)
WEBSOCKET_CONNECTIONS = Gauge("kajovodagmar_realtime_connections", "Active realtime connections")
REALTIME_EVENTS = Counter(
    "kajovodagmar_realtime_events_total", "Realtime events", ["direction", "event_type", "result"]
)
AI_RUNS = Counter("kajovodagmar_ai_runs_total", "AI orchestration runs", ["role", "result"])
AI_LATENCY = Histogram(
    "kajovodagmar_ai_run_duration_seconds", "AI orchestration latency", ["role", "phase"]
)
JOBS = Counter("kajovodagmar_jobs_total", "Background jobs", ["kind", "result"])
REALTIME_RECONNECTS = Counter(
    "kajovodagmar_realtime_reconnects_total", "Realtime reconnect attempts", ["result"]
)
REALTIME_QUEUE_BYTES = Gauge(
    "kajovodagmar_realtime_input_queue_bytes", "Current buffered realtime input", ["session"]
)
TRANSCRIPTION_LATENCY = Histogram(
    "kajovodagmar_transcription_duration_seconds", "Speech transcription latency", ["result"]
)
SPEECH_LATENCY = Histogram(
    "kajovodagmar_speech_first_audio_seconds", "Time to first synthesized audio", ["result"]
)
SEARCH_REQUESTS = Counter(
    "kajovodagmar_search_requests_total", "Search requests", ["scope", "result"]
)
DOMAIN_CHANGES = Counter(
    "kajovodagmar_domain_changes_total", "Domain state changes", ["domain", "operation", "result"]
)
PROVIDER_REQUESTS = Counter(
    "kajovodagmar_provider_requests_total", "Provider requests", ["capability", "result"]
)
NOTIFICATIONS = Counter(
    "kajovodagmar_notifications_total", "Notification delivery attempts", ["kind", "result"]
)
EXPORTS = Counter("kajovodagmar_exports_total", "Export operations", ["kind", "result"])
BACKUPS = Counter("kajovodagmar_backups_total", "Backup operations", ["operation", "result"])
DATABASE_POOL = Gauge(
    "kajovodagmar_database_pool_connections", "Database pool connections", ["state"]
)
PROCESS_INFO = Gauge(
    "kajovodagmar_build_info",
    "Application build information",
    ["version", "specification_revision", "component"],
)
PROCESS_INFO.labels("1.0.0", "v0021", "web").set(1)
