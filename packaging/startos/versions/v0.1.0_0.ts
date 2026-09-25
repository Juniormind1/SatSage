import { IMPOSSIBLE, VersionInfo } from '@start9labs/start-sdk'

/** Vor 0.9.7 hing das Sideload-Paket fest auf diesem Scaffold. */
export const v_0_1_0_0 = VersionInfo.of({
  version: '0.1.0:0',
  releaseNotes: {
    en_US: 'Initial SatSage StartOS packaging scaffold',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
