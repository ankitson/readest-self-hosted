import fs from 'node:fs';
import path from 'node:path';

const required = (name) => {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
};

const version = required('SELFHOST_RESOLVED_RELEASE_VERSION');
const releaseTag = required('RELEASE_TAG');
const repository = required('GITHUB_REPOSITORY');
const releasePubDate = required('SELFHOST_RELEASE_PUB_DATE');
const assetsDir = path.resolve(process.env.SELFHOST_RELEASE_ASSETS_DIR || 'release-assets');
const notesPath = path.resolve(
  process.env.SELFHOST_RELEASE_NOTES_PATH || 'release-notes-selfhost.md',
);

if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version)) {
  throw new Error(`Invalid selfhost release version: ${version}`);
}
if (releaseTag !== `selfhost-v${version}`) {
  throw new Error(`Release tag ${releaseTag} does not match version ${version}`);
}
if (!/^[0-9A-Za-z_.-]+\/[0-9A-Za-z_.-]+$/.test(repository)) {
  throw new Error(`Invalid GitHub repository: ${repository}`);
}
if (
  !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(releasePubDate) ||
  Number.isNaN(Date.parse(releasePubDate))
) {
  throw new Error(`Invalid selfhost release publication date: ${releasePubDate}`);
}
if (!fs.statSync(assetsDir, { throwIfNoEntry: false })?.isDirectory()) {
  throw new Error(`Release assets directory does not exist: ${assetsDir}`);
}

const assetNames = {
  windowsX64Setup: `Readest-Selfhost_${version}_x64-setup.exe`,
  windowsX64Portable: `Readest-Selfhost_${version}_x64-portable.exe`,
  windowsArm64Setup: `Readest-Selfhost_${version}_arm64-setup.exe`,
  windowsArm64Portable: `Readest-Selfhost_${version}_arm64-portable.exe`,
  linuxX64AppImage: `Readest-Selfhost_${version}_amd64.AppImage`,
  linuxX64Deb: `Readest-Selfhost_${version}_amd64.deb`,
  linuxX64Rpm: `Readest-Selfhost-${version}-1.x86_64.rpm`,
  linuxArm64AppImage: `Readest-Selfhost_${version}_aarch64.AppImage`,
  linuxArm64Deb: `Readest-Selfhost_${version}_arm64.deb`,
  linuxArm64Rpm: `Readest-Selfhost-${version}-1.aarch64.rpm`,
  macosDmg: `Readest-Selfhost_${version}_universal.dmg`,
  macosUpdater: `Readest-Selfhost_${version}_universal.app.tar.gz`,
  androidUniversal: `Readest-Selfhost_${version}_universal.apk`,
  androidArm64: `Readest-Selfhost_${version}_arm64.apk`,
  androidArmv7: `Readest-Selfhost_${version}_armv7.apk`,
  androidX64: `Readest-Selfhost_${version}_x64.apk`,
  androidX86: `Readest-Selfhost_${version}_x86.apk`,
};

const signedAssets = [
  assetNames.windowsX64Setup,
  assetNames.windowsX64Portable,
  assetNames.windowsArm64Setup,
  assetNames.windowsArm64Portable,
  assetNames.linuxX64AppImage,
  assetNames.linuxX64Deb,
  assetNames.linuxX64Rpm,
  assetNames.linuxArm64AppImage,
  assetNames.linuxArm64Deb,
  assetNames.linuxArm64Rpm,
  assetNames.macosUpdater,
  assetNames.androidUniversal,
  assetNames.androidArm64,
  assetNames.androidArmv7,
  assetNames.androidX64,
  assetNames.androidX86,
];
const unsignedAssets = [assetNames.macosDmg];
const expectedAssets = [
  ...signedAssets.flatMap((assetName) => [assetName, `${assetName}.sig`]),
  ...unsignedAssets,
].sort();

