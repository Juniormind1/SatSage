import { VersionInfo } from '@start9labs/start-sdk'

/** Package-Version = App-VERSION aus dem Repo-Root, Revision :0. */
export const current = VersionInfo.of({
  version: '1.0.1:0',
  releaseNotes: {
    en_US:
      'SatSage 1.0.1. Filters accept fiat amounts (EUR, USD, €, $) and convert them to sats at the current price, global search hits show the fiat value, wallets appear faster on first load, and the scan keeps the platform data source. Acquisition is the moment sats arrive at your own address, not when the sender received them. Unresolved inputs of a batch transaction count as a bundle at that transaction\'s block time and do not turn green early. The 31 December balance counts only outputs that already existed that day. Prior-year figures change: after the update, trace the origin of all UTXOs and recalculate the tax year.',
    de_DE:
      'SatSage 1.0.1. Filter verstehen Fiat-Beträge (EUR, USD, €, $) und rechnen sie zum aktuellen Kurs in Sats um, Treffer der globalen Suche zeigen den Fiat-Wert, Wallets erscheinen beim ersten Laden schneller, und der Scan behält die Datenquelle der Plattform. Die Anschaffung ist der Empfang auf der eigenen Adresse, nicht mehr die Zeit beim Absender. Ungeklärte Eingänge einer Sammel-Transaktion zählen als Bündel zur Blockzeit dieser Transaktion und werden nicht zu früh grün. Der Bestand am 31.12. zählt nur Outputs, die an diesem Tag schon lagen. Vorjahreswerte ändern sich: nach dem Update „Herkunft aller UTXOs“ laufen lassen und das Steuerjahr neu auswerten.',
  },
  migrations: {},
}).satisfies('0.1.0:0')
