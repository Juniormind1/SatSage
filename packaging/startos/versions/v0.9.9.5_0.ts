import { VersionInfo } from '@start9labs/start-sdk'

/** Sideload 0.9.9.5. Bleibt im Graph, damit Geräte von dort nach 1.0.0 wandern. */
export const v_0_9_9_5_0 = VersionInfo.of({
  version: '0.9.9.5:0',
  releaseNotes: {
    en_US:
      'SatSage 0.9.9.5, the last release before 1.0.0. FIFO spend builds an unsigned PSBT. The destination turns yellow for a known exchange and red for a sanctioned address, with a confirmation before the PSBT is built.',
    de_DE:
      'SatSage 0.9.9.5, das letzte Release vor 1.0.0. FIFO-Spend baut eine unsignierte PSBT. Die Zieladresse wird gelb bei einer bekannten Börse und rot bei einer sanktionierten Adresse; vor der PSBT fragt ein Dialog.',
  },
  migrations: {
    up: async () => {},
    down: async () => {},
  },
})
