import { T } from '@start9labs/start-sdk'
import { rpcHostId, rpcPort } from 'bitcoin-core-startos/startos/utils'
import { storeJson } from './fileModels/store.json'
import { sdk } from './sdk'

export const appPort = 8730
export const uiHostId = 'ui'
export const uiInterfaceId = 'ui'

export type BridgeAddress = { host: string; port: string }

export type Indexer = 'electrs' | 'fulcrum'

/**
 * Plaintext Electrum port on the LXC bridge (TLS is terminated by StartOS for
 * wallet-facing interfaces; dependents use 50001 without SSL).
 *
 * Host ids are string literals — same approach as mempool-startos — so we do
 * not need fulcrum-startos / electrs-startos as npm imports for the bridge.
 */
const INDEXER_HOSTS: Record<Indexer, { packageId: string; hostId: string }> = {
  electrs: { packageId: 'electrs', hostId: 'electrum' },
  fulcrum: { packageId: 'fulcrum', hostId: 'main' },
}
const electrumPort = 50001

export const parseBridgeAddress = (address: string): BridgeAddress => {
  const value = address.trim()
  const separator = value.lastIndexOf(':')
  if (separator <= 0 || separator === value.length - 1) {
    throw new Error('Invalid bridge address')
  }
  const port = value.slice(separator + 1)
  if (!/^[0-9]+$/.test(port)) {
    throw new Error('Invalid bridge port')
  }
  const host = value.slice(0, separator).replace(/^\[(.*)\]$/, '$1')
  return { host, port }
}

/** User choice from store.json; missing → electrs (pre-Fulcrum installs). */
export async function selectedIndexer(effects: T.Effects): Promise<Indexer> {
  const value = await storeJson.read((s) => s.indexer).const(effects)
  return value === 'fulcrum' ? 'fulcrum' : 'electrs'
}

export const electrumBridge = (effects: T.Effects, indexer: Indexer) => {
  const { packageId, hostId } = INDEXER_HOSTS[indexer]
  return sdk.host
    .getBridgeAddress(effects, {
      packageId,
      hostId,
      internalPort: electrumPort,
      ssl: false,
    })
    .const()
}

export const getBridgeHosts = async (effects: T.Effects) => {
  const indexer = await selectedIndexer(effects)
  const bitcoind = await sdk.host
    .getBridgeAddress(effects, {
      packageId: 'bitcoind',
      hostId: rpcHostId,
      internalPort: rpcPort,
      ssl: false,
    })
    .const()
  const electrum = await electrumBridge(effects, indexer)

  if (!bitcoind || !electrum) {
    throw new Error(
      `Bridge addresses are not available (bitcoind / ${indexer})`,
    )
  }

  return {
    indexer,
    bitcoind: parseBridgeAddress(bitcoind),
    electrum: parseBridgeAddress(electrum),
  }
}
