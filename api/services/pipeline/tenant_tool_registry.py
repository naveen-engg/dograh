"""Multi-Tenant Tool Registry for Needle Engine.

Provides tenant-isolated NeedleRunner instances with deterministic tools
scoped to specific organization IDs.
"""

from __future__ import annotations

from typing import Dict, Optional, Union
from loguru import logger

from api.db import db_client
from api.enums import ToolStatus
from api.services.pipeline.needle_runner import (
    NeedleRunner,
    NeedleSlot,
    NeedleToolDefinition,
)


class TenantToolRegistry:
    """Singleton managing tenant-isolated Needle runners and tool configurations."""

    _instances: Dict[str, NeedleRunner] = {}

    @classmethod
    def get_runner(cls, tenant_id: Optional[Union[str, int]] = None) -> NeedleRunner:
        """Get or initialize the tenant-specific NeedleRunner."""
        tid = str(tenant_id) if tenant_id is not None else "default"
        if tid not in cls._instances:
            logger.info(f"TenantToolRegistry: Initializing NeedleRunner for tenant '{tid}'")
            cls._instances[tid] = NeedleRunner(tenant_id=tid)
        return cls._instances[tid]

    @classmethod
    def register_tool(
        cls,
        tenant_id: Union[str, int],
        tool_def: NeedleToolDefinition,
    ) -> None:
        """Register a deterministic tool explicitly for a tenant."""
        runner = cls.get_runner(tenant_id)
        runner.register_tool(tool_def)
        logger.debug(
            f"TenantToolRegistry: Registered '{tool_def.name}' for tenant '{tenant_id}'"
        )

    @classmethod
    async def sync_tenant_tools(cls, tenant_id: int) -> int:
        """Sync active deterministic tools from the database for this organization."""
        runner = cls.get_runner(tenant_id)
        synced_count = 0

        try:
            tools = await db_client.get_tools_by_organization(
                organization_id=tenant_id,
                status=ToolStatus.ACTIVE,
            )

            for t in tools:
                config = t.configuration or {}
                intent_patterns = config.get("intent_patterns", [])

                # If the tool has deterministic intent patterns configured, register it in Needle
                if intent_patterns:
                    slots = [
                        NeedleSlot(
                            name=s["name"],
                            pattern=s["pattern"],
                            slot_type=s.get("type", "str"),
                            required=s.get("required", True),
                            default=s.get("default"),
                        )
                        for s in config.get("slots", [])
                        if "name" in s and "pattern" in s
                    ]

                    tool_def = NeedleToolDefinition(
                        name=t.name,
                        description=t.description or "",
                        intent_patterns=intent_patterns,
                        slots=slots,
                        response_template=config.get("response_template"),
                        confidence_threshold=float(config.get("confidence_threshold", 0.75)),
                    )
                    runner.register_tool(tool_def)
                    synced_count += 1

            logger.info(
                f"TenantToolRegistry: Synced {synced_count} deterministic tools for tenant {tenant_id}"
            )
        except Exception as e:
            logger.warning(
                f"TenantToolRegistry: Error syncing tools for tenant {tenant_id}: {e}"
            )

        return synced_count

    @classmethod
    def clear_tenant_cache(cls, tenant_id: Optional[Union[str, int]] = None) -> None:
        """Clear runners for one or all tenants."""
        if tenant_id is not None:
            cls._instances.pop(str(tenant_id), None)
        else:
            cls._instances.clear()


tenant_tool_registry = TenantToolRegistry
