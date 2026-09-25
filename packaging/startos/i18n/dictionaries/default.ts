export const DEFAULT_LANG = 'en_US'

const dict = {
  'SatSage API': 0,
  'SatSage is ready': 1,
  'SatSage is not ready': 2,
  'Web UI': 3,
  'The SatSage web interface': 4,
  'Select Indexer': 5,
  'Electrum server for SatSage address history and UTXO lookups (StartOS bridge)': 6,
  'Fulcrum (recommended when installed)': 7,
  Electrs: 8,
  'Choose Electrs or Fulcrum as the local Electrum backend for SatSage': 9,
} as const

export type I18nKey = keyof typeof dict
export type LangDict = Record<(typeof dict)[I18nKey], string>
export default dict
