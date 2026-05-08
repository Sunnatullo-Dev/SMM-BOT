class ProviderError(Exception):
    """Base class for provider-specific errors."""


class ProviderAuthError(ProviderError):
    """Raised when provider authentication fails."""


class ProviderResponseError(ProviderError):
    """Raised when provider returns an unexpected response."""


class ProviderTimeoutError(ProviderError):
    """Raised when provider request times out."""


class ProviderUnavailableError(ProviderError):
    """Raised when the provider service is unavailable."""
