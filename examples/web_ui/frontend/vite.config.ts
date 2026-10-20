import path from 'path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import svgr from 'vite-plugin-svgr';

export default defineConfig({
	plugins: [react(), tailwindcss(), svgr()],
	server: {
		proxy: {
			// Port 3100: the web_ui express backend defaults to 3000, but
			// that port is taken by other local apps (e.g. GitFox) on this
			// machine, so start.sh starts it with PORT=3100.
			'/api': 'http://localhost:3100',
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
