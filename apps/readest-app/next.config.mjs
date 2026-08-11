import withSerwistInit from '@serwist/next';
import withBundleAnalyzer from '@next/bundle-analyzer';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Build provenance surfaced in the About dialog. Derived here rather than in
// each build script so every path picks it up -- the iOS sideload build,
// `tauri build` for desktop, and the Docker image. CI env wins; git is the
// local fallback.
const gitOut = (cmd) => {
  try {
    return execSync(cmd, { cwd: __dirname, stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim();
  } catch {
    return '';
  }
};

// A Docker build has neither a git checkout nor the workflow's GITHUB_* env, so
// the values can also be passed in explicitly as build args.
const explicitCommit = process.env['NEXT_PUBLIC_BUILD_COMMIT'];
const explicitRepo = process.env['NEXT_PUBLIC_BUILD_REPO'];

const inCI = Boolean(process.env['GITHUB_SHA'] || explicitCommit);
const buildCommit = (() => {
  const sha = explicitCommit || process.env['GITHUB_SHA'] || gitOut('git rev-parse HEAD');
  if (!sha) return '';
  const short = sha.slice(0, 7);
  // Only meaningful locally: CI legitimately patches tracked files (identity,
  // updater endpoint) before the frontend build, so every CI build would
  // otherwise be tagged dirty.
  return !inCI && gitOut('git status --porcelain') ? `${short}-dirty` : short;
})();
const buildRepo =
  explicitRepo ||
  process.env['GITHUB_REPOSITORY'] ||
  gitOut('git remote get-url origin').match(/[:/]([^/:]+\/[^/]+?)(?:\.git)?$/)?.[1] ||
  '';

const isDev = process.env['NODE_ENV'] === 'development';
const appPlatform = process.env['NEXT_PUBLIC_APP_PLATFORM'];

if (isDev) {
  const { initOpenNextCloudflareForDev } = await import('@opennextjs/cloudflare');
  initOpenNextCloudflareForDev();
}

const exportOutput = appPlatform !== 'web' && !isDev;
// Opt-in standalone output, set only by the Docker production build
// (Dockerfile). Every other path keeps the original behavior: Tauri `export`,
// local `build-web` (output undefined), dev, and the Cloudflare/OpenNext
// deploy — which forces standalone itself via NEXT_PRIVATE_STANDALONE.
const standaloneOutput = !exportOutput && process.env['BUILD_STANDALONE'] === 'true';

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Ensure Next.js uses SSG instead of SSR
  // https://nextjs.org/docs/pages/building-your-application/deploying/static-exports
  // The Docker production image opts into a self-contained `.next/standalone`
  // tree (see Dockerfile) so it can ship only the traced runtime; all other
  // web builds fall back to the default server output.
  env: {
    NEXT_PUBLIC_BUILD_COMMIT: buildCommit,
    NEXT_PUBLIC_BUILD_REPO: buildRepo,
  },
  output: exportOutput ? 'export' : standaloneOutput ? 'standalone' : undefined,
  // Emit browser source maps for the Tauri export build so Sentry can
  // symbolicate crashes. `scripts/upload-sourcemaps.mjs` uploads them after the
  // build and strips the .map files, so they never ship inside the app bundle.
  productionBrowserSourceMaps: exportOutput,
  // Monorepo: trace from the repo root so workspace packages land in the
  // standalone tree. Only relevant to — and only set for — the Docker build.
  outputFileTracingRoot: standaloneOutput ? path.join(__dirname, '../../') : undefined,
  pageExtensions: exportOutput ? ['jsx', 'tsx'] : ['js', 'jsx', 'ts', 'tsx'],
  // Note: This feature is required to use the Next.js Image component in SSG mode.
  // See https://nextjs.org/docs/messages/export-image-api for different workarounds.
  images: {
    unoptimized: true,
  },
  devIndicators: false,
  experimental: {
    // Dev caching is on by default since Next 16.1. We deliberately do NOT
    // enable Turbopack's build cache (turbopackFileSystemCacheForBuild, beta):
    // a build interrupted mid-compile leaves a partial cache that the next
    // build mishandles, fanning out workers until it exhausts RAM.
    turbopackFileSystemCacheForDev: true,
  },
  // Configure assetPrefix or else the server won't properly resolve your assets.
  assetPrefix: '',
  reactStrictMode: true,
  serverExternalPackages: ['isows'],
  allowedDevOrigins: ['192.168.2.120'],
  webpack: (config, { isServer }) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      nunjucks: 'nunjucks/browser/nunjucks.js',
      // `js-mdict` is consumed as TS source via tsconfig paths from
      // `packages/js-mdict/src/`; its sources `import 'fflate'` directly.
      // Without an alias, webpack walks up from that source location and
      // can't find fflate (only installed in this app's node_modules).
      fflate: path.resolve(__dirname, 'node_modules/fflate'),
      ...(appPlatform !== 'web' ? { '@tursodatabase/database-wasm': false } : {}),
      ...(isServer && appPlatform === 'web'
        ? { '@readest/turso-database-wasm/webpack': false, 'jieba-wasm': false }
        : {}),
    };
    return config;
  },
  turbopack: {
    resolveAlias: {
      nunjucks: 'nunjucks/browser/nunjucks.js',
      // Turbopack rejects absolute paths in resolveAlias ("server relative
      // imports not implemented") — use a project-relative path.
      fflate: './node_modules/fflate',
      ...(appPlatform !== 'web' ? { '@tursodatabase/database-wasm': './src/utils/stub.ts' } : {}),
    },
  },
  transpilePackages: [
    'ai',
    'ai-sdk-ollama',
    '@ai-sdk/react',
    '@assistant-ui/react',
    '@assistant-ui/react-ai-sdk',
    '@assistant-ui/react-markdown',
    'streamdown',
    ...(isDev
      ? []
      : [
          'i18next-browser-languagedetector',
          'react-i18next',
          'i18next',
          '@tauri-apps',
          'highlight.js',
          'foliate-js',
          'marked',
        ]),
  ],
  async rewrites() {
    return [
      {
        source: '/reader/:ids',
        destination: '/reader?ids=:ids',
      },
      {
        source: '/o/book/:hash/annotation/:id',
        destination: '/o?book=:hash&note=:id',
      },
      {
        source: '/s/:token',
        destination: '/s?token=:token',
      },
    ];
  },
  async headers() {
    return [
      {
        source: '/.well-known/apple-app-site-association',
        headers: [
          {
            key: 'Content-Type',
            value: 'application/json',
          },
        ],
      },
      {
        source: '/_next/static/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: isDev
              ? 'public, max-age=0, must-revalidate'
              : 'public, max-age=31536000, immutable',
          },
        ],
      },
    ];
  },
};

const pwaDisabled = isDev || appPlatform !== 'web';

const withPWA = pwaDisabled
  ? (config) => config
  : withSerwistInit({
      swSrc: 'src/sw.ts',
      swDest: 'public/sw.js',
      cacheOnNavigation: true,
      reloadOnOnline: true,
      disable: false,
      register: true,
      scope: '/',
    });

const withAnalyzer = withBundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
});

export default withPWA(withAnalyzer(nextConfig));
