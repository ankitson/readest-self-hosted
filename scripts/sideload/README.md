# Sideload builds (SideStore / AltStore)

Builds an **unsigned**, universal (iPhone + iPad) IPA. SideStore re-signs it on
the device with your own free Apple ID, so nothing here needs a certificate, a
provisioning profile, or an Apple account.

```sh
scripts/sideload/build-unsigned-ipa.sh          # -> dist/readest-selfhost-unsigned.ipa
```

CI runs the same script on a GitHub-hosted macOS runner
(`.github/workflows/build-ios-sideload.yml`) and attaches the IPA plus an
AltSource feed to a GitHub release.

## Why unsigned

Signing an iOS app in CI with a **free** Apple ID does not work, for two
independent reasons:

1. `codesign` can only reach the signing key from inside a GUI (Aqua) security
   session. Over ssh, and from a LaunchAgent, it fails with
   `errSecInternalComponent` — unlocking the keychain and fixing the key's
   partition list are both necessary and neither is sufficient.
2. A personal team's provisioning profile expires after **7 days**, so even a
   working signed build would need re-running weekly.

Building unsigned removes the first problem entirely and hands the second to
SideStore, which re-signs on-device on a schedule with no computer involved.

## How the pieces fit

```
push to main
     │
     ▼
GitHub-hosted macOS runner ── builds unsigned IPA ──┐
                                                    ▼
                                        GitHub release (IPA + source.json)
                                                    │
                    https://…/releases/latest/download/source.json
                                                    │
                                                    ▼
                                   SideStore on the iPad ── signs + auto-refreshes
```

`releases/latest/download/<asset>` permanently redirects to the newest release,
so the URL SideStore subscribes to never changes and no extra hosting is needed.

## The one non-obvious build step

The Xcode project's "Build Rust Code" phase shells out to
`tauri ios xcode-script`, which connects back to the parent `tauri` CLI over a
local JSON-RPC socket. Under a bare `xcodebuild` there is no such parent, and the
phase dies with `ConnectionRefused`. So the script compiles the staticlib itself,
copies it to `Externals/arm64/release/libapp.a`, and sets `READEST_PREBUILT_RUST=1`
to skip the phase (the guard lives in `gen/apple/project.yml`).

`prepare-project.py` additionally strips what a personal team cannot sign: the
Sign in with Apple / associated-domains / App Groups / CarPlay entitlements, and
the ShareExtension and ReadestWidget targets that exist only to share an App
Group. You lose the share sheet, the home-screen widget and CarPlay; sync,
reading and annotation are unaffected.

## Device setup (one time, done by hand)

Verified: the build and feed. **Not** verified on-device — I could not drive the
iPad. Expect to adjust.

1. **Install SideStore.** On iPadOS 26.4+ install it with
   [iloader](https://iloader.app/) — the plain install path hits VPN errors on
   those versions, per SideStore's own 0.6.3 release notes.
2. **Pairing file.** Generate one with `idevicepair` (already installed via
   Homebrew on the Mac) or Jitterbug, and hand it to SideStore.
3. **LocalDevVPN.** Enable it in SideStore; 0.6.3 replaced the old StosVPN/
   WireGuard loopback with it.
4. **Add the source:**
   `https://github.com/ankitson/readest-self-hosted/releases/latest/download/source.json`
5. Install **Readest Selfhost** from that source, then enter
   `https://readest.home.ankitson.com` on first launch.

Free-Apple-ID limits that still apply: **3** sideloaded apps at once (SideStore
itself is one of them) and 10 new App IDs per 7 days. SideStore's background
refresh is what keeps the 7-day certificate from expiring — if the iPad is off
the network for longer than that, the app stops launching until you open
SideStore and refresh.
