# Progress Widget preview

[Open the light-theme standalone interactive preview](progress-widget-preview.html) or [the dark-theme preview](progress-widget-preview-dark.html). Both use local sample data and the HTML/CSS/JS embedded in `app/bot/progress_widget.py`; switch tabs and open a history item to inspect the screens. No network or Telegram account is used.

The managed environment has Chromium installed but cannot complete a headless screenshot: even a minimal local HTML page stalls while its sandbox reports read-only process/font-cache errors. This preview is therefore an HTML artifact, not a Telegram-client screenshot. The Widget was not live-tested in Telegram.

## Unified progress PNG dashboard

The current all-numbers screen is rendered by Pillow in `app/bot/progress_image.py`. Run `uv run python scripts/generate_progress_previews.py` to regenerate the fictional-data states below:

* [Empty progress](progress-empty.png), [360 px](progress-empty-360.png), [390 px](progress-empty-390.png), [430 px](progress-empty-430.png)
* [Partially filled progress](progress-partial.png), [360 px](progress-partial-360.png), [390 px](progress-partial-390.png), [430 px](progress-partial-430.png)
* [All numbers with varied results](progress-full.png), [360 px](progress-full-360.png), [390 px](progress-full-390.png), [430 px](progress-full-430.png)

* [First and second part results at 430 px](progress-25-demo-430.png)

The current overview covers tasks 1–25. The 360, 390 and 430 px images are LANCZOS resizes of the 1200 px renderer output using fictional data.

[Historical comparison of two earlier 1–19 layouts at 360 px](progress-comparison.png).
