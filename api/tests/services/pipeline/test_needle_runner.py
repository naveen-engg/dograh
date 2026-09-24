import pytest
import time
from api.services.pipeline.needle_runner import (
    NeedleRunner,
    NeedleSlot,
    NeedleToolDefinition,
)


@pytest.mark.asyncio
async def test_needle_tool_execution_fast_path():
    runner = NeedleRunner(tenant_id="tenant_alpha")

    # Define a deterministic transactional tool: Order Lookup
    async def get_order_status(order_id: str, context: dict = None):
        return {
            "status": "Shipped",
            "carrier": "FedEx",
            "delivery_date": "Tomorrow by 5 PM",
        }

    runner.register_tool(
        NeedleToolDefinition(
            name="order_status_lookup",
            description="Checks the delivery status of an order",
            intent_patterns=[
                r"where is my order",
                r"track (my )?order",
                r"status of order",
            ],
            slots=[
                NeedleSlot(
                    name="order_id",
                    pattern=r"(?:order\s*(?:#|number)?\s*)([A-Z0-9-]+)",
                    slot_type="str",
                    required=True,
                )
            ],
            handler=get_order_status,
            response_template="Your order {order_id} is {status} via {carrier} and scheduled for delivery {delivery_date}.",
        )
    )

    transcript = "Can you please track my order #ORD-99881?"
    start_time = time.perf_counter()
    res = await runner.execute_transcript(transcript)
    total_ms = (time.perf_counter() - start_time) * 1000.0

    assert res.matched is True
    assert res.tool_name == "order_status_lookup"
    assert res.extracted_slots["order_id"] == "ORD-99881"
    assert "Your order ORD-99881 is Shipped" in res.response_text
    assert res.fallback_to_llm is False
    assert res.execution_time_ms < 25.0
    assert total_ms < 25.0, f"Needle execution took {total_ms:.2f}ms, expected sub-25ms"


@pytest.mark.asyncio
async def test_needle_runner_unmatched_fallback_to_llm():
    runner = NeedleRunner(tenant_id="tenant_beta")

    # Register tool
    runner.register_tool(
        NeedleToolDefinition(
            name="check_balance",
            description="Account balance check",
            intent_patterns=[r"check my balance", r"what is my balance"],
            slots=[],
            handler=lambda: "Your balance is $450.00",
        )
    )

    # General conversational query that does not match any tool
    general_transcript = "What do you think is the best way to bake sourdough bread?"
    res = await runner.execute_transcript(general_transcript)

    assert res.matched is False
    assert res.fallback_to_llm is True
    assert res.response_text is None
