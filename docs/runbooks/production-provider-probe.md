# Production provider probe

After deployment, the versioned deployment script runs `kajovodagmar diagnostics-voice-live-probe` inside the exact deployed web container. The command reads the selected model roles and decrypts provider credentials through the application `SecretCipher`; no key is accepted as a command-line argument or GitHub Actions input.

The probe sends only synthetic conversation, WAV, speech, and embedding inputs. Its JSON output contains role, model ID, timing, safe provider request IDs, dimensions, and byte counts. It never records Authorization headers, credentials, cookies, production conversation content, or audio. Any failed speech capability is reported as `speech probe failed` through the command's non-zero result and deployment evidence.

Deployment fails and uses the existing rollback trap if the probe fails. Inspect the redacted release evidence at the server's protected release log directory.
