import path from 'path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import svgr from 'vite-plugin-svgr';

export default defineConfig({
	plugins: [react(), tailwindcss(), svgr()],
	server: {
		// 5173 is the AgentScope web UI; the platform frontend is its own app.
		port: 5174,
		proxy: {
			// All traffic goes to the L1 orchestration backend only (BFF,
			// architecture.md §2): the frontend never talks to the runtime.
			'/api': {
				target: 'http://localhost:8100',
				rewrite: (p) => p.replace(/^\/api/, ''),
			},
		},
	},
	resolve: {
		alias: {
			'@': path.resolve(__dirname, './src'),
			'next/navigation': path.resolve(__dirname, './src/lib/next-navigation-shim.ts'),
		},
	},
	optimizeDeps: {
		include: ['mime-types'],
	},
});
