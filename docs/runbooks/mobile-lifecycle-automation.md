# Mobile lifecycle automation

The GitHub Actions mobile workflow runs the isolated acceptance stack and then exercises Chrome through an Android target using `adb reverse tcp:18443 tcp:18443`. The lifecycle smoke records home/background return, screen off/on, window state, connectivity state, and redacted logcat. Browser traces and screenshots remain in the Playwright evidence directory when a browser scenario fails.

`ITERATIONS` and `AUTONOMOUS_SEED` control deterministic repetition. The current workflow defaults to five iterations; merge validation can run twenty and a scheduled or manually dispatched run can run fifty. A real-device cloud is intentionally optional and is activated only after its GitHub Environment is configured; no secret is requested from a user or printed in logs.
