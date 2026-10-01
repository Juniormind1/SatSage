import { VersionInfo } from '@start9labs/start-sdk'

/** Sideload 0.9.8. Bleibt im Graph, damit Geräte von dort nach 0.9.9 wandern. */
export const v_0_9_8_0 = VersionInfo.of({
  version: '0.9.8:0',
  releaseNotes: {
    en_US:
      'SatSage 0.9.8. Package version follows the app release. StartOS Basic Auth opens a session without a console token URL.',
    de_DE:
      'SatSage 0.9.8. Die Paketversion folgt dem App-Release. Nach dem StartOS-Basic-Auth öffnet die Oberfläche eine Sitzung, ohne Token aus der Konsole.',
  },
  migrations: {
    up: async () => {},
    down: async () => {},
  },
})
