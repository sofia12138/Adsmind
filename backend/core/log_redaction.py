"""Remove OAuth credentials from HTTP client and access log query strings."""
import logging
import re

_SENSITIVE_QUERY = re.compile(r'([?&](?:access_token|client_secret|secret|auth_code|code|fb_exchange_token|state)=)[^&\s"\']+', re.IGNORECASE)


class OAuthLogFilter(logging.Filter):
    def filter(self, record):
        def redact(value):
            return _SENSITIVE_QUERY.sub(r'\1[redacted]', value) if isinstance(value, str) else value
        # Uvicorn's access formatter needs the original five arguments.
        record.msg = redact(record.msg)
        if isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        return True


def install():
    for name in ('httpx', 'httpcore', 'uvicorn.access'):
        logger = logging.getLogger(name)
        if not any(isinstance(f, OAuthLogFilter) for f in logger.filters):
            logger.addFilter(OAuthLogFilter())
