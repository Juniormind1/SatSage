import { utils } from '@start9labs/start-sdk'
import { sdk } from '../sdk'
import { storeJson } from '../fileModels/store.json'

export const seedFiles = sdk.setupOnInit(async (effects) => {
  // Use once(), not const(): seeding may write uiPassword, and FileHelper
  // rejects "write after const" for the same effects.constRetry scope.
  const store = await storeJson.read().once()
  if (!store?.uiPassword) {
    await storeJson.merge(effects, {
      uiPassword: utils.getDefaultString({ charset: 'a-z,A-Z,0-9', len: 32 }),
    })
  }
})
