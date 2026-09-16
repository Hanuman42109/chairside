"""Alternative integration point: Retell's built-in LLM + "custom functions".

If the Retell agent is configured with Retell's own LLM (rather than the
Custom LLM websocket in app/routes/llm_websocket.py), Retell calls this
webhook directly whenever the agent invokes one of the custom functions you
define in the Retell dashboard. Each call here is stateless from our side --
there's no LangGraph state machine involved, just a direct tool invocation.

Wire up whichever pattern (this, or the websocket) matches how the agent
ends up configured in the Retell dashboard; both are provided so that choice
doesn't have to be made before the backend exists.

TODO: confirm the exact request/response envelope against current Retell
custom-function docs -- the shape below (`{"name": ..., "args": {...}}` in,
`{"result": ...}` out) is the commonly documented pattern but hasn't been
checked against a live payload.
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.tools import calcom, faq_kb, hubspot, twilio_sms

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook/retell", tags=["retell-functions"])


async def _handle_check_availability(args: dict) -> dict:
    on_date = date.fromisoformat(args["date"])
    slots = await calcom.check_availability(on_date)
    return {"slots": [s.model_dump() for s in slots]}


async def _handle_book_appointment(args: dict) -> dict:
    result = await calcom.book_slot(
        slot_start=args["slot_start"],
        attendee_name=args["attendee_name"],
        attendee_email=args.get("attendee_email", ""),
        attendee_phone=args["attendee_phone"],
    )
    return result.model_dump()


async def _handle_create_crm_contact(args: dict) -> dict:
    result = await hubspot.upsert_contact(
        phone=args["phone"],
        first_name=args.get("first_name", ""),
        last_name=args.get("last_name", ""),
        appointment_type=args.get("appointment_type"),
        insurance_provider=args.get("insurance_provider"),
    )
    return result.model_dump()


async def _handle_send_confirmation_sms(args: dict) -> dict:
    result = await twilio_sms.send_sms(to=args["to"], body=args["body"])
    return result.model_dump()


async def _handle_query_faq(args: dict) -> dict:
    result = faq_kb.query_faq(args["question"])
    return result.model_dump() if result else {"answer": None}


_HANDLERS = {
    "check_availability": _handle_check_availability,
    "book_appointment": _handle_book_appointment,
    "create_crm_contact": _handle_create_crm_contact,
    "send_confirmation_sms": _handle_send_confirmation_sms,
    "query_faq": _handle_query_faq,
}


@router.post("/functions")
async def retell_custom_function(request: Request) -> dict:
    payload: dict[str, Any] = await request.json()
    name = payload.get("name")
    args = payload.get("args", {})

    handler = _HANDLERS.get(name)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unknown function: {name!r}")

    try:
        result = await handler(args)
    except Exception as exc:  # noqa: BLE001 -- surface any tool failure to Retell as an error result
        logger.exception("custom function %s failed", name)
        return {"result": None, "error": str(exc)}

    return {"result": result}
