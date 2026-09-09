# Capture app — plan

A mobile application for dealership employees: photograph a vehicle from
guided angles, send the photographs to the existing pipeline, get processed
listings back.

**Read `docs/HANDOVER.md` first** for the system this attaches to, and
`docs/REALISM_PLAN.md` for why the capture metadata matters.

---

## Why this exists, and why it is not just another upload button

The client asked for it directly, recorded in APA-158:

> "The platform input should be two-way. One should be if I upload image
> manually or if I took the photo from the mobile app, it should directly go
> to the DMS and it should do all the thing, return the output. The second way
> is to extract photos from the link."

But the more important reason is technical. `docs/REALISM_PLAN.md` Phase 1
spends four to six days estimating **camera elevation** from the eccentricity
of wheel ellipses, because a dealer's photographs come from someone crouching
for one shot, standing for the next and holding the phone overhead for the
third — and the resulting horizon mismatch is what stops a composite looking
photographed.

**A phone does not need to estimate that. It knows.** The accelerometer reports
device pitch; EXIF reports focal length. Captured alongside the photograph,
the compositor gets a measured horizon rather than an inferred one.

So this is not a second way to upload. It is the input path that makes the
realism work reliable, because controlled capture beats reconstruction. It is
also the most likely explanation for why commercial competitors look good:
they control how the photograph is taken.

---

## Framework

**React Native with Expo**, using a development build rather than Expo Go.

| Considered | Verdict |
|---|---|
| **React Native + Expo** | **Chosen.** The team writes React 19 and TypeScript already — the entire web client is that. API response types can be shared with `frontend/src/api/client.ts` rather than redefined. Expo removes most native build setup, and over-the-air updates make demonstrating easy. |
| Flutter | Technically the strongest for custom camera overlays, because it renders every pixel itself rather than bridging to native views. Rejected because Dart is a new language for all four team members, and the sprint already introduces on-device inference and a camera pipeline. Three unknowns at once is one too many. |
| Capacitor | Would reuse the existing React client directly and reach a working demo fastest. Rejected because capture guidance is the point of this app, and a web view inside a shell is the wrong tool for a live camera overlay. |
| .NET MAUI, Kotlin Multiplatform | No advantage here for this team. |

**These are alternatives, not complements.** Building in two frameworks means
writing the app twice for the same result — no code is shared between them.

A **two-day documented comparison** is worth doing anyway, building the same
camera screen in React Native and Flutter and writing up the difference. Not as
a hedge, but because the Sprint 2 report has an *Industry Resource Evaluation &
Research* section that compared vision models, and the same treatment of a
framework choice is evidence rather than assertion.

### Libraries

- `react-native-vision-camera` — camera, and **frame processors**: worklets that
  run on the camera thread, which is what makes on-device inference on a live
  preview viable in React Native.
- `react-native-fast-tflite` or ONNX Runtime — running the quantised detector.
- `expo-sensors` — device pitch for the tilt guide.
- `expo-file-system` — the upload queue.
- `expo-dev-client` — required, because VisionCamera ships native code and
  therefore cannot run in Expo Go.

Versions to be confirmed at the point of building; this list is the shape, not
a lockfile.

---

## Capture guidance

Three layers, cheapest first. Each is useful alone, and they compose.

### G1 — Ghost silhouette overlay

A translucent car outline on the viewfinder for each requested angle. The
employee lines the vehicle up and shoots. No inference, works offline, and it is
what most vehicle inspection applications actually do because it works.

The five angles already exist as a vocabulary in `classification.py`: `front`,
`front_quarter`, `side`, `rear_quarter`, `rear`. The app requests them in a
fixed order so a listing arrives complete and consistent.

### G2 — Tilt guide

A level indicator driven by the accelerometer, keeping the phone at a
consistent pitch across every shot in a listing.

**This is the layer that matters most to the rest of the system**, and it is
also the cheapest. It gives consistent capture to the employee and a measured
camera elevation to the compositor.

### G3 — On-device detection

