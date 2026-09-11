import { FileHelper, utils, z } from '@start9labs/start-sdk'
import { sdk } from '../sdk'

const shape = z.object({
  uiPassword: z
    .string()
    .catch(utils.getDefaultString({ charset: 'a-z,A-Z,0-9', len: 32 })),
  // Electrum backend on the StartOS bridge. Default electrs keeps existing
  // sideloads working; users switch to Fulcrum via the Select Indexer action.
  // See doc/START9-fulcrum-indexer.md.
  indexer: z.enum(['electrs', 'fulcrum']).catch('electrs'),
})

export const storeJson = FileHelper.json(
  { base: sdk.volumes.main, subpath: 'store.json' },
  shape,
)
