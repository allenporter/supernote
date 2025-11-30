"""Decorators for route handlers."""


def public_route(handler):
    """Decorator to mark a route handler as public (no authentication required)."""
    handler.is_public = True
    return handler
