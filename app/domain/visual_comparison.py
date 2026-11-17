from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PAIR_PROMPT_VERSION = "visual-pair-v5"


class VisualComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["consistent", "different", "uncertain"]
    identity_evidence: Literal["distinctive", "generic", "insufficient"]
    quality_sufficient: bool
    same_parts_visible: bool = Field(
        description="The same physical regions must be visible in both photos."
    )
    agreements: list[str] = Field(max_length=6)
    structural_agreements: list[str] = Field(default_factory=list, max_length=6)
    contradictions: list[str] = Field(max_length=6)
    explanation: str = Field(min_length=1, max_length=1000)
    suggested_photo: str | None = Field(max_length=500)

    def conservative(self) -> "VisualComparison":
        verdict = self.verdict
        if not self.quality_sufficient or not self.same_parts_visible:
            verdict = "uncertain"
        elif verdict == "consistent" and (
            self.identity_evidence == "insufficient"
            or (
                self.identity_evidence != "distinctive"
                and len(
                    {
                        x.strip().casefold()
                        for x in self.structural_agreements
                        if x.strip()
                    }
                )
                < 2
            )
            or len(
                {item.strip().casefold() for item in self.agreements if item.strip()}
            )
            < 2
            or self.contradictions
        ):
            verdict = "uncertain"
        elif verdict == "different" and not any(s.strip() for s in self.contradictions):
            verdict = "uncertain"
        return self.model_copy(update={"verdict": verdict})


class DifferenceAudit(VisualComparison):
    difference_basis: Literal[
        "construction", "condition", "appearance_or_viewpoint", "insufficient"
    ] = Field(
        description=(
            "Classify the strongest proposed difference. Damage, wear or missing "
            "removable parts are condition, even if permanent. Construction means "
            "incompatible manufactured structure visible in both photos."
        )
    )
