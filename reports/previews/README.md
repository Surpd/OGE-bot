# Progress Widget preview

[Open the light-theme standalone interactive preview](progress-widget-preview.html) or [the dark-theme preview](progress-widget-preview-dark.html). Both use local sample data and the HTML/CSS/JS embedded in `app/bot/progress_widget.py`; switch tabs and open a history item to inspect the screens. No network or Telegram account is used.

The managed environment has Chromium installed but cannot complete a headless screenshot: even a minimal local HTML page stalls while its sandbox reports read-only process/font-cache errors. This preview is therefore an HTML artifact, not a Telegram-client screenshot. The Widget was not live-tested in Telegram.

## Unified progress PNG dashboard

The current all-numbers screen is rendered by Pillow in `app/bot/progress_image.py`. Run `uv run python scripts/generate_progress_previews.py` to regenerate these three fictional-data states:

* [Empty progress](progress-empty.png), [360 px](progress-empty-360.png), [390 px](progress-empty-390.png), [430 px](progress-empty-430.png)
* [Partially filled progress](progress-partial.png), [360 px](progress-partial-360.png), [390 px](progress-partial-390.png), [430 px](progress-partial-430.png)
* [All numbers with varied results](progress-full.png), [360 px](progress-full-360.png), [390 px](progress-full-390.png), [430 px](progress-full-430.png)

The source images are 900 px wide and show all 19 numbers in one 3-column grid. Phone-width files are LANCZOS resizes of the renderer output, checked visually at 360, 390 and 430 px. Sample data is synthetic and contains no student records. These previews are not screenshots from a live Telegram client.

[Previous and current overview at 360 px](progress-comparison.png).
