from pathlib import Path


FRONTEND_APP = Path(__file__).resolve().parents[1] / "frontend" / "static" / "app.js"


def test_dashboard_uses_current_browser_close_endpoint():
    source = FRONTEND_APP.read_text(encoding="utf-8")
    assert "`/api/browser/close/${projectId}`" in source
    assert 'api("/api/browser/close",' not in source


def test_dashboard_uses_current_secret_unlock_endpoint():
    source = FRONTEND_APP.read_text(encoding="utf-8")
    assert '"/api/secrets/unlock"' in source
    assert '"/api/secrets/panel/verify"' not in source
