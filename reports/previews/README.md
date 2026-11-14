# Progress Widget preview

[Open the light-theme standalone interactive preview](progress-widget-preview.html) or [the dark-theme preview](progress-widget-preview-dark.html). Both use local sample data and the HTML/CSS/JS embedded in `app/bot/progress_widget.py`; switch tabs and open a history item to inspect the screens. No network or Telegram account is used.

The managed environment has Chromium installed but cannot complete a headless screenshot: even a minimal local HTML page stalls while its sandbox reports read-only process/font-cache errors. This preview is therefore an HTML artifact, not a Telegram-client screenshot. The Widget was not live-tested in Telegram.

## Progress 2.1 PNG dashboard

The current bot dashboard is rendered by Pillow in `app/bot/progress_image.py`. These six PNGs are generated from deterministic, fictional data by `uv run python scripts/generate_progress_previews.py`:

* [Overview: 72 completed, including 35 skipped](progress-dashboard-overview.png)
* [Numbers 1–7](progress-dashboard-numbers-1-7.png)
* [Numbers 8–14](progress-dashboard-numbers-8-14.png)
* [History](progress-dashboard-history.png)
* [Errors](progress-dashboard-errors.png)
* [Empty progress](progress-dashboard-empty.png)

The PNGs are production-renderer output; the sample data contains no real student results. They have been inspected as images, including at phone display width. They have not been tested in a live Telegram client.
