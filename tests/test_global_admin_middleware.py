import pytest

from app.ownership import OwnershipStore
from app.project_access import ProjectAccessMiddleware


@pytest.mark.parametrize(
    "path",
    [
        "/api/network/profiles",
        "/api/network/test",
        "/api/secrets/unlock",
        "/api/system/status",
    ],
)
def test_global_admin_paths_are_explicit(path):
    assert path in ProjectAccessMiddleware.GLOBAL_ADMIN_PATHS


def test_global_admin_identity_is_bootstrap_admin():
    assert OwnershipStore.BOOTSTRAP_USER_ID == 1
