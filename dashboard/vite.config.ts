import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    /*
     * Installable, and offline for real.
     *
     * The floor app already queued its writes locally; what was missing was
     * the SHELL surviving a cold start with no signal. A technician who opens
     * the app in a dead spot got a browser error page, which makes every
     * offline guarantee behind it irrelevant — nothing loads to do the
     * queuing.
     *
     * `autoUpdate` rather than a prompt: nobody on a plant floor is going to
     * act on "a new version is available", and a stale client talking to a
     * moved API is a support call. The new service worker takes over on the
     * next launch.
     *
     * navigateFallback makes the SPA's client-side routes work offline —
     * without it, /board on a cold offline start is a 404 from the cache.
     */
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg', 'icon-192.png', 'icon-512.png', 'push-sw.js'],
      manifest: {
        name: 'Greenlam Tracker',
        short_name: 'Greenlam',
        description: 'Maintenance and production, one register',
        // standalone, so it opens without browser chrome and reads as an app.
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        scope: '/',
        background_color: '#0e0f11',
        theme_color: '#0e0f11',
        lang: 'en',
        categories: ['productivity', 'business'],
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          // `maskable` lets Android crop to its own shape without clipping the
          // fan — the arch has enough margin inside 512 to survive it.
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        // The API is NEVER cached. A cached KPI is a wrong KPI presented with
        // confidence, and the outbox already owns offline writes.
        navigateFallbackDenylist: [/^\/api\//],
        globPatterns: ['**/*.{js,css,html,woff2,png,svg}'],
        // Push handling, added to the generated worker rather than replacing
        // it. Switching to injectManifest for one event handler would mean
        // owning the precache, the navigation fallback and the update strategy
        // by hand — four things that currently work.
        importScripts: ['/push-sw.js'],
        // The Devanagari cut alone is ~80 KB; the default 2 MB cap would drop
        // the fonts and Hindi would render as boxes offline.
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        cleanupOutdatedCaches: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  resolve: {
    alias: {
      // Source alias rather than a build step: packages/core is pure TypeScript
      // with no DOM dependency, so Vite compiles it directly and the Expo port
      // later imports the same files.
      '@greenlam/core': fileURLToPath(
        new URL('../packages/core/src/index.ts', import.meta.url),
      ),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Same origin in development, exactly as in production. This is what
      // makes the httpOnly refresh cookie first-party — without it, Safari on
      // iOS drops it as a cross-site cookie and sessions silently die.
      '/api': {
        // 127.0.0.1, not localhost. On Windows `localhost` resolves to ::1
        // first and Node 18+ uses the OS order verbatim, while uvicorn binds
        // IPv4 only — so every API call through the proxy dies with
        // "ECONNREFUSED ::1:8000" against a server that is running fine.
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  // `vite preview` does NOT inherit server.proxy, and preview is the only way
  // to meet the real service worker — devOptions is off, so `npm run dev` has
  // no offline shell at all. Testing the offline claim means testing the built
  // app, and the built app needs the same first-party /api origin.
  //
  // The proxy runs here on the host, so a phone pointed at this server reaches
  // the API through it. The API itself never has to listen on the LAN.
  preview: {
    port: 4173,
    proxy: {
      '/api': {
        // 127.0.0.1 for the same reason as above.
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Floor phones are mid-range Android on patchy Wi-Fi. Warn early rather
    // than discovering the bundle size during the pilot.
    chunkSizeWarningLimit: 400,
    sourcemap: true,
  },
});