const actualAssets = fs
  .readdirSync(assetsDir, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name !== 'latest.json')
  .map((entry) => entry.name)
  .sort();
const expectedSet = new Set(expectedAssets);
const actualSet = new Set(actualAssets);
const missingAssets = expectedAssets.filter((assetName) => !actualSet.has(assetName));
const unexpectedAssets = actualAssets.filter((assetName) => !expectedSet.has(assetName));

if (missingAssets.length > 0) {
  throw new Error(`Missing release assets: ${missingAssets.join(', ')}`);
}
if (unexpectedAssets.length > 0) {
  throw new Error(`Unexpected release assets: ${unexpectedAssets.join(', ')}`);
}
for (const assetName of expectedAssets) {
  if (fs.statSync(path.join(assetsDir, assetName)).size === 0) {
    throw new Error(`Release asset is empty: ${assetName}`);
  }
}

const baseUrl = `https://github.com/${repository}/releases/download/${releaseTag}`;
const readSignature = (assetName) => {
  const signature = fs.readFileSync(path.join(assetsDir, `${assetName}.sig`), 'utf8').trim();
  if (!signature) {
    throw new Error(`Updater signature is empty: ${assetName}.sig`);
  }
  return signature;
};
const entry = (assetName) => ({
  signature: readSignature(assetName),
  url: `${baseUrl}/${encodeURIComponent(assetName)}`,
});

const platforms = {
  'windows-x86_64': entry(assetNames.windowsX64Setup),
  'windows-x86_64-nsis': entry(assetNames.windowsX64Setup),
  'windows-x86_64-portable': entry(assetNames.windowsX64Portable),
  'windows-aarch64': entry(assetNames.windowsArm64Setup),
  'windows-aarch64-nsis': entry(assetNames.windowsArm64Setup),
  'windows-aarch64-portable': entry(assetNames.windowsArm64Portable),
  'linux-x86_64': entry(assetNames.linuxX64AppImage),
  'linux-x86_64-appimage': entry(assetNames.linuxX64AppImage),
  'linux-x86_64-deb': entry(assetNames.linuxX64Deb),
  'linux-x86_64-rpm': entry(assetNames.linuxX64Rpm),
  'linux-aarch64': entry(assetNames.linuxArm64AppImage),
  'linux-aarch64-appimage': entry(assetNames.linuxArm64AppImage),
  'linux-aarch64-deb': entry(assetNames.linuxArm64Deb),
  'linux-aarch64-rpm': entry(assetNames.linuxArm64Rpm),
  'darwin-x86_64': entry(assetNames.macosUpdater),
  'darwin-x86_64-app': entry(assetNames.macosUpdater),
  'darwin-aarch64': entry(assetNames.macosUpdater),
  'darwin-aarch64-app': entry(assetNames.macosUpdater),
  'darwin-universal': entry(assetNames.macosUpdater),
  'darwin-universal-app': entry(assetNames.macosUpdater),
  'android-universal': entry(assetNames.androidUniversal),
  'android-arm64': entry(assetNames.androidArm64),
  'android-armv7': entry(assetNames.androidArmv7),
  'android-x86_64': entry(assetNames.androidX64),
  'android-i686': entry(assetNames.androidX86),
};

const latest = {
  version,
  notes: `Readest Selfhost ${releaseTag}`,
  pub_date: releasePubDate,
  platforms,
};
fs.writeFileSync(path.join(assetsDir, 'latest.json'), `${JSON.stringify(latest, null, 2)}\n`);

const releaseNotes = `# Readest Selfhost ${releaseTag}

Readest Selfhost client release ${releaseTag}.

The macOS build is ad-hoc signed but is not Apple Developer ID signed or notarized; macOS Gatekeeper may display a warning.
`;
fs.writeFileSync(notesPath, releaseNotes);

console.log(
  `Prepared ${expectedAssets.length} selfhost assets and ${Object.keys(platforms).length} updater platforms.`,
);
