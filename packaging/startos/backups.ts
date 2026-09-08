import { sdk } from './sdk'

// The single volume contains .env, its backup, the password hash, and caches.
export const { createBackup, restoreInit } = sdk.setupBackups(
  async () => sdk.Backups.ofVolumes('main'),
)
