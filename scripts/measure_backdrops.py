"""Measure the backdrops that were uploaded before anything measured them.

A backdrop's geometry — where its floor begins and where its horizon falls — is
worked out by `backdrop_analysis` when a dealer uploads it. Every backdrop added
before that existed carries nulls instead, and the compositor reads a null as
"never measured" and stands the vehicle on the assumed ground line, exactly as it
did before. That is the right default and it is also invisible: a library full of
existing backdrops shows no change whatever, which looks like the feature not
working rather than the feature declining to guess.

This measures them, once:

    python3 -m scripts.measure_backdrops              # report what would change
    python3 -m scripts.measure_backdrops --write      # actually write it

A backdrop a dealer has corrected by hand is never touched, with or without
--write. Their correction is better evidence than anything measured from the
pixels, and silently reverting it would be worse than never having offered the
correction at all.
"""

from __future__ import annotations

import argparse
import io
import sys

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

import backdrop_analysis
from api import storage
from database.connection import get_engine
from database.models import Backdrop


def measure(backdrop: Backdrop) -> backdrop_analysis.BackdropGeometry | None:
    """Read a backdrop off disk and measure it, or None if it cannot be read."""
    try:
        content = storage.resolve(backdrop.storage_path).read_bytes()
        with Image.open(io.BytesIO(content)) as image:
            return backdrop_analysis.analyse(image)
    except Exception as exc:
        print(f"  backdrop {backdrop.id} ({backdrop.name}) could not be read: {exc}")
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m scripts.measure_backdrops",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--write", action="store_true",
        help="write the measurements. Without it nothing is changed and the "
             "figures are only printed, so a run can be inspected first",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="re-measure backdrops that already carry a measurement. Corrections "
             "made by a dealer are still left alone",
    )
    args = parser.parse_args(argv)

    with Session(get_engine()) as session:
        rows = session.scalars(select(Backdrop).order_by(Backdrop.id)).all()

        pending = [
            b for b in rows
            if not b.geometry_overridden
            and (args.all or b.horizon_y_ratio is None)
        ]

        skipped = len(rows) - len(pending)
        print(f"{len(rows)} backdrops, {len(pending)} to measure, {skipped} left alone")

        measured = 0
        for backdrop in pending:
            geometry = measure(backdrop)
            if geometry is None:
                continue

            print(
                f"  {backdrop.id:>4} {backdrop.name[:28]:<28} "
                f"horizon {geometry.horizon_y_ratio:.3f} "
                f"({geometry.horizon_method}, confidence {geometry.horizon_confidence:.2f})  "
                f"floor {geometry.floor_top_y_ratio:.3f}"
            )

            if args.write:
                backdrop.horizon_y_ratio = round(geometry.horizon_y_ratio, 3)
                backdrop.horizon_confidence = round(geometry.horizon_confidence, 3)
                backdrop.horizon_method = geometry.horizon_method
                backdrop.floor_top_y_ratio = round(geometry.floor_top_y_ratio, 3)
                backdrop.floor_confidence = round(geometry.floor_confidence, 3)
                backdrop.camera_elevation_deg = (
                    None if geometry.camera_elevation_deg is None
                    else round(geometry.camera_elevation_deg, 2)
                )
            measured += 1

        if args.write:
            session.commit()
            print(f"\nwritten: {measured}")
        else:
            print(f"\nnothing written — {measured} would be. Re-run with --write.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
