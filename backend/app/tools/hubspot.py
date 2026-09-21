"""HubSpot integration: create/update a contact after a call.

Docs: https://developers.hubspot.com/docs/api/crm/contacts
Uses a private-app access token (free tier supports this). We search by
phone number first so repeat callers update one contact instead of creating
duplicates.

Note: HubSpot's contact search index has a few seconds of propagation lag
after a create -- two upserts for the same new phone number in quick
succession (e.g. an automated test) can both miss the search and create two
contacts. Real calls are naturally spaced out in time, so this shouldn't
matter in practice, but it's not a bug in `_find_contact_by_phone` if you see
it happen back-to-back.
"""

import httpx

from app.config import get_settings
from app.tools import mock_data
from app.tools.schemas import ContactResult


class HubSpotError(RuntimeError):
    """Raised when HubSpot returns a non-2xx response or unexpected payload."""


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.hubspot_access_token}",
        "Content-Type": "application/json",
    }


async def _find_contact_by_phone(client: httpx.AsyncClient, phone: str) -> str | None:
    response = await client.post(
        "/crm/v3/objects/contacts/search",
        headers=_headers(),
        json={
            "filterGroups": [
                {"filters": [{"propertyName": "phone", "operator": "EQ", "value": phone}]}
            ],
            "limit": 1,
        },
    )
    if response.status_code != 200:
        raise HubSpotError(f"contact search failed: {response.status_code} {response.text}")

    results = response.json().get("results", [])
    return results[0]["id"] if results else None


async def upsert_contact(
    phone: str,
    first_name: str,
    last_name: str = "",
    email: str | None = None,
    appointment_type: str | None = None,
    insurance_provider: str | None = None,
    notes: str | None = None,
) -> ContactResult:
    """Create a HubSpot contact, or update it if one with this phone exists.

    Args:
        phone: caller's phone number in E.164 format, used as the dedupe key.
        appointment_type / insurance_provider / notes: stored as custom
            properties -- these must exist on the HubSpot contact object
            (Settings -> Properties) before going live; see README.

    Returns:
        ContactResult with the HubSpot contact id and whether it was newly created.
    """
    settings = get_settings()
    if settings.tools_mock_mode:
        return mock_data.fake_contact()

    properties = {
        "phone": phone,
        "firstname": first_name,
        "lastname": last_name,
    }
    if email:
        properties["email"] = email
    if appointment_type:
        properties["chairside_appointment_type"] = appointment_type
    if insurance_provider:
        properties["chairside_insurance_provider"] = insurance_provider
    if notes:
        properties["chairside_last_call_notes"] = notes

    async with httpx.AsyncClient(base_url=settings.hubspot_api_base_url, timeout=10.0) as client:
        existing_id = await _find_contact_by_phone(client, phone)

        if existing_id:
            response = await client.patch(
                f"/crm/v3/objects/contacts/{existing_id}",
                headers=_headers(),
                json={"properties": properties},
            )
            if response.status_code != 200:
                raise HubSpotError(f"contact update failed: {response.status_code} {response.text}")
            return ContactResult(contact_id=existing_id, created=False)

        response = await client.post(
            "/crm/v3/objects/contacts",
            headers=_headers(),
            json={"properties": properties},
        )
        if response.status_code not in (200, 201):
            raise HubSpotError(f"contact create failed: {response.status_code} {response.text}")
        contact_id = response.json()["id"]
        return ContactResult(contact_id=contact_id, created=True)
