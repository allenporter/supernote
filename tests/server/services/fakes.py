from supernote.server.services.coordination import LocalCoordinationService


class FakeCoordinationService(LocalCoordinationService):
    """
    Fake implementation of CoordinationService for testing.
    Currently identical to LocalCoordinationService since Local is already in-memory.
    """

    def __init__(self) -> None:
        """Create a fake coordination service."""
        super().__init__()
        # Ensure we have our own store/lock if we aren't careful,
        # but supers init does that.
        pass
