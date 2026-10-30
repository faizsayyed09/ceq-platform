class CeqError(Exception):
    """Base application error safe for structured API responses."""


class ValidationError(CeqError):
    pass


class ExternalServiceError(CeqError):
    pass


class ResourceNotFoundError(CeqError):
    pass


class SecurityError(CeqError):
    pass
