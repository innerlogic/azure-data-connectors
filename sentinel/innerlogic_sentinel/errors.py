class ConnectorError(Exception):
    """Base class for connector failures."""


class ConfigError(ConnectorError):
    """Missing or invalid configuration."""


class NonRetryableError(ConnectorError):
    """The Innerlogic API rejected the request (400/401/403/other 4xx).

    The checkpoint is left unchanged; an operator must fix the cause
    (token, access status, saved cursor) rather than the connector retrying.
    """


class RetryableError(ConnectorError):
    """Transient failure (429/5xx/timeout) that outlived the retry budget."""


class ValidationError(ConnectorError):
    """The API response did not have the documented shape."""


class IngestionError(ConnectorError):
    """Azure rejected one or more records; the checkpoint must not advance."""
