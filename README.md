# RUNA Harbor — iOS (TestFlight)

This repo holds the Godot-exported Xcode project for **the whole RUNA game** (opens in Dawncrest, like
`Play Runa.cmd`), split into `parts/` because GitHub caps single files at 100 MB. The App Store Connect app
record is still named "RUNA Harbor"; rename it there any time (App Information), the bundle ID stays. A GitHub Actions workflow builds it on a
Mac runner and uploads it to TestFlight. No Mac needed.

## One-time setup: repo secrets

Settings → Secrets and variables → Actions → **New repository secret**, four times:

| Name | Value |
|---|---|
| `ASC_KEY_ID` | App Store Connect API key ID (10 characters) |
| `ASC_ISSUER_ID` | Issuer ID (UUID shown above the keys list) |
| `ASC_KEY_P8` | The whole contents of the `AuthKey_XXXX.p8` file, including the BEGIN/END lines |
| `APPLE_TEAM_ID` | Team ID (10 characters, Membership details) |

Secrets are never shown in logs and can't be read back, even in a public repo.

## Build

Actions → **Build and upload to TestFlight** → **Run workflow**. Takes about 15–25 minutes.
Each run uses the run number as the build number, so every upload is new.
After it finishes, Apple processes the build (5–30 min), then it appears in
App Store Connect → RUNA Harbor → TestFlight and in the TestFlight app on your iPhone.

## Memory

The whole game is big (about 2.4 GB of memory on a PC while Dawncrest builds). The workflow asks iOS for the
**increased memory limit** (on by default, `big_memory` when running it). If Apple's signing step rejects that
entitlement, run the workflow again with `big_memory` unticked.

## Signing

By default (`signing: manual`) each run creates its own App Store distribution certificate and profile through the
API (`tools/asc_sign.py`), signs the app with them, uploads, then revokes and deletes them. That keeps the app's
entitlements (the increased memory limit). The API key needs the **Admin** role. `signing: cloud` uses Xcode's cloud
signing instead, which drops entitlements.

## Logs on the phone

The game writes `logs/godot.log` into its own folder, visible in the iPhone **Files** app (On My iPhone > RUNA).

## If signing fails

Automatic signing on a fresh Mac runner relies on Apple's cloud-managed certificates.
If the log says the key isn't allowed to create or use a distribution certificate,
make a new API key with the **Admin** role (Users and Access → Integrations → App Store
Connect API), and update `ASC_KEY_ID` and `ASC_KEY_P8`. The issuer and team IDs stay the same.

## Updating the game

Re-export from the main project (`tools/web_build_v01/build_web.sh` with `TARGET=ios`: `slim`, `ios settings`,
`import` until done, `ios`),
tar + gzip `build_ios/`, split into 90 MB pieces, replace `parts/`, regenerate `parts.sha256`.
