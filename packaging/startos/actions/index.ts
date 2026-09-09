import { sdk } from '../sdk'
import { rotatePassword } from './rotatePassword'
import { selectIndexer } from './selectIndexer'

export const actions = sdk.Actions.of()
  .addAction(rotatePassword)
  .addAction(selectIndexer)
