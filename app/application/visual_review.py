from collections import OrderedDict
from threading import BoundedSemaphore, Lock
from time import monotonic

from fastapi import HTTPException

from app.domain.object_matches import MatchNotFoundError
from app.infrastructure.analysis_errors import ImageAnalysisProviderError


class VisualReviewCache:
    """Bounded, short-lived, process-local cache. Never contains image bytes."""

    def __init__(self, capacity=128, ttl=900):
        self.capacity, self.ttl = capacity, ttl
        self.entries = OrderedDict()
        self.lock = Lock()
        self.slots = BoundedSemaphore(2)
        self.inflight = set()

    def get(self, key):
        with self.lock:
            value = self.entries.get(key)
            if value is None:
                return None
            if value[0] <= monotonic():
                del self.entries[key]
                return None
            self.entries.move_to_end(key)
            return value[1]

    def put(self, key, value):
        with self.lock:
            self.entries[key] = (monotonic() + self.ttl, value)
            self.entries.move_to_end(key)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)


class ReviewMatchPhotos:
    def __init__(self, repository, images, analyzer, cache):
        self.repository, self.images = repository, images
        self.analyzer, self.cache = analyzer, cache

    def __call__(self, match_id, user):
        match = self.repository.get_by_id_and_user(match_id, user.id)
        if match is None:
            raise MatchNotFoundError
        # Each authorized read commits its short transaction before any API call.
        a = self.images.content(match.my_report.id, user)
        b = self.images.content(match.candidate_report.id, user)
        key = (
            str(user.id),
            str(match_id),
            a.reference.sha256,
            b.reference.sha256,
            self.analyzer.namespace,
        )
        cached = self.cache.get(key)
        response = cached
        if response is None:
            with self.cache.lock:
                if key in self.cache.inflight:
                    raise HTTPException(429, "Esta comparacion ya esta en curso.")
                if not self.cache.slots.acquire(blocking=False):
                    raise HTTPException(
                        429, "Hay comparaciones en curso. Intenta nuevamente."
                    )
                self.cache.inflight.add(key)
            try:
                cached = self.cache.get(key)
                if cached is not None:
                    response = cached
                else:
                    result, metadata = self.analyzer.compare(
                        [
                            (a.data, a.reference.content_type),
                            (b.data, b.reference.content_type),
                        ]
                    )
                    response = {
                        "comparison": result.conservative().model_dump(),
                        "provider": metadata["provider"],
                        "model": metadata["model"],
                        "prompt_version": metadata["prompt_version"],
                        "fallback_used": metadata["fallback_used"],
                        "verification": metadata.get("verification", "not_needed"),
                        "source_sha256": a.reference.sha256,
                        "candidate_sha256": b.reference.sha256,
                    }
                    self._validate_current(match_id, match, user, a, b)
                    self.cache.put(key, response)
            except ImageAnalysisProviderError:
                raise HTTPException(
                    502, "No se pudo comparar las fotos. Intenta nuevamente."
                ) from None
            finally:
                with self.cache.lock:
                    self.cache.inflight.discard(key)
                    self.cache.slots.release()
        self._validate_current(match_id, match, user, a, b)
        return {**response, "cached": cached is not None}

    def _validate_current(self, match_id, match, user, a, b):
        # Never display or cache a verdict for photos replaced during inference.
        current = self.repository.get_by_id_and_user(match_id, user.id)
        if current is None:
            raise MatchNotFoundError
        current_a = self.images.metadata(match.my_report.id, user)
        current_b = self.images.metadata(match.candidate_report.id, user)
        if (current_a.sha256, current_b.sha256) != (
            a.reference.sha256,
            b.reference.sha256,
        ):
            raise HTTPException(409, "Las fotos cambiaron. Actualiza la coincidencia.")
