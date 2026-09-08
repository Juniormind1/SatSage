import { utils } from '@start9labs/start-sdk'
import { storeJson } from '../fileModels/store.json'
import { i18n } from '../i18n'
import { sdk } from '../sdk'

export const rotatePassword = sdk.Action.withoutInput(
  'rotate-password',
  async () => ({
    name: i18n('Rotate Web UI Password'),
    description: i18n(
      'Generate a new Basic-auth password for the SatSage web interface. Stop SatSage before rotating it.',
    ),
    warning: null,
    allowedStatuses: 'only-stopped',
    group: null,
    visibility: 'enabled',
  }),
  async ({ effects }) => {
    const password = utils.getDefaultString({
      charset: 'a-z,A-Z,0-9',
      len: 32,
    })
    await storeJson.merge(effects, { uiPassword: password })
    return {
      version: '1',
      title: i18n('SatSage Web UI Password'),
      message: i18n('Use this password with the username admin.'),
      result: {
        type: 'group',
        value: [
          {
            type: 'single',
            name: i18n('Password'),
            description: null,
            value: password,
            masked: true,
            copyable: true,
            qr: false,
          },
        ],
      },
    }
  },
)
