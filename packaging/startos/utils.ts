import { T } from '@start9labs/start-sdk'
import { rpcHostId, rpcPort } from 'bitcoin-core-startos/startos/utils'
import {
  electrumHostId,
  port as electrsPort,
} from 'electrs-startos/startos/utils'
import { sdk } from './sdk'

export const appPort = 8730
export const uiHostId = 'ui'
export const uiInterfaceId = 'ui'

export type BridgeAddress = { host: string; port: string }

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

export const getBridgeHosts = async (effects: T.Effects) => {
  const bitcoind = await sdk.host
    .getBridgeAddress(effects, {
      packageId: 'bitcoind',
      hostId: rpcHostId,
      internalPort: rpcPort,
      ssl: false,
    })
    .const()
  const electrs = await sdk.host
    .getBridgeAddress(effects, {
      packageId: 'electrs',
      hostId: electrumHostId,
      internalPort: electrsPort,
      ssl: false,
    })
    .const()

  if (!bitcoind || !electrs) {
    throw new Error('Bridge addresses are not available')
  }

  return {
    bitcoind: parseBridgeAddress(bitcoind),
    electrs: parseBridgeAddress(electrs),
  }
}
