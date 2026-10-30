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


class ArtifactValidationError(CeqError):
    """Artifact metadata or identifiers were invalid."""


class ArtifactNotFoundError(CeqError):
    """The requested artifact does not exist."""


class ArtifactAuthorizationError(CeqError):
    """Artifact storage rejected the operation."""


class ArtifactStorageError(CeqError):
    """Artifact storage could not complete the operation."""


class ArtifactDownloadLinkError(CeqError):
    """An artifact download link could not be created."""
