# AutoPivot Studio Platform Measurements

These measurements are for the generated **4:3 AutoPivot showroom with the large raised circular platform**.
The reference image was 1448 × 1086. AutoPivot outputs 1280 × 960, also 4:3, so the same ratios can be used without crop distortion.

## Measured platform geometry

| Setting | Ratio | Approx. 1280×960 pixels | Purpose |
|---|---:|---:|---|
| Platform top left | 0.105 | x = 134 | Left edge of top-surface ellipse |
| Platform top top | 0.598 | y = 574 | Back/top edge of top-surface ellipse |
| Platform top right | 0.875 | x = 1120 | Right edge of top-surface ellipse |
| Platform top bottom | 0.820 | y = 787 | Front edge of top-surface ellipse |
| Platform outer left | 0.098 | x = 125 | Outer raised rim |
| Platform outer top | 0.592 | y = 568 | Outer raised rim |
| Platform outer right | 0.882 | x = 1129 | Outer raised rim |
| Platform outer bottom | 0.855 | y = 821 | Bottom/front of raised rim |
| Vehicle contact Y | 0.755 | y ≈ 725 | Intended tyre contact area on platform |

`PLATFORM_CONTACT_SINK_PIXELS=2` moves the robust contact line two pixels into the surface, so the effective default contact is about **y = 727** on the 1280×960 output.

## Vehicle scale

The code no longer scales a full-car image from the whole canvas width. It first measures the platform top width and then uses:

```env
PLATFORM_VEHICLE_WIDTH_RATIO=0.86
PLATFORM_VEHICLE_MAX_HEIGHT_RATIO=0.54
```

## Contact detection

The pipeline estimates a robust lower vehicle contact line from the alpha mask:

```env
PLATFORM_CONTACT_PERCENTILE=0.97
PLATFORM_CONTACT_ALPHA_THRESHOLD=96
```

This is intentionally different from using the absolute lowest transparent-mask pixel. The high alpha threshold ignores faint old-ground/shadow remnants, while the percentile reduces sensitivity to one-pixel segmentation spikes.

## Platform masks

Two masks are created automatically in `autopivot_backend.py`; no separate mask image is required:

1. **Top-surface ellipse mask** — clips generated contact/ambient shadows so they stay on the platform.
2. **Front-rim ellipse-ring mask** — repaints the original platform rim after the car, allowing a small natural foreground overlap when a tyre reaches the rim.
