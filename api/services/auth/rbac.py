from typing import Annotated, Callable
from fastapi import Depends, Header, HTTPException, Request, status
from loguru import logger

from api.db import db_client
from api.db.models import UserModel
from api.enums import SupportAuditAction, UserRole
from api.services.auth.depends import get_user


def require_roles(*allowed_roles: UserRole) -> Callable:
    """Dependency factory that enforces one of the allowed UserRoles."""

    async def _role_checker(
        user: Annotated[UserModel, Depends(get_user)],
    ) -> UserModel:
        role = user.effective_role
        if role not in allowed_roles:
            role_names = [r.value for r in allowed_roles]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of roles: {', '.join(role_names)}. Current role: {role.value}",
            )
        return user

    return _role_checker


# Commonly used RBAC dependencies
require_super_admin = require_roles(UserRole.SUPER_ADMIN)
require_support_or_admin = require_roles(UserRole.SUPER_ADMIN, UserRole.SUPPORT_ENGINEER)
require_tenant_admin = require_roles(UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN)


async def enforce_support_read_only(
    request: Request,
    user: Annotated[UserModel, Depends(get_user)],
) -> UserModel:
    """Enforce that SUPPORT_ENGINEER users can only perform read-only actions (GET, HEAD, OPTIONS).

    Any mutation (POST, PUT, PATCH, DELETE) attempted by a Support Engineer is blocked and logged.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if user.effective_role == UserRole.SUPPORT_ENGINEER:
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            # Block and record security audit log
            await db_client.create_support_audit_log(
                actor_user_id=user.id,
                actor_email=user.email,
                target_organization_id=user.selected_organization_id,
                action=SupportAuditAction.BLOCKED_WRITE_ATTEMPT.value,
                method=request.method,
                path=str(request.url.path),
                ip_address=client_ip,
                user_agent=user_agent,
                extra_metadata={"query_params": dict(request.query_params)},
            )
            logger.warning(
                f"Blocked write attempt {request.method} {request.url.path} "
                f"by support engineer {user.email} (id={user.id})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Support Engineers have read-only access while inspecting tenant resources.",
            )

        # Log read access for full compliance audit trail
        await db_client.create_support_audit_log(
            actor_user_id=user.id,
            actor_email=user.email,
            target_organization_id=user.selected_organization_id,
            action=SupportAuditAction.READ_RESOURCE.value,
            method=request.method,
            path=str(request.url.path),
            ip_address=client_ip,
            user_agent=user_agent,
        )

    return user
