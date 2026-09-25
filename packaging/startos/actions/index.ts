import { sdk } from '../sdk'
import { selectIndexer } from './selectIndexer'

export const actions = sdk.Actions.of().addAction(selectIndexer)
