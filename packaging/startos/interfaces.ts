import { i18n } from './i18n'
import { storeJson } from './fileModels/store.json'
import { sdk } from './sdk'
import { appPort, uiHostId, uiInterfaceId } from './utils'

export const setInterfaces = sdk.setupInterfaces(async ({ effects }) => {
  // Wait until seedFiles has written uiPassword so rotate-password / docs stay consistent.
  const password = await storeJson.read((s) => s.uiPassword).const(effects)
  if (!password) return []

  // Bind plain HTTP for the container and expose StartOS-managed HTTPS. The
  // proxy gate uses the same generated password that is seeded in the app.
  const uiMulti = sdk.MultiHost.of(effects, uiHostId)
  const uiOrigin = await uiMulti.bindPort(appPort, {
    protocol: 'http',
    addSsl: {
      addXForwardedHeaders: true,
      auth: {
        type: 'basic',
        credentials: [{ username: 'admin', password }],
        realm: null,
      },
    },
  })

  const ui = sdk.createInterface(effects, {
    name: i18n('Web UI'),
    id: uiInterfaceId,
    description: i18n('The SatSage web interface'),
    type: 'ui',
    masked: false,
    schemeOverride: null,
    username: 'admin',
    path: '',
    query: {},
  })

  return [await uiOrigin.export([ui])]
})