A small quantised detector on the camera feed, confirming the vehicle is
present, centred and filling enough of the frame before the shutter is enabled.
Green outline when the shot is good.

Runs in a VisionCamera frame processor. Needs a quantised model — YOLO11n or
MobileNet-SSD converted to TFLite or ONNX — and has a battery cost, so it should
be throttled to a few frames per second rather than every frame. Detection only:
confirming the *angle* on device is a further step and is not required, because
G1 already tells the employee which angle to shoot and the server confirms it
afterwards.

### G5 — Server verdict (later)

Photograph goes up, the existing YOLO and CLIP models return a verdict, the
employee retakes if needed. **No new models.** Depends on signal, so it belongs
after the offline path is solid.

---

## The two things that will bite

### Signal on a dealership lot is poor

An employee photographing twenty vehicles behind a shed will lose work unless
photographs queue on device and upload when a connection returns. This is a
requirement, not a refinement.

- Photographs written to local storage immediately on capture, with their
  metadata.
- A queue that survives the app being closed or killed.
- Background upload where the platform allows it.
- Visible per-listing state: captured, queued, uploading, processed.

### Photographs are large

A modern phone photograph is 4–8 MB. Twenty vehicles at seven angles is over
half a gigabyte.

- Decide whether to downscale on device. The pipeline segments at 1024×1024 and
  the compositor outputs 1280×960 for studio presets, so a 12-megapixel original
  carries detail that is discarded — but plate detection benefits from
  resolution, and so would the matting work in Phase 3 of the realism plan.
  **Measure before deciding.** Sending 2048px on the long edge is the likely
  compromise.
- Chunked or resumable upload, not a single multipart POST that fails at 95%.

---

## Backend changes

Smaller than expected, because the existing endpoints largely fit.

**1. Capture metadata on `images`.** Device pitch, requested angle, focal
length, capture timestamp, device model. A single JSON column is simplest —
these are attributes of a photograph, not relational data.

**2. `compositing.py` prefers measured metadata over estimation.** Phase 1 of
the realism plan already specifies a fallback chain; captured pitch becomes the
first entry, ahead of wheel-ellipse estimation. Photographs uploaded from the
web keep working exactly as they do now.

**3. Longer-lived authentication.** Employees will not sign in daily. A refresh
token, and a device-scoped session that can be revoked when a phone is lost.

**4. Per-employee accounts.** Currently every user of a dealership shares one
account — `HANDOVER.md` §9.7. A capture app makes that untenable: you want to
know who photographed what, and to revoke one employee without changing a
shared password.

**5. Resumable upload endpoint**, or chunked upload against the existing one.

**6. Authentication on the ML routes.** `HANDOVER.md` §9.1 lists this as the
top known gap. A published mobile application makes it urgent rather than
theoretical.

---

## Order of work

1. **Framework spike, two days.** Same camera screen in both, written up.
2. **Plumbing.** Sign in, list vehicles, capture, queue, upload, see the result.
   No guidance yet. Proves the path end to end.
3. **G1 and G2.** Silhouette overlay and tilt guide. Send the pitch with the
   photograph and record it.
4. **Compositor reads the metadata.** Phase 1 of the realism plan, taking the
   measured value when present.
5. **G3.** On-device detection in a frame processor.
6. **G5** if the round trip proves fast enough in the field.

Steps 2 and 3 are the demonstrable sprint outcome. Step 4 is where the two
sprints meet and is worth showing side by side: the same vehicle composited
with an estimated horizon and with a measured one.

---

## What to measure

- **Capture-to-result time** over a real connection, not office wifi.
- **Upload success rate** on poor signal, with the queue enabled and disabled.
- **Horizon error**: measured pitch against the wheel-ellipse estimate on the
  same photograph. This quantifies what the app buys the realism work, and it is
  the strongest evidence for the report.
- **Battery cost** of G3, with the frame processor throttled and unthrottled.
- **Angle compliance**: how often an employee following the guidance produces a
  photograph the classifier agrees is the requested angle.

That last one is the honest test of whether the guidance works at all.
