export const DEFAULT_LANG = 'en_US'

const dict = {
  'SatSage API': 0,
  'SatSage is ready': 1,
  'SatSage is not ready': 2,
  'Web UI': 3,
  'The SatSage web interface': 4,
  'Rotate Web UI Password': 5,
  'Generate a new Basic-auth password for the SatSage web interface. Stop SatSage before rotating it.': 6,
  'SatSage Web UI Password': 7,
  'Use this password with the username admin.': 8,
  Password: 9,
  'Select Indexer': 10,
  'Electrum server for SatSage address history and UTXO lookups (StartOS bridge)': 11,
  'Fulcrum (recommended when installed)': 12,
  Electrs: 13,
  'Choose Electrs or Fulcrum as the local Electrum backend for SatSage': 14,
} as const

export type I18nKey = keyof typeof dict
export type LangDict = Record<(typeof dict)[I18nKey], string>
export default dict
