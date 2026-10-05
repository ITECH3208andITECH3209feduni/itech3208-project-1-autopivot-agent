# APA-232 — Dealership Activity View: Metadata Only

## Scope and implementation

Platform administrators can expand Activity alongside each dealership in the existing platform administration page. Team management and onboarding remain available. The activity summary shows active users, vehicle listings, original uploads, processing job totals by status, and the latest job creation time. Counts include permanent dealership data only; public demo uploads are not included.

A separate paginated job table shows job ID, listing ID, processing type, status, review state and creation/start/completion timestamps. It supports all/pending/processing/completed/failed filters, 20 rows per page and manual refresh. Timestamps display in the viewer's local timezone. Summary totals cover the whole dealership and do not change with the job table filter.

### Backend API

- `GET /api/platform/dealerships/{id}/activity`
- `GET /api/platform/dealerships/{id}/jobs?limit=20&offset=0&status=failed`

Both endpoints use the existing database-backed `platform_admin` role guard. Inactive accounts and revoked sessions are rejected by the shared authentication dependency; initial password changes remain mandatory. Other roles receive 403 and an audit entry. Unknown dealerships receive 404. Job limits must be 1–100, offsets nonnegative and status one of the four supported values. Newest creation timestamp comes first, with descending job ID as a deterministic tie-breaker. Offset pagination is appropriate for this initial admin view; concurrent creation/deletion can shift page contents, so a future high-volume version can use cursor pagination.

All queries scope to the selected dealership. Job reads select only approved database columns, then serialize through a dedicated response schema. Summary queries use counts and a timestamp aggregate. No existing photo-bearing listing/job response schema is reused. Original image counts exclude generated outputs to avoid counting the same upload twice.

### Privacy and access restrictions

The platform activity API does not return photographs, thumbnails, file URLs, storage paths, original filenames, image IDs, vehicle descriptions, stock details, raw processing errors or raw model output. The UI offers no preview/download actions or links to dealership listings.

The existing `/api/files/{path}` endpoint checks ownership by dealership path prefix. Platform administrators have no dealership and cannot read any stored originals, processed images, backdrops or plate overlays. This story adds an explicit platform refusal and a persistent `platform_photo_access` denied audit entry. Refusals use the same 404 for existing and missing files. File paths are redacted from these new audit entries.

Successful activity/job metadata views are logged as `dealership_activity_viewed`, with the actor, dealership, route and timestamp. These read-audit records contain no photo content. Existing listing and backdrop APIs remain scoped to the caller's dealership. Existing public demo processing accepts user-supplied content; it does not grant access to stored dealership photographs and is outside this story.

No database migration or new dependency is required. Existing users, dealerships, listings, images, processing jobs and audit logs supply all required data.

## Consent design for a future sprint — not implemented

Photograph access remains disabled for every platform administrator. No consent UI, grant endpoint, support-photo endpoint or model-training export is introduced by APA-232. A metadata read or dealership onboarding must never be treated as photo consent.

Proposed future consent model:

| Field | Purpose |
| --- | --- |
| id, dealership_id | Identify the grant and its owning dealership |
| purpose | Separate `support` from `model_improvement`; grants are never interchangeable |
| granted_by_user_id, granted_at | Record the dealership administrator who authorized access |
| scope | Explicit selected image/listing IDs; avoid implicit access to all future uploads |
| authorized_platform_user_id | Limit support access to the intended administrator |
| expires_at | Bound access in time; an expired grant is denied |
| revoked_by_user_id, revoked_at | Support immediate revocation with preserved audit history |
| policy_version | Record which consent wording was accepted |

Only a ready, active dealership administrator may grant or revoke consent for their own dealership. Staff and platform administrators cannot grant consent on a dealership's behalf. Default is no grant. Separate explicit confirmation is required for each purpose and scope. Missing, mismatched, revoked or expired grants deny access.

A future photo-access service must verify the actor, purpose, resource ownership, scope, expiry and revocation on every access. Tokens/URLs must not bypass revocation; long-lived signed URLs are unsuitable for immediate revocation. Record grants, revocations and each successful/denied photo access. Keep originals, processed outputs and derived artifacts within the same permission boundary. Define retention and what can be withdrawn from model-improvement data before enabling that feature; consent revocation cannot automatically undo an already trained model.

## Local application and demo

1. Apply the supplied patch from the repository root with `git apply` after reviewing current changes. The patch was built against the uploaded main ZIP; if it does not apply, stop and reconcile the changed files rather than forcing it.
2. Run the targeted tests shown in the evidence file and build the frontend.
3. Start the normal backend and frontend, log in as the existing platform administrator, then select **Activity** on a dealership card.
4. Show the counts and job metadata. Filter by a status and demonstrate Refresh or pagination where enough jobs exist.
5. Show that activity contains no photograph preview/download. An empty dealership should show zero counts and no jobs; use existing real dealership jobs to demonstrate populated rows.
6. In browser developer tools, inspect `/api/platform/dealerships/{id}/jobs` and show only the approved fields. Automated tests cover direct file access denial; do not expose private file paths during a public demo.

No new platform account is created. No seed credentials or private photo data are added.
