class ProviderError(Exception):
    """Raised by any provider on a failed external call.

    Services catch this and translate it into a domain result carrying
    coverage/confidence (architecture.md §D) — providers themselves never
    decide what a failure means for the caller.
    """

    def __init__(self, provider: str, message: str, *, retryable: bool = False) -> None:
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")
