import { sdk } from './sdk'

export const setDependencies = sdk.setupDependencies(async () => ({
  bitcoind: {
    kind: 'running',
    versionRange: '>=28.0:0',
    healthChecks: ['bitcoind', 'sync-progress'],
  },
  electrs: {
    kind: 'running',
    versionRange: '>=0.11.1:14',
    healthChecks: ['electrs', 'sync'],
  },
}))
