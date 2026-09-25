import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from api.constants import AUTH_PROVIDER
from api.db import db_client
from api.db.models import UserModel
from api.enums import SupportAuditAction, UserRole
from api.services.auth.depends import get_superuser
from api.services.auth.rbac import require_roles, require_super_admin, require_support_or_admin
from api.services.auth.stack_auth import (
    StackAuthSessionError,
    StackAuthUserSearchError,
    stackauth,
)
from api.utils.auth import create_jwt_token

router = APIRouter(prefix="/superuser", tags=["superuser"])


class ImpersonateRequest(BaseModel):
    """Request payload for superadmin impersonation."""

    provider_user_id: str | None = None
    user_id: int | None = None
    email: str | None = None


class ImpersonateResponse(BaseModel):
    refresh_token: str
    access_token: str


class SuperuserWorkflowRunResponse(BaseModel):
    id: int
    name: str
    workflow_id: int
    workflow_name: Optional[str]
    user_id: Optional[int]
    organization_id: Optional[int]
    organization_name: Optional[str]
    mode: str
    is_completed: bool
    recording_url: Optional[str]
    transcript_url: Optional[str]
    usage_info: Optional[dict]
    cost_info: Optional[dict]
    initial_context: Optional[dict]
    gathered_context: Optional[dict]
    created_at: datetime


class SuperuserWorkflowRunsListResponse(BaseModel):
    workflow_runs: List[SuperuserWorkflowRunResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int


class SupportAuditLogResponse(BaseModel):
    id: int
    actor_user_id: int
    actor_email: Optional[str]
    target_organization_id: Optional[int]
    target_user_id: Optional[int]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[str]
    method: Optional[str]
    path: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    extra_metadata: dict
    created_at: datetime


class SupportAuditLogsListResponse(BaseModel):
    audit_logs: List[SupportAuditLogResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int


class UserSummaryResponse(BaseModel):
    id: int
    email: Optional[str]
    provider_id: str
    role: str
    is_superuser: bool
    selected_organization_id: Optional[int]
    created_at: datetime


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


@router.post("/impersonate")
async def impersonate(
    request_data: ImpersonateRequest,
    req: Request,
    user: UserModel = Depends(require_super_admin),
) -> ImpersonateResponse:
    """Impersonate a user as a super-admin or authorized support engineer with audit logging."""

    provider_user_id = (
        request_data.provider_user_id.strip() if request_data.provider_user_id else None
    ) or None
    email = request_data.email.strip().lower() if request_data.email else None
    target_user: UserModel | None = None

    # Resolve target user
    if request_data.user_id is not None:
        target_user = await db_client.get_user_by_id(request_data.user_id)
        if target_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {request_data.user_id} not found.",
            )
        provider_user_id = target_user.provider_id
    elif email:
        target_user = await db_client.get_user_by_email(email)
        if target_user is not None:
            provider_user_id = target_user.provider_id
        else:
            try:
                stack_users = await stackauth.find_users_by_email(email)
            except StackAuthUserSearchError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to search Stack Auth users.",
                ) from exc

            if len(stack_users) == 1 and isinstance(stack_users[0].get("id"), str):
                provider_user_id = stack_users[0]["id"]
            elif len(stack_users) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Multiple Stack Auth users matched that email.",
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with email {email} not found.",
                )
    elif provider_user_id:
        target_user, _ = await db_client.get_or_create_user_by_provider_id(provider_user_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One of 'provider_user_id', 'user_id', or 'email' must be provided.",
        )

    # Record Audit Log for Impersonation Start
    client_ip = req.client.host if req.client else None
    user_agent = req.headers.get("user-agent")
    await db_client.create_support_audit_log(
        actor_user_id=user.id,
        actor_email=user.email,
        target_organization_id=target_user.selected_organization_id if target_user else None,
        target_user_id=target_user.id if target_user else None,
        action=SupportAuditAction.IMPERSONATE_START.value,
        resource_type="user",
        resource_id=str(target_user.id) if target_user else provider_user_id,
        ip_address=client_ip,
        user_agent=user_agent,
        extra_metadata={"impersonated_email": target_user.email if target_user else email},
    )

    # Handle local OSS auth impersonation
    if AUTH_PROVIDER == "local":
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found in local database")
        token = create_jwt_token(target_user.id, target_user.email or "")
        return ImpersonateResponse(
            refresh_token=token,
            access_token=token,
        )

    # Stack Auth impersonation session
    try:
        session = await stackauth.impersonate(provider_user_id)
    except StackAuthSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create Stack Auth impersonation session.",
        ) from exc

    if (
        not isinstance(session, dict)
        or "refresh_token" not in session
        or "access_token" not in session
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create Stack Auth impersonation session.",
        )

    return ImpersonateResponse(
        refresh_token=session["refresh_token"],
        access_token=session["access_token"],
    )


