# Permissions Overview

This document summarizes the permissions the Android REPL beta requests and why they matter for the first public release.

## Accessibility

- The app exposes an accessibility service so it can read the current UI tree (`android.ui.getAriaTree`) and produce refIds/xpaths. The service should be enabled once per device and can be disabled later; no other OS permissions are required for this surface.

## Screenshot / MediaProjection

- Capturing screenshots uses Android’s `MediaProjection` API. Users must grant screenshot permission after launching `aria_tree.py --screenshot` once. The CLI falls back to template-based captures when the permission is absent. The permission prompt is shown by the system (not the app), and users can revoke it later.

## Local Network / Token

- The desktop agent communicates with the device over LAN (`http://<device-ip>:8080`). A simple health endpoint (`/health`) reports status and `tokenRequired:false`. There is no transport encryption in this beta, so keep the device on a trusted network segment.

## Security Notes

- Only expose `/api/execute`, `/health`, `/screenshot`, `/api/apps`, and the documented launcher endpoints. Do not forward requests beyond the documented surface. You can disable the REPL by stopping the phone-side service or killing the app.
