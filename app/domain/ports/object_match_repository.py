from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.domain.matching import MatchLevel
from app.domain.object_matches import MatchPage, MatchProposal, MatchStatus, ObjectMatch
from app.domain.object_reports import ObjectReport


@dataclass(frozen=True, slots=True)
class MatchCandidates:
    source: ObjectReport
    candidates: tuple[ObjectReport, ...]


class ObjectMatchRepository(Protocol):
    def generation(
        self,
        report_id: UUID,
        user_id: UUID,
    ) -> AbstractContextManager[MatchCandidates]:
        """Own one atomic generation transaction, including rollback on any error."""
        ...

    def synchronize(
        self,
        source: ObjectReport,
        proposals: tuple[MatchProposal, ...],
    ) -> tuple[ObjectMatch, ...]:
        """Upsert/prune pending pairs only, inside generation()."""
        ...

    def list_by_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        level: MatchLevel | None = None,
        status: MatchStatus | None = None,
    ) -> MatchPage: ...

    def get_by_id_and_user(
        self,
        match_id: UUID,
        user_id: UUID,
    ) -> ObjectMatch | None: ...
