import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const backend = process.env.GLUCOTWIN_API_URL || 'http://127.0.0.1:8765';
export default defineConfig({ plugins: [react(), tailwindcss()], server: { proxy: { '/api': backend } }, preview: { proxy: { '/api': backend } } });
