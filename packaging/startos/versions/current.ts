import { VersionInfo } from '@start9labs/start-sdk'

/** Package-Version = App-VERSION aus dem Repo-Root, Revision :0. */
export const current = VersionInfo.of({
  version: '1.0.1:0',
  releaseNotes: {
    en_US:
      'SatSage 1.0.1. Filters accept fiat amounts (EUR, USD, €, $) and convert them to sats at the current price, global search hits show the fiat value, wallets appear faster on first load, and the scan keeps the platform data source.',
    de_DE:
      'SatSage 1.0.1. Filter verstehen Fiat-Beträge (EUR, USD, €, $) und rechnen sie zum aktuellen Kurs in Sats um, Treffer der globalen Suche zeigen den Fiat-Wert, Wallets erscheinen beim ersten Laden schneller, und der Scan behält die Datenquelle der Plattform.',
  },
  migrations: {},
}).satisfies('0.1.0:0')
