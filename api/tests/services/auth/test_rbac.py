import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from api.db.models import UserModel
from api.enums import SupportAuditAction, UserRole
from api.services.auth.rbac import (
    enforce_support_read_only,
    require_roles,
    require_super_admin,
    require_support_or_admin,
    require_tenant_admin,
)


@pytest.fixture
def super_admin_user():
    user = MagicMock(spec=UserModel)
    user.id = 1
    user.email = "admin@platform.com"
    user.is_superuser = True
    user.role = "super_admin"
    user.effective_role = UserRole.SUPER_ADMIN
    user.selected_organization_id = 10
    return user


@pytest.fixture
def support_engineer_user():
    user = MagicMock(spec=UserModel)
    user.id = 2
    user.email = "support@platform.com"
    user.is_superuser = False
    user.role = "support_engineer"
    user.effective_role = UserRole.SUPPORT_ENGINEER
    user.selected_organization_id = 20
    return user


@pytest.fixture
def tenant_admin_user():
    user = MagicMock(spec=UserModel)
    user.id = 3
    user.email = "tenant_admin@tenant.com"
    user.is_superuser = False
    user.role = "tenant_admin"
    user.effective_role = UserRole.TENANT_ADMIN
    user.selected_organization_id = 30
    return user


@pytest.fixture
def tenant_user():
    user = MagicMock(spec=UserModel)
    user.id = 4
    user.email = "member@tenant.com"
    user.is_superuser = False
    user.role = "tenant_user"
    user.effective_role = UserRole.TENANT_USER
    user.selected_organization_id = 30
    return user


@pytest.mark.asyncio
async def test_require_super_admin(super_admin_user, support_engineer_user, tenant_admin_user):
    checker = require_super_admin

    # Super admin passes
    result = await checker(super_admin_user)
    assert result == super_admin_user

    # Support engineer blocked
    with pytest.raises(HTTPException) as exc_info:
        await checker(support_engineer_user)
    assert exc_info.value.status_code == 403

    # Tenant admin blocked
    with pytest.raises(HTTPException) as exc_info:
        await checker(tenant_admin_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_support_or_admin(super_admin_user, support_engineer_user, tenant_user):
    checker = require_support_or_admin

    # Both super_admin and support_engineer pass
    assert await checker(super_admin_user) == super_admin_user
    assert await checker(support_engineer_user) == support_engineer_user

    # Tenant user blocked
    with pytest.raises(HTTPException) as exc_info:
        await checker(tenant_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_tenant_admin(super_admin_user, tenant_admin_user, tenant_user):
    checker = require_tenant_admin

    # Super admin and tenant admin pass
    assert await checker(super_admin_user) == super_admin_user
    assert await checker(tenant_admin_user) == tenant_admin_user

    # Standard tenant user blocked
    with pytest.raises(HTTPException) as exc_info:
        await checker(tenant_user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_support_read_only_allowed_get(support_engineer_user):
    request = MagicMock()
    request.method = "GET"
    request.client.host = "192.168.1.100"
    request.headers.get.return_value = "Mozilla/5.0"
    request.url.path = "/api/v1/workflow/42"

    with patch("api.services.auth.rbac.db_client.create_support_audit_log", new_callable=AsyncMock) as mock_audit:
        result = await enforce_support_read_only(request, support_engineer_user)
        assert result == support_engineer_user
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == SupportAuditAction.READ_RESOURCE.value
        assert call_kwargs["actor_user_id"] == 2
        assert call_kwargs["method"] == "GET"


@pytest.mark.asyncio
async def test_support_read_only_blocked_mutation(support_engineer_user):
    request = MagicMock()
    request.method = "DELETE"
    request.client.host = "192.168.1.100"
    request.headers.get.return_value = "Mozilla/5.0"
    request.url.path = "/api/v1/workflow/42"
    request.query_params = {}

    with patch("api.services.auth.rbac.db_client.create_support_audit_log", new_callable=AsyncMock) as mock_audit:
        with pytest.raises(HTTPException) as exc_info:
            await enforce_support_read_only(request, support_engineer_user)

        assert exc_info.value.status_code == 403
        assert "Support Engineers have read-only access" in exc_info.value.detail
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == SupportAuditAction.BLOCKED_WRITE_ATTEMPT.value
        assert call_kwargs["method"] == "DELETE"
