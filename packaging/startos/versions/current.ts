import { VersionInfo } from '@start9labs/start-sdk'

/** Package-Version = App-VERSION aus dem Repo-Root, Revision :0. */
export const current = VersionInfo.of({
  version: '1.0.2:0',
  releaseNotes: {
    en_US:
      'SatSage 1.0.2. A libbitcoin indexer is queried natively when its address index is listed under store.address, and SatSage stays on the query port that answered. Password and key fields have an eye button to show and hide the input. After the history scan the group "Already spent" stays below the UTXOs. The navigation stays pinned on wide screens, and the history log groups progress lines by 10, 20 or 50 addresses.',
    de_DE:
      'SatSage 1.0.2. Ein libbitcoin-Indexer wird auch dann direkt abgefragt, wenn sein Adressindex unter store.address steht, und SatSage bleibt bei dem Abfrage-Port, der geantwortet hat. Passwort- und Schlüsselfelder haben ein Auge, das die Eingabe zeigt und wieder verbirgt. Nach dem Verlaufsscan bleibt die Gruppe „Bereits ausgegeben“ unter den UTXOs stehen. Die Navigation bleibt auf breiten Bildschirmen angeheftet, und das Verlaufs-Log fasst den Fortschritt zu 10, 20 oder 50 Adressen zusammen.',
  },
  migrations: {},
}).satisfies('0.1.0:0')
