from app.tools.twilio_sms import build_booking_confirmation_text


def test_build_booking_confirmation_text_includes_key_details():
    text = build_booking_confirmation_text(
        patient_first_name="Jane",
        appointment_start_local="2:00 PM on Sept 22",
        office_name="Chairside Dental",
    )
    assert "Jane" in text
    assert "2:00 PM on Sept 22" in text
    assert "Chairside Dental" in text
