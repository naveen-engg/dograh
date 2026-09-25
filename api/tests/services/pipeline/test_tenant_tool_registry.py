import pytest
from api.services.pipeline.needle_runner import NeedleSlot, NeedleToolDefinition
from api.services.pipeline.tenant_tool_registry import tenant_tool_registry


@pytest.fixture(autouse=True)
def clean_registry():
    tenant_tool_registry.clear_tenant_cache()
    yield
    tenant_tool_registry.clear_tenant_cache()


@pytest.mark.asyncio
async def test_tenant_tool_isolation():
    # Tenant 101 registers an order status tool
    order_tool_t1 = NeedleToolDefinition(
        name="lookup_order",
        description="Lookup status for an order",
        intent_patterns=[r"where is my order", r"track order\s*(?P<order_id>\w+)"],
        slots=[
            NeedleSlot(name="order_id", pattern=r"(?:order|#)\s*([A-Za-z0-9]+)"),
        ],
        response_template="Order {order_id} is out for delivery.",
    )
    tenant_tool_registry.register_tool(101, order_tool_t1)

    # Tenant 202 registers an appointment booking tool
    booking_tool_t2 = NeedleToolDefinition(
        name="book_appointment",
        description="Book medical appointment",
        intent_patterns=[r"book appointment", r"schedule visit for (?P<date>\w+)"],
        slots=[
            NeedleSlot(name="date", pattern=r"(tomorrow|monday|tuesday)"),
        ],
        response_template="Appointment confirmed for {date}.",
    )
    tenant_tool_registry.register_tool(202, booking_tool_t2)

    runner_t1 = tenant_tool_registry.get_runner(101)
    runner_t2 = tenant_tool_registry.get_runner(202)

    # Verify tool registries are completely isolated
    assert "lookup_order" in runner_t1._tools
    assert "lookup_order" not in runner_t2._tools

    assert "book_appointment" in runner_t2._tools
    assert "book_appointment" not in runner_t1._tools

    # Test execution isolation:
    # 1. Tenant 1 utterance matches Tenant 1 tool
    res_t1 = await runner_t1.execute_transcript("where is my order #XYZ99")
    assert res_t1.matched is True
    assert res_t1.tool_name == "lookup_order"
    assert "XYZ99" in res_t1.response_text

    # 2. Same utterance in Tenant 2 MUST NOT match and fallback to LLM
    res_t2 = await runner_t2.execute_transcript("where is my order #XYZ99")
    assert res_t2.matched is False
    assert res_t2.fallback_to_llm is True

    # 3. Tenant 2 appointment utterance matches Tenant 2 tool
    res_booking = await runner_t2.execute_transcript("schedule visit for tomorrow")
    assert res_booking.matched is True
    assert res_booking.tool_name == "book_appointment"
    assert "tomorrow" in res_booking.response_text
