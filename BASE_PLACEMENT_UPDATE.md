# Circular base placement update

This update is based on your attached alembic.zip and uses your supplied studio-full image. The existing React application, authentication, database, API and model setup are retained.

## Changes

- `compositing.py`: updated measured ellipse for the top surface, connected tyre placement, reduced the artificial floor reflection, added individual contact shadows and fixed double application of the cutout alpha.
- `platform_placement.py`: estimates two support points from the lower opaque silhouette, preferring dark pixels near the tyre regions. It uniformly scales the vehicle and finds a translation that puts all estimated contacts inside an inset ellipse. The existing perspective and relative contact heights are retained.
- `assets/backgrounds/studio-full.png`: your supplied background.
- `assets/backgrounds/studio-full-platform-mask.png`: visible top-surface mask, excluding the vertical front rim. Runtime regenerates the same ellipse at the output resolution from STUDIO_FULL.platform_box; editing this PNG alone does not change runtime geometry.
- `tests/test_platform_placement.py`: five geometry/compositing tests covering multiple aspect ratios and output sizes, contact shadows, empty cutouts and the separate close-up path.

The reference background is 1448 x 1086. The estimated top ellipse spans x=170..1286, y=657..881. These are hand-calibrated image coordinates, not physical measurements. Runtime uses ratios, so the standard 1280 x 960 output retains alignment.

Vehicle visible height is capped at 35% of the canvas and width at 84% of the platform diameter. A smaller inset ellipse keeps tyre contacts away from the rim. If the support points do not fit, the vehicle is reduced until they do. Each estimated contact receives a small dark shadow; all surface shadows are clipped to the base mask.

## Use

Extract into a new folder for a complete copy, or back up your running project and copy ONLY the files listed above into it. For an existing installation, keep its .env, virtual environment, downloaded weights and live database. Do not overwrite a live database with the database snapshot included in the uploaded archive.

Restart your backend using your existing run.bat or VS Code run command. Reprocess the original uploaded car image using the built-in full studio backdrop. Previously generated images are not changed automatically. Dealer-uploaded backgrounds use their existing placement unless explicitly associated with a measured platform preset.

## Validation and limits

All five new tests passed, including several dimensions/angles within the geometry test. Python compilation passed. Synthetic front and side silhouettes were rendered on the supplied background and visually inspected. These tests verify mask containment and contact shadow positioning; they are not a real-car quality benchmark. Your full model stack and GPU were not run in this environment.

Contact points are silhouette-based estimates, not a trained tyre detector. Missing tyres, opaque remnants of the original ground or an unsuitable camera perspective can still give an incorrect result. The update cannot restore tyres removed by segmentation or recover real camera geometry from a single cutout. Metadata identifies the method as lower_silhouette and records estimated contacts and placement for debugging.

Run geometry tests from the project folder:

    python -m unittest discover -s tests -p test_platform_placement.py -v
