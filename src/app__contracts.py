# Verbatim excerpt from app/contracts.py of AgentSuite.
# The claim and check contracts the extraction result is built from.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/contracts.py:145-167 ----
class CitationClaim(BaseModel):
    """One claim the review makes about one cited work.

    Tolerant about the key name for the claim itself. Measured against a
    hosted 70B, the same prompt produced `claim_text`, `claim`, `text` and
    `quote` on different calls — the content correct every time. Rejecting
    three of those four buys a repair call to rename a field.
    """

    claim_id: str
    cited_as: str = Field(description="The reference string as written.")
    claim_text: Evidence = Field(description="What the review says about the work.")
    claim_type: Literal["summary", "critique", "attribution", "numeric"] = "summary"

    @model_validator(mode="before")
    @classmethod
    def _accept_aliases(cls, value):
        if not isinstance(value, dict) or "claim_text" in value:
            return value
        for alias in ("claim", "text", "quote", "statement", "assertion"):
            if alias in value:
                return {**value, "claim_text": value[alias]}
        return value

# ---- app/contracts.py:183-191 ----
class ClaimCheck(BaseModel):
    claim_id: str
    verdict: Literal[
        "supported", "partially_supported", "unsupported", "cannot_verify"
    ] = "cannot_verify"
    basis: Literal["full_text", "abstract_only", "metadata_only", "none"] = "none"
    reasoning: str
    evidence_from_source: list[Evidence] = Field(default_factory=list)
    confidence: Confidence = "low"

