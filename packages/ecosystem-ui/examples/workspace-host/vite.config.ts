// SPDX-License-Identifier: MIT
// Dev server for the F-12 workspace example host. Runs from inside
// packages/ecosystem-ui (reuses its node_modules -- react/react-dom/vite
// are already present there for the library's own Storybook/vitest setup);
// this file is deliberately its own tiny Vite root rather than sharing the
// package's own library-build vite.config.ts (a `build.lib` config can't
// also serve an index.html dev app).
import path from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: __dirname,
  plugins: [react()],
  server: { port: 5174 },
});
