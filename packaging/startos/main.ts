import { manifest as bitcoinManifest } from 'bitcoin-core-startos/startos/manifest'
import { i18n } from './i18n'
import { sdk } from './sdk'
import { appPort, getBridgeHosts } from './utils'

export const main = sdk.setupMain(async ({ effects }) => {
  const bridges = await getBridgeHosts(effects)
  if (!bridges.bitcoind || !bridges.electrum) {
    throw new Error(
      `bitcoind and ${bridges.indexer} bridge addresses are not available yet`,
    )
  }

  const app = sdk.SubContainer.of(
    effects,
    { imageId: 'satsage' },
    sdk.Mounts.of()
      .mountVolume({
        volumeId: 'main',
        subpath: null,
        mountpoint: '/data',
        readonly: false,
      })
      .mountDependency<typeof bitcoinManifest>({
        dependencyId: 'bitcoind',
        volumeId: 'main',
        subpath: null,
        mountpoint: '/mnt/bitcoind',
        readonly: true,
      }),
    'satsage-sub',
  )

  return sdk.Daemons.of(effects).addDaemon('server', {
    subcontainer: app,
    exec: {
      command: sdk.useEntrypoint(),
      env: {
        SATSAGE_MANAGED_BY: 'start9',
        // Kein StartOS-Passwort. Ein optionales SatSage-Passwort setzt nur
        // der Nutzer in den Einstellungen. Ohne dieses Passwort öffnet die
        // Web-UI ohne Token — die 127.0.0.1-Zeile im Log ist der Container.
        SATSAGE_TRUST_PROXY: '1',
        SATSAGE_HOST_ALLOWLIST:
          '*.local,.onion,192.168.*.*,10.*.*.*,172.16.*.*',
        SATSAGE_BIND: '0.0.0.0', // StartOS proxy dials container bridge IP, not loopback
        RPC_COOKIE_FILE: '/mnt/bitcoind/.cookie',
        BITCOIND_HOST: bridges.bitcoind.host,
        NODE_IP: bridges.bitcoind.host,
        RPCPORT: bridges.bitcoind.port,
        // Electrum protocol always via FULCRUM_* (app name); source package is
        // electrs or fulcrum — see SATSAGE_ELECTRUM_INDEXER / doc/START9-fulcrum-indexer.md
        SATSAGE_ELECTRUM_INDEXER: bridges.indexer,
        FULCRUM_HOST: bridges.electrum.host,
        FULCRUM_PORT: bridges.electrum.port,
        FULCRUM_SSL: 'false',
        // Legacy alias for older AppState mapping (ELECTRS_HOST → FULCRUM_HOST).
        ELECTRS_HOST: bridges.electrum.host,
        SATSAGE_OUTBOUND_PUBLIC_OPT_IN: '0',
      },
    },
    ready: {
      display: i18n('SatSage API'),
      gracePeriod: 30000,
      // Port im Container, nicht fetch auf 127.0.0.1: der Health-Daemon läuft
      // im StartOS-Host und erreicht die Container-Loopback nicht.
      fn: () =>
        sdk.healthCheck.checkPortListening(effects, appPort, {
          successMessage: i18n('SatSage is ready'),
          errorMessage: i18n('SatSage is not ready'),
        }),
    },
    requires: [],
  })
})
