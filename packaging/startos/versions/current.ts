import { VersionInfo } from '@start9labs/start-sdk'

/** Package-Version = App-VERSION aus dem Repo-Root, Revision :0. */
export const current = VersionInfo.of({
  version: '0.9.8:0',
  releaseNotes: {
    en_US:
      'SatSage 0.9.8. Package version follows the app release. StartOS Basic Auth opens a session without a console token URL.',
    de_DE:
      'SatSage 0.9.8. Die Paketversion folgt dem App-Release. Nach dem StartOS-Basic-Auth öffnet die Oberfläche eine Sitzung, ohne Token aus der Konsole.',
  },
  migrations: {},
}).satisfies('0.1.0:0')
