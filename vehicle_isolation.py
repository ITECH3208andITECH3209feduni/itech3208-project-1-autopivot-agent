"""Remove pieces of *other* cars from a background-removed cutout."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

MAX_REMOVED_FRACTION = 0.10
MAX_INSIDE_OTHER_WIDTH = 0.50
MAIN_GROW_FRACTION = 0.006


def _iou_box(mask: np.ndarray, box: tuple[float, float, float, float]) -> float:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return 0.0
    mx1, my1, mx2, my2 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    bx1, by1, bx2, by2 = box
    iw = max(0.0, min(mx2, bx2) - max(mx1, bx1))
    ih = max(0.0, min(my2, by2) - max(my1, by1))
    inter = iw * ih
    union = (mx2 - mx1) * (my2 - my1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def remove_other_vehicles(
    cutout: Image.Image,
    instance_masks: list[np.ndarray],
    vehicle_box: tuple[float, float, float, float],
) -> tuple[Image.Image, int]:
    """Clear pixels that belong to other cars. Returns the cutout and how many pixels
    were cleared (0 when nothing changed).
    """
    if len(instance_masks) < 2:
        return cutout, 0
    rgba = np.array(cutout.convert("RGBA"))
    alpha = rgba[:, :, 3]
    if any(m.shape != alpha.shape for m in instance_masks):
        return cutout, 0

    scores = [_iou_box(m, vehicle_box) for m in instance_masks]
    main_index = int(np.argmax(scores))
    if scores[main_index] < 0.5:
        return cutout, 0
    main = instance_masks[main_index].astype(np.uint8)

    width = vehicle_box[2] - vehicle_box[0]
    grow = max(2, int(round(width * MAIN_GROW_FRACTION)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    main_grown = cv2.dilate(main, kernel) > 0

    bx1, by1, bx2, by2 = vehicle_box
    box_w = max(1.0, bx2 - bx1)
    others = np.zeros_like(main_grown)
    for i, mask in enumerate(instance_masks):
        if i == main_index:
            continue
        ys, xs = np.nonzero(mask)
        if xs.size == 0:
            continue
        inside = ((xs >= bx1) & (xs <= bx2) & (ys >= by1) & (ys <= by2)).mean()
        if inside > 0.85 and (xs.max() - xs.min()) > MAX_INSIDE_OTHER_WIDTH * box_w:
            continue  # part of our own car, not another one
        others |= mask.astype(bool)
    others = cv2.dilate(others.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0

    remove = others & ~main_grown & (alpha > 0)
    count = int(remove.sum())
    opaque = int((alpha > 128).sum())
    if count == 0 or opaque == 0 or count > opaque * MAX_REMOVED_FRACTION:
        return cutout, 0

    alpha = alpha.copy()
    alpha[remove] = 0

    near = cv2.dilate(remove.astype(np.uint8), np.ones((4 * grow + 1, 4 * grow + 1), np.uint8)) > 0
    k = max(3, int(round(width * 0.012))) | 1
    opened = cv2.morphologyEx(
        (alpha > 32).astype(np.uint8), cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)),
    ) > 0
    sliver = near & (alpha > 0) & ~opened
    alpha[sliver] = 0
    count += int(sliver.sum())

    lab = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2LAB).astype(np.float32)
    theirs = lab[remove].mean(axis=0)
    ours_px = main.astype(bool) & ~near & (alpha > 128)
    if ours_px.sum() > 100:
        ours = np.median(lab[ours_px], axis=0)
        border = cv2.dilate(remove.astype(np.uint8),
                            np.ones((6 * grow + 1, 6 * grow + 1), np.uint8)) > 0
        d_theirs = np.linalg.norm(lab - theirs, axis=2)
        d_ours = np.linalg.norm(lab - ours, axis=2)
        looks_theirs = border & (alpha > 0) & (d_theirs < 0.6 * d_ours)
        alpha[looks_theirs] = 0
        count += int(looks_theirs.sum())
    zone = cv2.dilate(remove.astype(np.uint8),
                      np.ones((8 * grow + 1, 8 * grow + 1), np.uint8)) > 0
    solid_now = alpha > 32
    cols = np.flatnonzero(solid_now.any(axis=0))
    if cols.size:
        tops = np.full(alpha.shape[1], -1, dtype=np.int64)
        tops[cols] = solid_now[:, cols].argmax(axis=0)
        win = max(5, int(round(width * 0.06))) | 1
        half = win // 2
        for x in np.flatnonzero(zone.any(axis=0)):
            if tops[x] < 0:
                continue
            lo, hi = max(0, x - half), min(alpha.shape[1], x + half + 1)
            neighbours = tops[lo:hi][tops[lo:hi] >= 0]
            smooth_top = int(np.median(neighbours))
            if tops[x] < smooth_top - 1:
                cut_rows = np.arange(tops[x], smooth_top - 1)
                cut_rows = cut_rows[zone[cut_rows, x]]
                count += int((alpha[cut_rows, x] > 0).sum())
                alpha[cut_rows, x] = 0

    solid = (alpha > 32).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid, 8)
    if n > 2:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha[(labels != largest) & (labels != 0)] = 0
    rgba[:, :, 3] = alpha
    return Image.fromarray(rgba, "RGBA"), count

