import type { VitePWAOptions } from "vite-plugin-pwa";

// A navigation under /api (sign-in, Google's return) must reach the network:
// the service worker never answers it with the cached shell.
export const API_NAVIGATION = /^\/api(\/|$)/;

export const pwaOptions: Partial<VitePWAOptions> = {
  registerType: "autoUpdate",
  // registerSW.js, an external file: the platform serves script-src 'self'.
  injectRegister: "script-defer",
  pwaAssets: { config: true },
  manifest: {
    name: "CoinPilot",
    short_name: "CoinPilot",
    description: "Keeps your Kraken portfolio on its targets.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    theme_color: "#0f172a",
    background_color: "#0f172a",
  },
  workbox: {
    globPatterns: ["**/*.{js,css,html,svg,png,ico,webmanifest}"],
    navigateFallback: "/index.html",
    navigateFallbackDenylist: [API_NAVIGATION],
    // Nothing fetched at run time is cached: no /api answer.
    runtimeCaching: [],
  },
  devOptions: { enabled: false },
};
