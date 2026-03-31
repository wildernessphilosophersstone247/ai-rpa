# Security Notes

1. **LAN-only**: The Android REPL beta listens on `http://<device-ip>:8080`. Keep the device and controller on a trusted local network; do not expose the port to the open internet.
2. **Token**: The current health response reports `tokenRequired:false`. Treat the port as sensitive while we add authentication.
3. **Permissions risk**: Screenshot/MediaProjection permission grants a capture surface; users should only authorize the desktop they trust. Accessibility access grants visibility into the UI tree—enable it temporarily and revoke if not using the REPL.
