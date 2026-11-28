# Rigby2D handoff

`bop-snap.rigby` is an editable Rigby2D work file converted from `../model/rig.json` and its PNG layers. It contains 16 point bones, 16 slots, textured weighted meshes, the 3-second/72-frame `loop`, and the attachment swaps. The fixed 768×768 film frame is centered at `{x: 384, y: -384}` with scale `1`, preserving the intended bottom crop.

## Reproduce the conversion

Rigby2D source: [official repository](https://github.com/jaisurya-dev-art/rigby2d), version `0.6.1`, commit `aaae35b57801859b89554c282b7af826f62974ae`. The checkout and dependencies are local under `.tmp/bop-rigby`; install scripts were disabled, and no global install was made.

From the project root in PowerShell:

```powershell
$env:RIGBY_SOURCE = 'D:\mitya\Projects\Oge Bot\.tmp\bop-rigby\rigby2d'
Push-Location $env:RIGBY_SOURCE
npm ci --ignore-scripts --no-audit --no-fund
Pop-Location
node experiments/bop-snap/tools/rigby/convert.mjs
Remove-Item Env:RIGBY_SOURCE
```

The converter also accepts `--rigby-source <path>`; without either override it uses `.tmp/bop-rigby/rigby2d`.

## Verification

- From the Rigby checkout, `node bin/rigby.js validate <path-to-bop-snap.rigby>` passed structure, image, JSON round-trip, and binary export checks with no warnings.
- CLI Chromium rendered 72/72 frames at 768×768. MCP stdio initialize/list, inspect, animation description, bone-key edit, attachment-swap edit, and validation passed on the converted project.
- Eight reference frames (0000, 0017, 0035–0038, 0044, 0071) were compared after a 3× native render and premultiplied-alpha Lanczos downsample to 768×768. Alpha bounding boxes matched within 1 px; silhouette IoU was 0.9976–0.9979; shared-visible-pixel RGB MAE was about 2.0–3.7 levels per channel.
- Native 3× downsampled frames are in `.tmp/bop-rigby/final-aa`. A thin straight mesh seam remains visible on the collar/chest at close inspection, so the separate CPU-composited render is the selected video master. The Rigby source and direct native render remain usable for editing and preview.

Documentation: [CLI](https://rigby2d.com/docs/cli.html), [MCP](https://rigby2d.com/docs/mcp.html), [meshes](https://rigby2d.com/docs/meshes.html), [file formats](https://rigby2d.com/docs/file-formats.html).
