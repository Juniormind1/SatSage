import { T } from '@start9labs/start-sdk'
import { sdk } from './sdk'
import { selectedIndexer } from './utils'

/**
 * bitcoind is always required. Exactly one Electrum indexer (electrs XOR
 * fulcrum) is required — chosen via store.json / Select Indexer action.
 * Pattern mirrors mempool-startos.
 */
export const setDependencies = sdk.setupDependencies(async ({ effects }) => {
  const indexer = await selectedIndexer(effects)

  const deps = {
    bitcoind: {
      kind: 'running' as const,
      versionRange: '>=28.0:0',
      healthChecks: ['bitcoind', 'sync-progress'],
    },
  } as Record<string, T.DependencyRequirement>

  if (indexer === 'fulcrum') {
    deps.fulcrum = {
      kind: 'running',
      versionRange: '>=2.1.1:0',
      healthChecks: ['primary', 'sync-progress'],
    }
  } else {
    deps.electrs = {
      kind: 'running',
      versionRange: '>=0.11.1:14',
      healthChecks: ['electrs', 'sync'],
    }
  }

  return deps
})
