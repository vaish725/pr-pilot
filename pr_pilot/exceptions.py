class LLMUnavailableError(Exception):
    """Raised when the configured LLM provider fails on all attempted calls."""
