import { storeJson } from '../fileModels/store.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'
import { selectedIndexer } from '../utils'

const { InputSpec, Value } = sdk

const indexerInputSpec = InputSpec.of({
  indexer: Value.select({
    name: i18n('Select Indexer'),
    description: i18n(
      'Electrum server for SatSage address history and UTXO lookups (StartOS bridge)',
    ),
    values: {
      fulcrum: i18n('Fulcrum (recommended when installed)'),
      electrs: i18n('Electrs'),
    },
    default: 'electrs',
  }),
})

export const selectIndexer = sdk.Action.withInput(
  'select-indexer',
  {
    name: i18n('Select Indexer'),
    description: i18n(
      'Choose Electrs or Fulcrum as the local Electrum backend for SatSage',
    ),
    warning: null,
    allowedStatuses: 'any',
    group: null,
    visibility: 'enabled',
  },
  indexerInputSpec,
  async ({ effects }) => ({ indexer: await selectedIndexer(effects) }),
  async ({ effects, input }) =>
    storeJson.merge(effects, { indexer: input.indexer }),
)
