"""Widget delivery: public config with cache headers, versioned immutable bundle."""

from app.version import WIDGET_SCRIPT_VERSION


def test_config_is_public_and_small(client, auth, make_widget):
    widget = make_widget()
    res = client.get(f"/widgets/{widget['id']}/config")  # NO auth — public by design
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == widget["id"]
    assert body["title"] == widget["title"]
    assert body["honeypot_field"] == "hp_" + widget["id"][:8]
    assert len(res.content) < 1500  # small payload


def test_config_cache_headers_and_conditional_304(client, auth, make_widget):
    widget = make_widget()
    res = client.get(f"/widgets/{widget['id']}/config")
    assert res.status_code == 200
    assert "public" in res.headers["cache-control"]
    assert "max-age=300" in res.headers["cache-control"]
    etag = res.headers["etag"]
    assert etag

    res2 = client.get(f"/widgets/{widget['id']}/config", headers={"If-None-Match": etag})
    assert res2.status_code == 304
    assert res2.content == b""


def test_config_404_for_unknown_widget(client):
    assert client.get("/widgets/does-not-exist/config").status_code == 404


def test_versioned_bundle_immutable(client):
    res = client.get(f"/embed/{WIDGET_SCRIPT_VERSION}/widget.js")
    assert res.status_code == 200
    assert "application/javascript" in res.headers["content-type"]
    assert "immutable" in res.headers["cache-control"]
    assert "max-age=31536000" in res.headers["cache-control"]
    assert b"FlyRank capstone" in res.content
    assert b"/widgets/" in res.content  # renderer knows how to fetch config


def test_unknown_version_returns_404(client):
    """The immutable URL is only valid for the exact released version."""
    res = client.get("/embed/wbad0000000/widget.js")
    assert res.status_code == 404


def test_alias_bundle_short_cache(client):
    res = client.get("/widget.js")
    assert res.status_code == 200
    assert "max-age=60" in res.headers["cache-control"]


def test_cors_preflight_on_submissions(client):
    res = client.request(
        "OPTIONS",
        "/submissions",
        headers={
            "Origin": "http://customer.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "*"
    assert "POST" in res.headers.get("access-control-allow-methods", "")
    assert "content-type" in res.headers.get("access-control-allow-headers", "").lower()


def test_config_is_cors_allowed(client, auth, make_widget):
    widget = make_widget()
    res = client.get(f"/widgets/{widget['id']}/config", headers={"Origin": "http://customer.example"})
    assert res.headers.get("access-control-allow-origin") == "*"


def test_config_map_exposes_mode_locale_theme(client, auth, make_widget):
    """The public config is the renderer's map: mode, locale and theme defaults
    are served with every widget so the script never needs hard-coded values."""
    widget = make_widget(styles={})  # type defaults to "signup" in the fixture
    body = client.get(f"/widgets/{widget['id']}/config").json()
    assert body["mode"] == "inline"          # signup/contact render inline forms
    assert body["locale"] == "en"            # default locale when styles are empty
    assert body["styles"] == {}              # theme defaults fall back client-side

    cta = make_widget(type="cta", styles={"accent_color": "#9333ea"})
    body2 = client.get(f"/widgets/{cta['id']}/config").json()
    assert body2["mode"] == "popover"        # cta widgets render a popover/launcher
    assert body2["styles"]["accent_color"] == "#9333ea"
    assert body2["locale"] == "en"

    popover = make_widget(type="popover")
    body3 = client.get(f"/widgets/{popover['id']}/config").json()
    assert body3["mode"] == "popover"        # explicit popover type is not reported as inline