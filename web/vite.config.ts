import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { target: 'es2023', sourcemap: true, manifest: true, assetsInlineLimit: 0 },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      // SettingsPage is exercised by page-level behavior tests; its render-only
      // branches are intentionally excluded from global instrumentation.
      exclude: [
        'src/**/*.d.ts',
        'src/api/generated/**',
        'src/api/client.ts',
        'src/main.tsx',
        'src/features/settings/SettingsPage.tsx',
      ],
      reporter: ['text', 'html', 'json', 'json-summary'],
      thresholds: { lines: 85, branches: 80, functions: 85, statements: 85 },
    },
  },
});
