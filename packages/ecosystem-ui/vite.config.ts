// SPDX-License-Identifier: MIT
// Standalone library build (F-1's own "builds independently" requirement) --
// ai-ui itself consumes this package via a source alias (@ecosystem-ui,
// ai-ui/vite.config.js), matching the existing @abs/AgentStudio precedent
// rather than depending on this build's output. This config exists so the
// package can also be typechecked/built/tested in complete isolation.
import path from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    lib: {
      entry: path.resolve(__dirname, 'src/index.ts'),
      formats: ['es'],
      fileName: () => 'ecosystem-ui.js',
    },
    rollupOptions: {
      external: ['react', 'react-dom', 'react/jsx-runtime'],
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test-setup.ts'],
  },
});
