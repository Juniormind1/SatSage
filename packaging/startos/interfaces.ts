import { i18n } from './i18n'
import { sdk } from './sdk'
import { appPort, uiHostId, uiInterfaceId } from './utils'

export const setInterfaces = sdk.setupInterfaces(async ({ effects }) => {
  // Wie Mempool: StartOS terminiert TLS und leitet durch. Kein Basic Auth,
  // kein Benutzername admin, kein von StartOS erfundenes Passwort.
  const uiMulti = sdk.MultiHost.of(effects, uiHostId)
  const uiOrigin = await uiMulti.bindPort(appPort, {
    protocol: 'http',
    addSsl: {
      addXForwardedHeaders: true,
    },
  })

  const ui = sdk.createInterface(effects, {
    name: i18n('Web UI'),
    id: uiInterfaceId,
    description: i18n('The SatSage web interface'),
    type: 'ui',
    masked: false,
    schemeOverride: null,
    username: null,
    path: '',
    query: {},
  })

  return [await uiOrigin.export([ui])]
})
