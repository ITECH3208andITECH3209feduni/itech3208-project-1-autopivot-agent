# Nothing that reaches the vision pipeline may be callable without signing in.
#
# The backend used to carry four routes left over from the single-page demo it
# grew out of — POST /remove-background, /process-vehicle, /detect-and-hide and
# /extract-images-from-url — none of them authenticated. Anyone who found the
# URL could spend the GPU, and the last one made the server fetch whatever page
# it was handed. No client called them: the listings flow, which checks who is
# asking and which dealership they belong to, is the only way in. They were
# removed rather than put behind a login, and these tests keep it that way.
#
# These import autopivot_backend, which loads torch and ultralytics at module
# level, so they need the ML environment (requirements-ml.txt). No model is
# loaded: a TestClient that is not entered as a context manager never runs the
# application's lifespan, which is where BiRefNet loads.
#
#     pytest tests/test_no_anonymous_processing.py -v

import fastapi.routing
import pytest
from fastapi.testclient import TestClient

import autopivot_backend as backend
from api.deps import get_current_user


# Everything that may be called without signing in, and why. Adding to this is a
# decision about who gets to use the server, so it should be made on purpose, in
# review, rather than happen as a side effect of registering a route.
PUBLIC_ROUTES = {
    # The built React client: its index page, and the fallback that serves it
    # for deep links and hands out its static files.
    ("GET", "/"),
    ("GET", "/{spa_path:path}"),
    # Monitoring. These report which models are loaded; they run none of them.
    ("GET", "/health"),
    ("GET", "/health/api"),
    ("GET", "/api/status"),
    # Signing in cannot require being signed in.
    ("POST", "/auth/login"),
    # FastAPI's own interactive documentation.
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}

# A mount serves a whole directory or sub-application, so each one is listed by
# path. This is the built client's scripts and stylesheets.
PUBLIC_MOUNTS = {"/assets"}

# The payloads are ones the old handlers turned away before reaching a model or
# the network. So wherever one of these routes still exists, the test fails at
# once on the status code instead of waiting on a model download first.
_NOT_AN_IMAGE = {"files": {"file": ("car.txt", b"not an image", "text/plain")}}

RETIRED_ROUTES = [
    ("/remove-background", _NOT_AN_IMAGE),
    ("/process-vehicle", _NOT_AN_IMAGE),
    ("/detect-and-hide", _NOT_AN_IMAGE),
    ("/extract-images-from-url", {"json": {"url": "ftp://example.invalid/listing"}}),
]


def registered_routes(app):
    """Every route the application answers, with included routers flattened.

    Newer FastAPI keeps each included router as a single node in app.routes and
    exposes the flattened view through fastapi.routing.iter_route_contexts.
    Older releases copied every route into app.routes, which was then already
    flat. Both are handled, so this check does not depend on the installed
    version.
    """
    flatten = getattr(fastapi.routing, "iter_route_contexts", None)
    return list(flatten(app.routes)) if flatten is not None else list(app.routes)


def requires_sign_in(route) -> bool:
    """Whether resolving this route's dependencies authenticates the caller.

    Every guard in api/deps.py — ReadyUser, CurrentUser and require_roles —
    bottoms out in get_current_user, so finding it anywhere in the tree is what
    it means for a route to be protected.
    """
    pending = [getattr(route, "dependant", None)]
    while pending:
        dependant = pending.pop()
        if dependant is None:
            continue
        if dependant.call is get_current_user:
            return True
        pending.extend(dependant.dependencies)
    return False


def anonymous_entry_points(app) -> list[str]:
    """Each route that answers without a signed-in user and is not on the list."""
    found = []
    for route in registered_routes(app):
        if requires_sign_in(route):
            continue
        if not route.methods:
            # A mount, or a websocket: no methods to match against.
            if route.path not in PUBLIC_MOUNTS:
                found.append(f"(mount) {route.path}")
            continue
        for method in sorted(route.methods):
            # HEAD is GET without the body; Starlette adds it to every GET route
            # it builds itself, which includes the documentation pages.
            listed_as = "GET" if method == "HEAD" else method
            if (listed_as, route.path) not in PUBLIC_ROUTES:
                found.append(f"{method} {route.path}")
    return found


def test_nothing_answers_an_anonymous_caller_except_what_is_listed_as_public():
    """
    The defect this exists to catch is a processing route that anyone can call.
    It does not care where one comes from — the old demo routes coming back, a
    debugging endpoint added for a demo and never taken out, or a guard dropped
    from an existing route while it was being edited. Any of those puts the GPU
    in the hands of whoever has the URL, and none of them fails anything else in
    the suite.
    """
    exposed = anonymous_entry_points(backend.app)

    assert not exposed, (
        "These answer without a signed-in user. Protect them with ReadyUser, "
        "or, if they genuinely must be public, add them to PUBLIC_ROUTES with "
        "the reason:\n  " + "\n  ".join(exposed)
    )


def test_the_listings_route_is_the_way_in_and_it_is_guarded():
    """
    The other half of the statement, and what keeps the check above honest: if
    the route table could not be read, or the guard could not be recognised,
    there would be nothing for it to object to and it would pass on an empty
    list. The one route that starts processing has to be found, and found
    protected.
    """
    processing_routes = [
        route
        for route in registered_routes(backend.app)
        if route.path == "/api/listings/{listing_id}/process"
        and "POST" in (route.methods or ())
    ]

    assert len(processing_routes) == 1
    assert requires_sign_in(processing_routes[0])


@pytest.mark.parametrize(
    "path, payload", RETIRED_ROUTES, ids=[path for path, _ in RETIRED_ROUTES]
)
def test_the_retired_demo_routes_no_longer_answer(path, payload):
    """
    The four routes the demo page used, asked directly. 405 when the built
    client is present — its GET-only fallback matches every path — and 404 when
    it is not; either way no handler ran. A 401 or 403 would mean the route was
    kept behind a login, which is not what was decided, and anything else means
    it is still open.
    """
    client = TestClient(backend.app, raise_server_exceptions=False)

    response = client.post(path, **payload)

    assert response.status_code in (404, 405), (
        f"POST {path} answered {response.status_code}: {response.text[:200]}"
    )
