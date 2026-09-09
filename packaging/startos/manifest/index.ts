import { setupManifest } from '@start9labs/start-sdk'
import { long, short } from './i18n'

export const manifest = setupManifest({
  id: 'satsage',
  title: 'SatSage',
  license: 'MIT',
  packageRepo: 'https://github.com/Juniormind1/SatSage',
  upstreamRepo: 'https://github.com/Juniormind1/SatSage',
  marketingUrl: 'https://github.com/Juniormind1/SatSage',
  donationUrl: 'https://github.com/Juniormind1/SatSage',
  description: { short, long },
  volumes: ['main'],
  images: {
    satsage: {
      source: {
        // Context = repo root (parent of packaging/). Dockerfile stays here.
        dockerBuild: { workdir: '..', dockerfile: 'Dockerfile' },
      },
      // The custom image has only been staged for the x86 SDK target so far.
      arch: ['x86_64'],
    },
  },
  dependencies: {
    bitcoind: {
      optional: false,
      description: {
        en_US: 'Bitcoin Core RPC and read-only cookie for wallet lookups',
      },
      metadata: {
        title: 'Bitcoin',
        icon: 'https://raw.githubusercontent.com/Start9Labs/bitcoin-core-startos/refs/heads/30.x/dep-icon.svg',
      },
    },
    // Exactly one of electrs / fulcrum is required at runtime (Select Indexer).
    electrs: {
      optional: true,
      description: {
        en_US:
          'Electrum index (electrs). Use Select Indexer to choose electrs or Fulcrum.',
      },
      metadata: {
        title: 'Electrs',
        icon: 'https://raw.githubusercontent.com/Start9-Community/electrs-startos/refs/heads/next/icon.svg',
      },
    },
    fulcrum: {
      optional: true,
      description: {
        en_US:
          'Electrum index (Fulcrum). Use Select Indexer to choose Fulcrum or electrs.',
      },
      metadata: {
        title: 'Fulcrum',
        icon: 'https://raw.githubusercontent.com/Start9Labs/fulcrum-startos/master/icon.png',
      },
    },
  },
})
