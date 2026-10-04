import { VersionInfo } from '@start9labs/start-sdk'

/** Sideload 0.9.9. Bleibt im Graph, damit Geräte von dort nach 0.9.9.5 wandern. */
export const v_0_9_9_0 = VersionInfo.of({
  version: '0.9.9:0',
  releaseNotes: {
    en_US:
      'SatSage 0.9.9. Paged lists, origin net on the tax timeline, Core RPC allowlist. StartOS opens without its own password when .env is plaintext.',
    de_DE:
      'SatSage 0.9.9. Seiten statt langer Listen, Herkunftsnetz im Steuerjahr, Core-RPC nur noch mit Allowlist. StartOS öffnet ohne eigenes Passwort, solange die .env im Klartext liegt.',
  },
  migrations: {
    up: async () => {},
    down: async () => {},
  },
})
