import { VersionInfo } from '@start9labs/start-sdk'

/** Release 1.0.0. Bleibt im Graph, damit Geräte von dort nach 1.0.1 wandern. */
export const v_1_0_0_0 = VersionInfo.of({
  version: '1.0.0:0',
  releaseNotes: {
    en_US:
      'SatSage 1.0.0, the first stable release. Your own Electrs on a non-standard port is used directly, origin and sanctions check work right after start, and failed jobs show the actual reason.',
    de_DE:
      'SatSage 1.0.0, das erste stabile Release. Ein eigener Electrs auf einem Nicht-Standard-Port wird direkt genutzt, Herkunft und Sanktionscheck laufen gleich nach dem Start, und gescheiterte Läufe nennen den Grund.',
  },
  migrations: {
    up: async () => {},
    down: async () => {},
  },
})
