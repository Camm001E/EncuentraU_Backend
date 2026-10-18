from app.api.schemas.deliveries import (
    DeliveryNoteRequest,
    DisputeRequest,
    ReopenRequest,
)


def test_private_delivery_inputs_are_hidden_in_repr():
    private = "Información privada para la revisión"
    for request in (
        DisputeRequest(reason=private),
        DeliveryNoteRequest(admin_note=private),
        ReopenRequest(admin_note=private),
    ):
        assert private not in repr(request)
