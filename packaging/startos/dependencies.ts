import { sdk } from './sdk'
import { selectedIndexer } from './utils'

/**
 * bitcoind is always required. Exactly one Electrum indexer (electrs XOR
 * fulcrum) is required — chosen via store.json / Select Indexer action.
 * Pattern mirrors mempool-startos.
 *
 * setupDependencies maps object keys to package ids; do not cast to
 * T.DependencyRequirement (that OS type requires an explicit `id`).
 */
export const setDependencies = sdk.setupDependencies(async ({ effects }) => {
  const indexer = await selectedIndexer(effects)

  const bitcoind = {
    kind: 'running' as const,
    versionRange: '>=28.0:0',
    healthChecks: ['bitcoind', 'sync-progress'],
  }

  if (indexer === 'fulcrum') {
    return {
      bitcoind,
      fulcrum: {
        kind: 'running' as const,
        versionRange: '>=2.1.1:0',
        healthChecks: ['primary', 'sync-progress'],
      },
    }
  }

  return {
    bitcoind,
    electrs: {
      kind: 'running' as const,
      versionRange: '>=0.11.1:14',
      healthChecks: ['electrs', 'sync'],
    },
  }
})
