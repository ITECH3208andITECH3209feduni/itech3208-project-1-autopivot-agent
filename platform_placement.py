"""Mask-constrained placement and rigid tyre-axis alignment."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


BASE_FRAME = {
    "horizontal_axis_degrees": 0.0,
    "vertical_axis_degrees": 90.0,
    "north_reference": "ceiling",
    "south_reference": "platform",
}


@dataclass(frozen=True)
class Contact:
    x: int
    y: int
    radius: float
    confidence: float
    method: str = "silhouette_lobe"


@dataclass
class Placement:
    vehicle: Image.Image
    x: int
    y: int
    contacts: list[Contact]
    target_height: float
    rendered_height: int
    scale_limited: bool


def _silhouette(image):
    alpha = np.asarray(image.convert("RGBA"))[:, :, 3] >= 128
    count, labels, stats, _ = cv2.connectedComponentsWithStats(alpha.astype("uint8"), 8)
    if count <= 1:
        raise ValueError("Cannot place an empty vehicle cutout")
    largest = int(stats[1:, cv2.CC_STAT_AREA].max())
    keep = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] >= max(4, largest * .002))
    keep = keep[keep != 0]
    if not keep.size:
        keep = np.array([1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])])
    return np.isin(labels, keep)


def _bounds(mask):
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _envelope(mask):
    present = mask.any(axis=0)
    return np.where(present, mask.shape[0] - 1 - mask[::-1].argmax(axis=0), -1)


def _visual_wheel_contacts(rgba, mask, bounds, envelope):
    """Find dark wheel columns that touch the lower edge of the cutout."""
    left, top, right, bottom = bounds
    width, height = right-left, bottom-top
    if width < 80 or height < 50:
        return []
    rgb = rgba[:, :, :3].astype(np.int16)
    dark = mask & (rgb.mean(axis=2) < 120) & ((rgb.max(axis=2)-rgb.min(axis=2)) < 42)
    integral = np.pad(np.cumsum(dark.astype(np.int32), axis=0), ((1, 0), (0, 0)))
    xs = np.arange(mask.shape[1]); lower = np.clip(envelope+1, 0, mask.shape[0])
    upper = np.clip(envelope-round(height*.35), top, mask.shape[0])
    score = np.where((xs >= left) & (xs < right) &
                     (envelope >= top+height*.44),
                     integral[lower, xs]-integral[upper, xs], 0).astype(np.float32)
    score = cv2.GaussianBlur(score[None, :], (0, 0), sigmaX=max(2., width*.012))[0]
    radius = max(4, round(width*.035))
    maxima = cv2.dilate(score[None, :], np.ones((1, radius*2+1), np.uint8))[0]
    peaks = np.flatnonzero((score >= maxima-.5) & (score >= max(8, height*.15)) &
                           (xs >= left) & (xs < right))
    groups = np.split(peaks, np.flatnonzero(np.diff(peaks) > 1)+1)
    candidates = []
    for group in groups:
        if not group.size:
            continue
        x = int(group[len(group)//2]); spread = max(6, round(width*.11))
        padded = np.pad(score, (spread, spread), mode="constant")
        centre = x+spread
        a = padded[centre-spread:centre-spread//2]
        b = padded[centre+spread//2:centre+spread]
        prominence = score[x]-max(float(a.min()), float(b.min()))
        if prominence < max(4., height*.015):
            continue
        confidence = float(np.clip(.57+prominence/max(height, 1), .57, .94))
        candidates.append((float(score[x]+prominence*.30),
                           Contact(x, int(envelope[x]), max(2., height*.045),
                                   confidence, "dark_tyre_candidate")))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return []
    selected = [candidates[0][1]]
    for _, contact in candidates[1:]:
        if abs(contact.x-selected[0].x) >= width*.17:
            selected.append(contact)
            break
    if len(selected) != 2:
        return []
    refined = []
    for p in selected:
        x0, x1 = max(left, p.x-round(height*.11)), min(right, p.x+round(height*.11)+1)
        y0, y1 = max(top, p.y-round(height*.32)), p.y-round(height*.025)
        patch = rgb[y0:y1, x0:x1]
        rim = ((patch.mean(axis=2) > 125) &
               ((patch.max(axis=2)-patch.min(axis=2)) < 65) & mask[y0:y1, x0:x1])
        _, rim_x = np.where(rim)
        centre = round(x0+rim_x.mean()) if rim_x.size > height*.2 else p.x
        window = np.arange(max(left, centre-round(height*.055)),
                           min(right, centre+round(height*.055)+1))
        foot_y = int(envelope[window].max())
        foot = window[envelope[window] >= foot_y-1]
        foot_x = int(foot[len(foot)//2])
        refined.append(Contact(foot_x, foot_y, p.radius, p.confidence, p.method))
    return sorted(refined, key=lambda p: p.x)


def detect_contacts(image: Image.Image) -> list[Contact]:
    """Prefer two visual tyre candidates; fall back to visible support lobes."""
    rgba = np.asarray(image.convert("RGBA"))
    mask = _silhouette(image)
    left, top, right, bottom = _bounds(mask)
    width, height = right - left, bottom - top
    envelope = _envelope(mask)
    visual = _visual_wheel_contacts(rgba, mask, (left, top, right, bottom), envelope)
    if visual:
        return visual
    radius = max(1, round(width * .006))
    smooth = np.array([
        np.median(envelope[max(left, x-radius):min(right, x+radius+1)])
        for x in range(left, right)
    ])
    neighbourhood = max(3, round(min(width * .09, height * .23)))
    maxima = cv2.dilate(smooth.astype("float32")[None, :],
                        np.ones((1, 2 * neighbourhood + 1), np.uint8))[0]
    peaks = np.flatnonzero((smooth >= maxima - .5) & (smooth >= top + height * .57))
    groups = np.split(peaks, np.flatnonzero(np.diff(peaks) > 1) + 1)
    candidates = []
    for group in groups:
        if not group.size:
            continue
        centre = int(group[len(group)//2])
        depth = smooth[centre]
        span = max(neighbourhood + 1, round(min(width * .17, height * .4)))
        before = smooth[max(0, int(group[0])-span):int(group[0])+1]
        after = smooth[int(group[-1]):min(width, int(group[-1])+span+1)]
        prominence = depth - max(float(before.min()), float(after.min()))
        if prominence < max(2, height * .018):
            continue
        lo, hi = max(left, left+centre-radius), min(right, left+centre+radius+1)
        xs = np.arange(lo, hi)
        xs = xs[np.abs(envelope[xs] - depth) <= max(2, height * .012)]
        if not xs.size:
            continue
        x = int(xs[len(xs)//2]); y = int(envelope[x])
        patch = rgba[max(top, y-max(3, round(height*.045))):y+1,
                     max(left, x-radius):min(right, x+radius+1), :3]
        dark = float(patch.mean()) < 115
        if not dark and prominence < height * .07:
            continue
        cutoff = depth - max(2, height * .032)
        a = b = centre
        while a > 0 and smooth[a-1] >= cutoff:
            a -= 1
        while b < width-1 and smooth[b+1] >= cutoff:
            b += 1
        foot_radius = float(np.clip((b-a+1)/2, height*.015, height*.13))
        confidence = min(.92, .48 + (.20 if dark else 0) + prominence / height)
        candidates.append(Contact(x, y, foot_radius, confidence))
    selected = []
    for contact in sorted(candidates, key=lambda p: p.confidence, reverse=True):
        if all(abs(contact.x - other.x) > max(height*.10, contact.radius+other.radius)
               for other in selected):
            selected.append(contact)
        if len(selected) == 4:
            break
    if len(selected) >= 2:
        return sorted(selected, key=lambda p: p.x)

    for low, high in ((.04, .44), (.56, .96)):
        xs = np.arange(left + int(width*low), min(right, left + int(width*high) + 1))
        depths = smooth[xs-left]
        if not xs.size:
            continue
        near = xs[depths >= depths.max() - max(1, height*.01)]
        x = int(near[len(near)//2]); y = int(envelope[x])
        if y >= top + height*.57 and all(abs(x-p.x) > height*.15 for p in selected):
            selected.append(Contact(x, y, max(2, height*.045), .25, "support_fallback"))
    if not selected:
        x = left + int(np.argmax(smooth))
        selected = [Contact(x, int(envelope[x]), max(2, height*.035), .15, "support_fallback")]
    return sorted(selected, key=lambda p: p.x)


def _tall_quarter_far_tyre_anchor(image: Image.Image, supports: list[Contact]):
    """Find one missed far tyre in a tall/quarter view without changing normal cars."""
    try:
        rgba_image = image.convert("RGBA")
        rgba = np.asarray(rgba_image)
        mask = _silhouette(rgba_image)
        left, top, right, bottom = _bounds(mask)
    except ValueError:
        return None

    width, height = right-left, bottom-top
    if width < 80 or height < 50:
        return None
    aspect = width / max(height, 1)
    if aspect >= 1.80:
        return None

    reliable = sorted((
        p for p in supports
        if p.method not in {"support_fallback", "virtual_axle_contact", "far_tyre_anchor"}
        and p.confidence >= .55
    ), key=lambda p: p.x)

    if len(reliable) >= 2 and reliable[-1].x - reliable[0].x >= width * .22:
        return None

    rgb = rgba[:, :, :3].astype(np.int16)
    mean = rgb.mean(axis=2)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    dark = mask & (mean < 112) & (chroma < 48)
    dark[:max(0, top + round(height * .34)), :] = False

    kernel_size = max(1, round(height * .012))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size * 2 + 1, kernel_size * 2 + 1)
    )
    closed = cv2.morphologyEx(dark.astype("uint8"), cv2.MORPH_CLOSE, kernel)
    count, labels, stats, centres = cv2.connectedComponentsWithStats(closed, 8)

    candidates = []
    for index in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[index])
        if area < max(18, round(height * height * .0012)):
            continue
        if w < height * .055 or h < height * .055:
            continue
        if w > height * .34 or h > height * .34:
            continue
        blob_aspect = w / max(h, 1)
        if not .42 <= blob_aspect <= 2.25:
            continue
        fill = area / max(w*h, 1)
        if fill < .12:
            continue

        cx, cy = centres[index]
        if cy < top + height * .43:
            continue

        separation = min((abs(cx-p.x) for p in reliable), default=width)
        if separation < max(width * .075, height * .14):
            continue

        patch = rgb[y:y+h, x:x+w]
        neutral_mid = (
            (patch.mean(axis=2) > 82) & (patch.mean(axis=2) < 205) &
            ((patch.max(axis=2)-patch.min(axis=2)) < 70)
        )
        rim_fraction = float(np.count_nonzero(neutral_mid) / max(neutral_mid.size, 1))
        if rim_fraction < .025:
            continue

        component = labels[y:y+h, x:x+w] == index
        yy, xx = np.where(component)
        if not yy.size:
            continue
        contact_y = y + int(np.percentile(yy, 98))
        contact_x = x + int(round(np.median(xx[yy >= np.percentile(yy, 88)])))
        radius = float(np.clip(max(w, h) * .24, height * .018, height * .075))

        shape_score = 1.0 - min(abs(np.log(max(blob_aspect, 1e-6))), 1.0)
        score = separation / max(width, 1) + shape_score * .35 + rim_fraction * .25
        candidates.append((score, Contact(
            int(contact_x), int(contact_y), radius, .52, "far_tyre_anchor"
        )))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _trim_axis_padding(image: Image.Image) -> Image.Image:
    """Trim transparent camera margins without changing vehicle pixels."""
    rgba = image.convert("RGBA")
    bbox = rgba.getchannel("A").point(lambda a: 255 if a > 4 else 0).getbbox()
    if bbox is None:
        raise ValueError("Cannot align an empty vehicle cutout")
    return rgba.crop((max(0, bbox[0] - 2), max(0, bbox[1] - 2),
                      min(rgba.width, bbox[2] + 2),
                      min(rgba.height, bbox[3] + 2)))


def _principal_axis(mask):
    """Return the dominant in-plane silhouette angle and its confidence."""
    ys, xs = np.where(mask)
    if xs.size < 3:
        return None, 0.0
    points = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
    covariance = np.cov(points, rowvar=False)
    values, vectors = np.linalg.eigh(covariance)
    major_index = int(np.argmax(values))
    major_value = max(float(values[major_index]), 0.0)
    minor_value = max(float(values[1 - major_index]), 1e-9)
    vector = vectors[:, major_index]
    if vector[0] < 0:
        vector = -vector
    angle = float(np.degrees(np.arctan2(vector[1], vector[0])))
    confidence = float(np.sqrt(major_value / minor_value))
    return angle, confidence


def _add_virtual_axle_contacts(image: Image.Image, supports: list[Contact]):
    """Add geometry-only opposite-side axle anchors."""
    real = [p for p in supports if p.method != "virtual_axle_contact"]
    reliable = [p for p in real if p.method != "support_fallback" and p.confidence >= .55]
    if not reliable:
        return list(supports), []
    try:
        left, _top, right, _bottom = _bounds(_silhouette(image))
    except ValueError:
        return list(supports), []
    centre_x = (left + right - 1) / 2.0
    virtual = []
    for p in reliable:
        mirrored_x = int(round(2.0 * centre_x - p.x))
        if not (left <= mirrored_x < right):
            continue
        if abs(mirrored_x - p.x) < max(8, round(p.radius * 2.0)):
            continue
        virtual.append(Contact(
            mirrored_x,
            p.y,
            max(1.0, p.radius * .85),
            min(.48, p.confidence * .70),
            "virtual_axle_contact",
        ))
    combined = list(real) + virtual
    combined.sort(key=lambda p: p.x)
    return combined, virtual


def _finish_axis_result(image, supports, info):
    """Attach narrowly inferred far-tyre and virtual axle placement anchors."""
    supports = list(supports)
    far_anchor = _tall_quarter_far_tyre_anchor(image, supports)
    if far_anchor is not None:
        supports.append(far_anchor)
        supports.sort(key=lambda p: p.x)
        info["far_tyre_anchor"] = {
            "x": far_anchor.x, "y": far_anchor.y, "method": far_anchor.method
        }
    else:
        info["far_tyre_anchor"] = None

    combined, virtual = _add_virtual_axle_contacts(image, supports)
    info["virtual_axle_contacts"] = [
        {"x": p.x, "y": p.y, "method": p.method} for p in virtual
    ]
    if info.get("applied"):
        info["contacts_after"] = [
            {"x": p.x, "y": p.y, "method": p.method} for p in combined
        ]
    return image, combined, info


def correct_axis(
    image: Image.Image,
    *,
    angle: str | None = None,
    pre_deskew_applied: bool = False,
):
    """Apply one conservative rigid roll correction, never perspective flattening."""
    rgba_image = _trim_axis_padding(image)
    supports = detect_contacts(rgba_image)
    reliable = sorted((p for p in supports if p.method != "support_fallback"
                       and p.confidence >= .55), key=lambda p: p.x)
    view = (angle or "").strip().lower()
    info = {
        "applied": False,
        "reason": "insufficient_vehicle_axis",
        "target_axis_degrees": 0.0,
        "rotation_degrees": 0.0,
        "shape_preserved": True,
        "axis_source": "visible_tyre_axle_line",
        "base_frame": dict(BASE_FRAME),
        "view_angle": view or None,
        "contacts_before": [
            {"x": p.x, "y": p.y, "method": p.method} for p in supports
        ],
    }
    mask = _silhouette(rgba_image)
    left, top, right, bottom = _bounds(mask)
    width, height = right - left, bottom - top
    principal_before, axis_confidence = _principal_axis(mask)
    info["axis_confidence"] = round(axis_confidence, 3)
    if principal_before is None or width < 80 or height < 50:
        return _finish_axis_result(rgba_image, supports, info)

    if pre_deskew_applied:
        info["reason"] = "pre_deskew_already_applied"
        info["axis_source"] = "pre_deskew_preserved"
        return _finish_axis_result(rgba_image, supports, info)

    if view in {"front", "rear"}:
        info["reason"] = "front_rear_orientation_preserved"
        info["axis_source"] = "view_angle_guard"
        return _finish_axis_result(rgba_image, supports, info)
    if view in {"front_quarter", "rear_quarter"}:
        info["reason"] = "quarter_perspective_preserved"
        info["axis_source"] = "view_angle_guard"
        return _finish_axis_result(rgba_image, supports, info)

    before = None
    if len(reliable) >= 2:
        first, last = reliable[0], reliable[-1]
        dx = last.x - first.x
        dy = last.y - first.y
        min_span = width * (.34 if view == "side" else .24)
        if dx >= max(16, min_span):
            visible_angle = float(np.degrees(np.arctan2(dy, dx)))
            info["visible_axle_angle_degrees"] = round(visible_angle, 3)
            info["contact_span_ratio"] = round(dx / max(width, 1), 3)

            if view == "side":
                if abs(visible_angle) < 2.25:
                    info["reason"] = "side_axis_within_perspective_deadband"
                    return _finish_axis_result(rgba_image, supports, info)
                if abs(visible_angle) > 8.0:
                    info["reason"] = "side_axis_exceeds_safe_roll_limit"
                    return _finish_axis_result(rgba_image, supports, info)
                before = visible_angle
                info["axis_source"] = "side_view_tyre_consensus"
            else:
                perspective_tolerance = max(8, round(height * .05))
                if abs(dy) > perspective_tolerance:
                    info["axis_source"] = "perspective_tyre_line_ignored"
                    info["reason"] = "perspective_slope_not_roll"
                    return _finish_axis_result(rgba_image, supports, info)
                if abs(visible_angle) < 2.50:
                    info["reason"] = "axis_within_perspective_deadband"
                    return _finish_axis_result(rgba_image, supports, info)
                before = visible_angle
                info["axis_source"] = "visible_tyre_axle_line"

    if before is None:
        if view == "side":
            info["reason"] = "side_view_needs_two_reliable_tyres"
            return _finish_axis_result(rgba_image, supports, info)

        if axis_confidence < 1.18 or width / max(height, 1) < 1.12 or abs(principal_before) > 75:
            info["reason"] = "axis_not_reliably_longitudinal"
            info["angle_before_degrees"] = round(principal_before, 3)
            return _finish_axis_result(rgba_image, supports, info)
        if abs(principal_before) < 2.50:
            info["reason"] = "principal_axis_within_perspective_deadband"
            info["angle_before_degrees"] = round(principal_before, 3)
            return _finish_axis_result(rgba_image, supports, info)
        before = float(principal_before)
        info["axis_source"] = "silhouette_principal_axis_fallback"

    target_axis = float(BASE_FRAME["horizontal_axis_degrees"])
    rotation = before - target_axis
    info["target_axis_degrees"] = target_axis
    info["angle_before_degrees"] = round(before, 3)

    output = rgba_image.rotate(
        rotation,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=(0, 0, 0, 0),
    )
    rotated_width, rotated_height = output.size
    alpha_bbox = output.getchannel("A").point(lambda a: 255 if a > 4 else 0).getbbox()
    if alpha_bbox is None:
        raise ValueError("Rigid axis rotation produced an empty vehicle cutout")
    crop_box = (max(0, alpha_bbox[0] - 2), max(0, alpha_bbox[1] - 2),
                min(output.width, alpha_bbox[2] + 2),
                min(output.height, alpha_bbox[3] + 2))
    output = output.crop(crop_box)
    radians = np.deg2rad(rotation)
    cos_a, sin_a = float(np.cos(radians)), float(np.sin(radians))
    source_centre = ((rgba_image.width - 1) / 2., (rgba_image.height - 1) / 2.)
    rotated_centre = ((rotated_width - 1) / 2., (rotated_height - 1) / 2.)
    revised = []
    for p in supports:
        dxp, dyp = p.x - source_centre[0], p.y - source_centre[1]
        rx = cos_a * dxp + sin_a * dyp + rotated_centre[0] - crop_box[0]
        ry = -sin_a * dxp + cos_a * dyp + rotated_centre[1] - crop_box[1]
        revised.append(Contact(round(rx), round(ry), p.radius, p.confidence, p.method))
    revised.sort(key=lambda p: p.x)
    revised_reliable = sorted(
        (p for p in revised if p.method != "support_fallback"
         and p.method != "virtual_axle_contact" and p.confidence >= .55),
        key=lambda p: p.x,
    )
    if len(revised_reliable) >= 2 and revised_reliable[-1].x != revised_reliable[0].x:
        after = float(np.degrees(np.arctan2(
            revised_reliable[-1].y - revised_reliable[0].y,
            revised_reliable[-1].x - revised_reliable[0].x)))
    else:
        after, _ = _principal_axis(_silhouette(output))
        after = float(after or 0.0)
    info.update(
        applied=True,
        reason="rigid_rotation",
        rotation_degrees=round(rotation, 3),
        angle_after_degrees=round(after, 3),
    )
    return _finish_axis_result(output, revised, info)

def contacts(image):
    """Compatibility API: contact coordinates relative to the cutout."""
    try:
        return [(p.x, p.y) for p in detect_contacts(image)]
    except ValueError:
        return []


def ellipse_mask(box, size):
    mask = Image.new("L", size, 0)
    w, h = size
    ImageDraw.Draw(mask).ellipse(tuple(round(v*(w if i % 2 == 0 else h))
                                       for i, v in enumerate(box)), fill=255)
    return mask


def _tall_view_height_factor(aspect: float) -> float:
    """Scale guard for tall/narrow front-quarter vehicle silhouettes."""
    if not np.isfinite(aspect) or aspect >= 1.80:
        return 1.0
    low_aspect = 1.35
    min_factor = .78
    t = float(np.clip((aspect - low_aspect) / (1.80 - low_aspect), 0.0, 1.0))
    return min_factor + (1.0 - min_factor) * t


def _perspective_high_side_guard(vehicle: Image.Image, supports: list[Contact]):
    """Return a placement-only anchor for the visually high side of a tall view."""
    try:
        silhouette = _silhouette(vehicle)
        left, top, right, bottom = _bounds(silhouette)
    except ValueError:
        return None

    width, height = right-left, bottom-top
    if width < 80 or height < 50:
        return None

    envelope = _envelope(silhouette)
    deepest = max((p.y for p in supports if p.method != "virtual_axle_contact"),
                  default=bottom-1)

    bands = []
    for side, lo, hi in (("left", .05, .28), ("right", .72, .95)):
        xs = np.arange(left + round(width*lo), min(right, left + round(width*hi)))
        xs = xs[(xs >= 0) & (xs < envelope.size) & (envelope[xs] >= 0)]
        if xs.size < 4:
            continue
        vals = envelope[xs]
        low_edge = float(np.percentile(vals, 88))
        near = xs[np.abs(vals-low_edge) <= max(2., height*.012)]
        if not near.size:
            near = np.array([xs[int(np.argmax(vals))]])
        x = int(near[len(near)//2])
        y = int(envelope[x])
        if y < top + height*.54:
            continue
        bands.append((side, x, y))

    if len(bands) < 2:
        return None

    side, x, y = min(bands, key=lambda item: item[2])
    if deepest - y < max(7, round(height*.10)):
        return None

    return Contact(x, y, max(2., height*.025), .20, "perspective_high_side_guard")


def place(cutout, box, size, *, surface_mask=None, scene_mask=None,
    target_height=None, width_ratio=.86, reference_aspect=3.2, contact_hints=None,
          height_ratio=.48, angle=None):
    """Fit to full-frame mask pixels; keep every contact on the surface."""
    cw, ch = size
    if surface_mask is None:
        surface_mask = ellipse_mask(box, size)
    if surface_mask.size != size or (scene_mask is not None and scene_mask.size != size):
        raise ValueError("Placement masks must match the output canvas")
    surface = np.asarray(surface_mask.convert("L")) >= 250
    if not surface.any():
        raise ValueError("The platform surface mask is empty")
    if scene_mask is None:
        scene_mask = Image.new("L", size, 255)
    scene = np.asarray(scene_mask.convert("L")) >= 250
    distance = cv2.distanceTransform(surface.astype("uint8"), cv2.DIST_L2, 5)
    sx1, sy1, sx2, sy2 = _bounds(surface)
    surface_width, surface_height = sx2-sx1, sy2-sy1
    cx = (sx1+sx2-1)/2
    cy = (sy1+sy2-1)/2 + surface_height * .23
    left, top, right, bottom = _bounds(_silhouette(cutout))
    visible_w, visible_h = right-left, bottom-top
    tall_depth_guard_active = False
    if target_height is not None:
        requested = target_height
    else:
        width_limited_height = surface_width * width_ratio * visible_h / visible_w
        height_limited_height = ch * height_ratio

        aspect = visible_w / max(visible_h, 1)
        view = (angle or "").strip().lower()

        depth_guard_allowed = view not in {"front", "rear"}
        if (depth_guard_allowed and aspect < 1.80
                and height_limited_height <= width_limited_height):
            tall_depth_guard_active = True
            height_limited_height *= _tall_view_height_factor(aspect)

        requested = min(height_limited_height, width_limited_height)
    if not np.isfinite(requested) or requested <= 0:
        raise ValueError("Target vehicle height must be positive and finite")
    scale = min(requested/visible_h, surface_width*.97/visible_w, ch*.80/visible_h)
    for _ in range(65):
        vehicle = cutout.resize((max(1, round(cutout.width*scale)),
                                 max(1, round(cutout.height*scale))), Image.Resampling.LANCZOS)
        opaque = _silhouette(vehicle)
        vl, vt, vr, vb = _bounds(opaque)
        supports = ([Contact(round(p.x*vehicle.width/cutout.width),
                             round(p.y*vehicle.height/cutout.height),
                             max(1., p.radius*vehicle.width/cutout.width),
                             p.confidence, p.method) for p in contact_hints]
                    if contact_hints else detect_contacts(vehicle))
        vehicle_bounds = _bounds(opaque)
        vehicle_aspect = ((vehicle_bounds[2]-vehicle_bounds[0]) /
                          max(1, vehicle_bounds[3]-vehicle_bounds[1]))
        high_side_guard = (
            _perspective_high_side_guard(vehicle, supports)
            if tall_depth_guard_active and vehicle_aspect < 1.55 else None
        )
        centre_x = (vl+vr-1)/2
        centre_y = max(p.y for p in supports)
        desired_x = round(cx-centre_x)
        desired_y = round(cy-centre_y + surface_height * .015)
        shifts_x = {0, *[round(surface_width*f) for f in (-.06, -.03, .03, .06)]}
        shifts_y = {0, *[round(surface_height*f) for f in (-.16, -.08, .08, .16)]}
        shifts = sorted(((dx,dy) for dx in shifts_x for dy in shifts_y),
                        key=lambda v: ((v[0]/surface_width)**2 + (v[1]/surface_height)**2,
                                       abs(v[0]), abs(v[1]), v))
        for dx, dy in shifts:
            x, y = desired_x+dx, desired_y+dy

            if high_side_guard is not None:
                ax = round(x + high_side_guard.x)
                if 0 <= ax < cw:
                    surface_rows = np.flatnonzero(surface[:, ax])
                    if surface_rows.size:
                        top_surface_y = int(surface_rows[0])
                        bottom_surface_y = int(surface_rows[-1])
                        local_depth = max(1, bottom_surface_y-top_surface_y)
                        grounding_inset = max(
                            round(ch*.018),
                            round(local_depth*.42),
                        )
                        required_y = top_surface_y + grounding_inset
                        current_y = y + high_side_guard.y
                        if current_y < required_y:
                            y += required_y - current_y

            if x+vl < 0 or x+vr > cw or y+vt < ch*.10 or y+vb > ch:
                continue
            safe = True
            for p in supports:
                margin = max(3., ch*.012)
                for px in (p.x-p.radius, p.x, p.x+p.radius):
                    ax, ay = round(x+px), y+p.y
                    if not (0 <= ax < cw and 0 <= ay < ch) or distance[ay,ax] < margin:
                        safe = False
                        break
                if not safe:
                    break
            if not safe:
                continue
            patch = scene[y+vt:y+vb, x+vl:x+vr]
            if np.any(opaque[vt:vb, vl:vr] & ~patch):
                continue
            rendered = vb-vt
            placed_supports = supports
            if high_side_guard is not None:
                if all(abs(high_side_guard.x-p.x) > max(3, high_side_guard.radius)
                       for p in supports):
                    placed_supports = list(supports) + [high_side_guard]
                    placed_supports.sort(key=lambda p: p.x)
            return Placement(vehicle, x, y, placed_supports, float(requested), rendered,
                             rendered < requested*.985)
        scale *= .97
    raise ValueError("The vehicle cannot fit within the platform and scene masks")


def fit(cutout, box, size):
    """Backwards-compatible wrapper for earlier callers."""
    result = place(cutout, box, size)
    return result.vehicle, result.x, result.y, [(p.x, p.y) for p in result.contacts]


def _contact_details(vehicle, pts):
    if pts and isinstance(pts[0], Contact):
        return pts
    detected = detect_contacts(vehicle)
    return [min(detected, key=lambda p: abs(p.x-px)+abs(p.y-py)) for px,py in pts]


def _shadow_layer(alpha):
    layer = Image.new("RGBA", (alpha.shape[1], alpha.shape[0]), (0, 0, 0, 0))
    layer.putalpha(Image.fromarray(np.clip(alpha, 0, 255).astype("uint8")))
    return layer


def ground_shadow(size, vehicle, x, y, pts, *, angle=None):
    """One soft footprint, with guarded quarter-view shadow geometry."""
    supports = _contact_details(vehicle, pts)
    if not supports:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    left, top, right, bottom = _bounds(_silhouette(vehicle))
    height, width = bottom-top, right-left
    aspect = width / max(1, height)
    view = (angle or "").strip().lower()
    special_anchor_present = any(
        p.method in {"far_tyre_anchor", "perspective_high_side_guard"}
        for p in supports
    )
    tall_quarter = (
        view in {"front_quarter", "rear_quarter"}
        and (aspect < 1.55 or special_anchor_present)
    )

    footprint_supports = supports
    depth = height * (.045 + .035 / (1.0 + aspect*aspect))
    broad_strength = 48.
    core_strength = 88.
    broad_sigma_x = max(1., height*.043)
    broad_sigma_y = max(1., height*.032)
    core_sigma_x = max(1., height*.016)
    core_sigma_y = max(1., height*.012)
    footprint_radius_scale = 1.0

    if tall_quarter:
        primary = [
            p for p in supports
            if p.method not in {
                "virtual_axle_contact", "perspective_high_side_guard",
                "support_fallback", "far_tyre_anchor",
            }
        ]
        if len(primary) >= 2:
            footprint_supports = primary
        else:
            fallback = [
                p for p in supports
                if p.method not in {
                    "virtual_axle_contact", "perspective_high_side_guard",
                    "support_fallback",
                }
            ]
            if fallback:
                footprint_supports = fallback

        depth *= .72
        broad_strength = 34.
        core_strength = 62.
        broad_sigma_x = max(1., height*.036)
        broad_sigma_y = max(1., height*.024)
        core_sigma_x = max(1., height*.013)
        core_sigma_y = max(1., height*.009)
        footprint_radius_scale = .82

    cloud = []
    for p in footprint_supports:
        if p.method == "virtual_axle_contact":
            radius_scale = .62
        elif p.method == "perspective_high_side_guard":
            radius_scale = .72
        else:
            radius_scale = 1.0
        radius_scale *= footprint_radius_scale
        for a in np.linspace(0, 2*np.pi, 32, endpoint=False):
            cloud.append((x+p.x+max(p.radius*.70,height*.065)*radius_scale*np.cos(a),
                          y+p.y+depth*radius_scale*np.sin(a)))
    if not cloud:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    hull = cv2.convexHull(np.asarray(cloud, dtype="float32")).reshape(-1,2)
    footprint = Image.new("L", size, 0)
    ImageDraw.Draw(footprint).polygon([tuple(point) for point in hull], fill=255)
    field = np.asarray(footprint, dtype="float32") / 255.0
    broad = cv2.GaussianBlur(field, (0,0), sigmaX=broad_sigma_x,
                             sigmaY=broad_sigma_y) * broad_strength
    core = cv2.GaussianBlur(field, (0,0), sigmaX=core_sigma_x,
                            sigmaY=core_sigma_y) * core_strength
    return _shadow_layer(np.maximum(broad, core))

def contact_shadow(size, vehicle, x, y, pts, *, angle=None):
    """Short edge-following occlusion at every estimated tyre contact."""
    supports = _contact_details(vehicle, pts)
    if not supports:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    silhouette = _silhouette(vehicle)
    left, top, right, bottom = _bounds(silhouette)
    height = bottom-top
    width = right-left
    view = (angle or "").strip().lower()
    special_anchor_present = any(
        p.method in {"far_tyre_anchor", "perspective_high_side_guard"}
        for p in supports
    )
    tall_quarter = (
        view in {"front_quarter", "rear_quarter"}
        and (width / max(height, 1) < 1.55 or special_anchor_present)
    )
    quarter_shadow_candidate = (
        view in {"front_quarter", "rear_quarter"}
        or (not view and width / max(height, 1) < 2.10)
    )
    envelope = _envelope(silhouette)
    field = np.zeros((size[1], size[0]), dtype="float32")

    real_tyre_supports = sorted((
        p for p in supports
        if p.method not in {
            "virtual_axle_contact", "perspective_high_side_guard",
            "support_fallback", "far_tyre_anchor",
        } and p.confidence >= .55
    ), key=lambda q: q.x)
    far_visible_support = None
    if tall_quarter and len(real_tyre_supports) >= 2:
        highest = min(real_tyre_supports, key=lambda q: q.y)
        deepest = max(real_tyre_supports, key=lambda q: q.y)
        horizontal_span = max(q.x for q in real_tyre_supports) - min(q.x for q in real_tyre_supports)
        if (deepest.y - highest.y >= max(5, round(height*.045))
                and horizontal_span >= width*.16):
            far_visible_support = highest

    def stamp_far_contact(contact, strength):
        """Add a compact soft patch immediately beneath one far tyre foot."""
        contact_x = int(np.clip(contact.x, left, right - 1))
        anchor_y = int(np.clip(contact.y, top, bottom - 1))
        cx = x + contact_x
        cy = y + anchor_y + max(1, round(height*.004))
        rx = max(4, round(max(contact.radius*1.20, height*.026)))
        ry = max(2, round(height*.010))

        yy, xx = np.ogrid[:field.shape[0], :field.shape[1]]
        core = (((xx-cx)/max(1, rx))**2 + ((yy-cy)/max(1, ry))**2) <= 1.0
        field[core] = np.maximum(field[core], strength)

        direction = 1 if contact_x < (left+right)/2 else -1
        soft_cx = cx + direction*max(1, round(rx*.28))
        soft_rx = max(rx + 2, round(rx*1.55))
        soft_ry = max(ry + 1, round(ry*1.70))
        soft = (((xx-soft_cx)/max(1, soft_rx))**2 +
                ((yy-(cy+1))/max(1, soft_ry))**2) <= 1.0
        field[soft] = np.maximum(field[soft], strength*.38)

    for p in supports:
        if far_visible_support is p:
            stamp_far_contact(p, 118.)

        if tall_quarter and p.method == "far_tyre_anchor":
            stamp_far_contact(p, 104.)
            continue

        if tall_quarter and p.method == "perspective_high_side_guard":
            stamp_far_contact(p, 82.)
            continue

        if p.method == "virtual_axle_contact":
            contact_x = int(np.clip(p.x, left, right - 1))
            anchor_y = max(int(p.y), int(envelope[contact_x]))
            cx, cy = x + contact_x, y + anchor_y
            rx = max(2, round(p.radius * .8))
            ry = max(1, round(height * .012))
            yy, xx = np.ogrid[:field.shape[0], :field.shape[1]]
            ellipse = (((xx-cx)/max(1, rx))**2 + ((yy-(cy+1))/max(1, ry))**2) <= 1.0
            virtual_strength = 38. if tall_quarter else 58.
            field[ellipse] = np.maximum(field[ellipse], virtual_strength)
            continue
        radius = min(p.radius*.70, height*.075)
        radius = max(1., radius)
        columns = np.arange(max(left, int(np.ceil(p.x-radius))),
                            min(right, int(np.floor(p.x+radius))+1))
        columns = columns[np.abs(envelope[columns]-p.y) <= max(1.,height*.006)]
        if p.method == "support_fallback":
            strength = 42. if tall_quarter else 50.
        elif p.method == "perspective_high_side_guard":
            strength = 72. if tall_quarter else 115.
        elif p.method == "far_tyre_anchor":
            strength = 82. if tall_quarter else 150.
        else:
            strength = 155. if tall_quarter else 190.
        for px in columns:
            ax, ay = x+int(px), y+int(envelope[px])
            if not 0 <= ax < size[0]:
                continue
            reach = max(3, min(9, round(height*.021)))
            for dy in range(reach + 1):
                if 0 <= ay+dy < size[1]:
                    weight = max(0., 1. - (dy / (reach + 1))**1.6)
                    field[ay+dy,ax] = max(field[ay+dy,ax], strength*weight)
    if quarter_shadow_candidate:
        guard = _perspective_high_side_guard(vehicle, supports)
        if guard is not None:
            gx = int(np.clip(x + guard.x, 0, size[0]-1))
            gy = int(np.clip(y + guard.y, 0, size[1]-1))
            probe_rx = max(5, round(max(guard.radius*1.5, height*.040)))
            probe_depth = max(6, round(height*.035))
            x0 = max(0, gx-probe_rx)
            x1 = min(size[0], gx+probe_rx+1)
            y0 = max(0, gy)
            y1 = min(size[1], gy+probe_depth+1)
            local = field[y0:y1, x0:x1]
            local_peak = float(local.max()) if local.size else 0.0
            local_mean = float(local.mean()) if local.size else 0.0
            if local_peak < 72.0 and local_mean < 20.0:
                stamp_far_contact(guard, 118.)

    field = cv2.GaussianBlur(field, (0,0), sigmaX=max(.7,height*.0035),
                            sigmaY=max(.5,height*.002))
    return _shadow_layer(field)


def surface_shadow(size, vehicle, x, y, pts, *, angle=None):
    """Combine floor shadows once, behind the unchanged vehicle cutout."""
    ambient = np.asarray(ground_shadow(size, vehicle, x, y, pts, angle=angle).getchannel("A"))
    contact = np.asarray(contact_shadow(size, vehicle, x, y, pts, angle=angle).getchannel("A"))
    combined = np.maximum(ambient, contact).copy()
    occupied = Image.new("L", size, 0)
    occupied.paste(vehicle.getchannel("A"), (x,y))
    combined[np.asarray(occupied) >= 250] = 0
    return _shadow_layer(combined)

