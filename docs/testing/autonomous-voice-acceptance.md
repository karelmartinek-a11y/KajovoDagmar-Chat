# Autonomous voice acceptance

The acceptance runner creates a separate Compose project and database for every run. It generates the initialization secret, password, and username in the runner process, seeds only the deterministic provider in `KAJOVODAGMAR_ENVIRONMENT=test`, initializes the instance through the normal authenticated UI flow, and removes the project and volumes on exit.

The deterministic provider is not a fallback. `ProviderService.runtime` rejects it unless the application environment is exactly `test`; production cannot expose its catalog or HTTP hook. Production capability checks use the server-side encrypted provider configuration through `kajovodagmar diagnostics-voice-live-probe`.

Run `make autonomous-voice-acceptance ITERATIONS=20`. Set `AUTONOMOUS_SEED` to reproduce a failing seed. Logs, Compose diagnostics, and probe JSON are written below `release/evidence/generated`. The runner never writes credentials to these artifacts.

The browser suite covers desktop/mobile Playwright behavior. Android lifecycle smoke uses `adb reverse`, Chrome, home/background, screen off/on, and connectivity evidence. A physical iOS device is not simulated; WebKit coverage is available through the regular Playwright projects.
