class ImageAnalysisProviderError(RuntimeError):
    """Only safe, fixed reason codes may cross the provider boundary."""

    def __init__(self, reason: str = "provider_error", *, fallback_allowed=False):
        super().__init__(reason)
        self.reason = reason
        self.fallback_allowed = fallback_allowed
