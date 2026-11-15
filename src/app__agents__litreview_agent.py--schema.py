# Verbatim excerpt from app/agents/litreview_agent.py of AgentSuite.
# The extraction output contract. This is the schema the safety-specialised endpoint returned valid JSON against the WRONG shape of -- it answered its own content-classification schema instead.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/agents/litreview_agent.py:132-154 ----
class ExtractedClaims(BaseModel):
    """Accepts the wrapper, a differently-named wrapper, or no wrapper.

    A model asked for `{"claims": [...]}` returns a bare array often enough
    that refusing it means paying for a second call to add two characters.
    """

    claims: list[CitationClaim]

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, value):
        if isinstance(value, list):
            return {"claims": value}
        if isinstance(value, dict) and "claims" not in value:
            for alias in ("items", "citations", "extracted_claims", "results"):
                if alias in value and isinstance(value[alias], list):
                    return {"claims": value[alias]}
            # A single claim returned unwrapped. Seen when a window contains
            # exactly one citation, which is common at a section boundary.
            if "claim_id" in value or "cited_as" in value:
                return {"claims": [value]}
        return value