@router.get("/audit-logs")
async def get_audit_logs(
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    actor_user_id: Optional[int] = Query(None, description="Filter by actor user ID"),
    target_organization_id: Optional[int] = Query(None, description="Filter by target org ID"),
    action: Optional[str] = Query(None, description="Filter by audit action"),
    user: UserModel = Depends(require_support_or_admin),
) -> SupportAuditLogsListResponse:
    """Retrieve paginated support and security audit logs."""
    offset = (page - 1) * limit
    logs, total_count = await db_client.get_support_audit_logs(
        limit=limit,
        offset=offset,
        actor_user_id=actor_user_id,
        target_organization_id=target_organization_id,
        action=action,
    )
    total_pages = (total_count + limit - 1) // limit

    return SupportAuditLogsListResponse(
        audit_logs=[
            SupportAuditLogResponse(
                id=log.id,
                actor_user_id=log.actor_user_id,
                actor_email=log.actor_email,
                target_organization_id=log.target_organization_id,
                target_user_id=log.target_user_id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                method=log.method,
                path=log.path,
                ip_address=log.ip_address,
                user_agent=log.user_agent,
                extra_metadata=log.extra_metadata or {},
                created_at=log.created_at,
            )
            for log in logs
        ],
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: UserModel = Depends(require_super_admin),
) -> List[UserSummaryResponse]:
    """List platform users and their assigned hierarchical roles."""
    offset = (page - 1) * limit
    async with db_client.async_session() as session:
        result = await session.execute(
            select(UserModel).order_by(UserModel.id.desc()).offset(offset).limit(limit)
        )
        users = result.scalars().all()
        return [
            UserSummaryResponse(
                id=u.id,
                email=u.email,
                provider_id=u.provider_id,
                role=u.effective_role.value,
                is_superuser=u.is_superuser,
                selected_organization_id=u.selected_organization_id,
                created_at=u.created_at,
            )
            for u in users
        ]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    request: UpdateUserRoleRequest,
    req: Request,
    admin_user: UserModel = Depends(require_super_admin),
) -> dict:
    """Update a user's role (super_admin, support_engineer, tenant_admin, tenant_user)."""
    target = await db_client.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = target.effective_role.value
    await db_client.update_user_role(user_id, request.role.value)

    # Log role modification in audit trail
    client_ip = req.client.host if req.client else None
    await db_client.create_support_audit_log(
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        target_organization_id=target.selected_organization_id,
        target_user_id=target.id,
        action=SupportAuditAction.CONFIG_OVERRIDE.value,
        resource_type="user_role",
        resource_id=str(user_id),
        method="PATCH",
        path=str(req.url.path),
        ip_address=client_ip,
        extra_metadata={"old_role": old_role, "new_role": request.role.value},
    )

    return {
        "status": "success",
        "user_id": user_id,
        "old_role": old_role,
        "new_role": request.role.value,
    }


@router.get("/workflow-runs")
async def get_workflow_runs(
    page: int = Query(1, ge=1, description="Page number (starts from 1)"),
    limit: int = Query(50, ge=1, le=100, description="Number of items per page"),
    filters: Optional[str] = Query(None, description="JSON-encoded filter criteria"),
    sort_by: Optional[str] = Query(
        None, description="Field to sort by (e.g., 'duration', 'created_at')"
    ),
    sort_order: Optional[str] = Query(
        "desc", description="Sort order ('asc' or 'desc')"
    ),
    user: UserModel = Depends(require_support_or_admin),
) -> SuperuserWorkflowRunsListResponse:
    """
    Get paginated list of all workflow runs with organization information.
    Requires super_admin or support_engineer role.
    """
    offset = (page - 1) * limit

    filter_criteria = None
    if filters:
        try:
            filter_criteria = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid filter format")

    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    workflow_runs, total_count = await db_client.get_workflow_runs_for_superadmin(
        limit=limit,
        offset=offset,
        filters=filter_criteria,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    total_pages = (total_count + limit - 1) // limit

    return SuperuserWorkflowRunsListResponse(
        workflow_runs=[SuperuserWorkflowRunResponse(**run) for run in workflow_runs],
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )
