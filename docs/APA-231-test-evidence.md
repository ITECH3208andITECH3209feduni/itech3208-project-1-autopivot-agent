# APA-231 test evidence

Run date: 15 September 2026. Branch: `feature-apa-231-dealership-user-management`.

The integration tests provision First Motors and Second Motors with separate
administrators and staff. Each administrator sees only their own dealership's
users. Cross-dealership list, account creation, reset and deactivation attempts
return 403 and create persistent denied audit records. Duplicate email returns
409. A provisioned account must change its initial password before using the
dashboard. Reset refuses tokens issued before the reset and blocks application
access until the temporary password is changed. Deactivation refuses existing
tokens and new login while keeping the user row for historical attribution.
Staff management attempts return 403. Public `/auth/register` and `/auth/signup`
remain absent (404); unauthenticated account creation returns 401.

Commands and results:

```text
python -m pytest tests/test_dealership_user_management.py tests/test_platform_administration.py tests/test_migrations.py -q
28 passed, 2 dependency deprecation warnings in 30.43s

npm run build --prefix frontend
TypeScript typecheck and Vite production build passed.

DATABASE_URL=postgresql+psycopg://example:example@localhost/example python -m alembic heads
f8d91a6b20e4 (head)
```

For the story's demonstration, run with two actual dealership accounts on a
migrated PostgreSQL database, record the user-list and denied-action results,
and attach that evidence to Jira. The reviewed merge to `main` is also pending.
