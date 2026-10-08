"""Export the raw vehicle cutouts the pipeline makes for one listing.

    .venv\Scripts\python.exe -m scripts.export_cutouts 3

Runs the same steps as a processing job up to the point the compositor takes
over (classify, detect, crop, remove background, cover plates) and writes, for
every exterior photograph, the cutout PNG plus a small JSON file into
storage\debug_cutouts\<listing id>\. Nothing in the database is changed.

Used to tune compositing.py against real cutouts without re-running the slow
models each time.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import autopivot_backend as backend  # noqa: E402  (loads .env and the models module)
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from api import storage  # noqa: E402
from api.config import BASE_DIR  # noqa: E402
from database.connection import get_engine  # noqa: E402
from database.models import Image as ImageRow  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__)
        return 2
    listing_id = int(sys.argv[1])
    out_dir = BASE_DIR / "storage" / "debug_cutouts" / str(listing_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    with Session(get_engine()) as session:
        rows = session.scalars(
            select(ImageRow).where(
                ImageRow.vehicle_listing_id == listing_id,
                ImageRow.image_type == "original",
            ).order_by(ImageRow.id)
        ).all()
        if not rows:
            print(f"Listing {listing_id} has no original photographs.")
            return 1
        work = [(r.id, r.image_kind, r.storage_path) for r in rows]

    print("Loading background model ...")
    backend.registry._load_birefnet()

    for image_id, kind, path in work:
        if kind not in (None, "exterior"):
            continue
        started = time.time()
        source = backend._open_image(storage.resolve(path).read_bytes()).convert("RGB")
        classified = backend._classify(source)
        if classified is not None and classified.kind != "exterior":
            continue
        vehicle = backend._detect_vehicle(source)
        if vehicle is None:
            print(f"  {image_id}: no vehicle")
            continue
        crop, coords = backend._crop_with_padding(source, vehicle["box"])
        cutout, model = backend._remove_background(crop)
        box = backend._box_in_crop(vehicle["box"], coords)
        angle = classified.angle if classified else None
        confidence = classified.angle_confidence if classified else None
        plates = backend._detect_plates(crop) + backend._detect_plate_zone_stickers(crop, box)
        plates = backend._filter_plates(
            plates, backend._box_area(vehicle["box"]), cutout,
            angle=angle, angle_confidence=confidence,
        )
        cutout = backend._apply_plate_treatment(cutout, plates, backend._brand_plate_overlay())

        cutout.save(out_dir / f"{image_id}.png")
        (out_dir / f"{image_id}.json").write_text(json.dumps({
            "image_id": image_id,
            "angle": angle,
            "angle_confidence": confidence,
            "vehicle_box_in_crop": [int(v) for v in box],
            "crop_coords": [int(v) for v in coords],
            "source_size": list(source.size),
            "plates": len(plates),
            "model": model,
        }, indent=2))
        print(f"  {image_id}: {angle} ({confidence}) saved in {time.time() - started:.0f}s")

    print(f"Done. Cutouts are in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

