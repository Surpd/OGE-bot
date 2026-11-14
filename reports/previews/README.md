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

The PNGs are production-renderer output; the sample data contains no real student results. Each screen is also saved as a real 375 px LANCZOS resize to inspect the scale Telegram uses on a phone. Full-size images and phone-width previews have been visually checked, including long history labels, a compact empty state, and large values. They have not been tested in a live Telegram client.

Phone-width previews:

* [Overview, 375 px](progress-dashboard-overview-375.png)
* [Numbers 1–7, 375 px](progress-dashboard-numbers-1-7-375.png)
* [Numbers 8–14, 375 px](progress-dashboard-numbers-8-14-375.png)
* [History, 375 px](progress-dashboard-history-375.png)
* [Errors, 375 px](progress-dashboard-errors-375.png)
* [Empty progress, 375 px](progress-dashboard-empty-375.png)
