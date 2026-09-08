import { sdk } from '../sdk'
import { rotatePassword } from './rotatePassword'

export const actions = sdk.Actions.of().addAction(rotatePassword)
