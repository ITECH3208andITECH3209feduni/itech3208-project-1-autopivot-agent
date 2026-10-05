# APA-232 verification evidence

Validation date: 5 October 2026.

## Automated checks

Command:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_platform_activity.py tests/test_platform_administration.py tests/test_dealership_user_management.py -q
```

Result in the isolated Linux verification environment: **42 passed, 1 warning in 70.18 seconds**. This includes 30 new APA-232 cases and 12 existing platform/dealership administration cases. The warning is a Starlette/httpx test-client deprecation; tests completed successfully. Installed core dependencies were taken from the repository's existing requirements file; no dependency files were changed.

New coverage:

- Exact allowlisted summary and job response fields, excluding sensitive sentinel values.
- Correct counts across two dealerships; original uploads counted separately from generated outputs.
- Status filtering, stable ordering for equal timestamps, pagination and invalid query parameters.
- Empty dealership and unknown dealership handling.
- Anonymous and forced-password-change access rejection.
- Dealership admin/staff denial against both own and other dealership activity endpoints, including audit records.
- Platform photo denial for actual files in both dealerships: originals, processed results, backdrops and overlays; missing files return the same response.
- Photo-denial logs redact file paths.
- Dealership users can still read their own files and cannot read another dealership's files.
- Existing listing/job reads cannot bypass platform restrictions; unsupported GET image-list requests return 405.
- Successful metadata reads produce audit records.

Frontend command:

```powershell
cd frontend
npm run build
```

Result: TypeScript check and Vite production build passed (73 modules, 1.46 seconds for Vite). No dependency change required. Python compilation and patch whitespace checks passed.

## Validation boundaries

The API tests use isolated SQLite data and a temporary photo directory. They do not mutate production data or depend on GPU models. The full ML suite, PostgreSQL runtime and interactive browser demo were not run. Frontend validation here is compilation/build, not browser interaction. Run the same tests in your Windows checkout, then follow the demo steps in `docs/APA-232-activity-and-consent.md` to confirm the UI with your local data.

No schema migration is introduced by APA-232.
