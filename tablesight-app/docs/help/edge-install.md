# Installing the edge agent
1. Dashboard → Location → "Add device" shows an 8-digit pairing code (valid 15 minutes, single use).
2. On the PC or edge box on the same network as your cameras run `sh edge-install.sh <code> <your server>`.
3. The device appears under Devices with a health status. No video leaves the building unless you enable cloud video.
Troubleshooting: "invalid or expired code" → generate a new one. Device offline → check Wi-Fi; events are buffered and replayed automatically.
