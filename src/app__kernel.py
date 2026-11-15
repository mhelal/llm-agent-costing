# Verbatim excerpt from app/kernel.py of AgentSuite.
# Mechanical verbatim verification (a substring check, not a model judgement) and the structured-output path.
#
# This is a READING COPY, not a runnable module. Line numbers refer to
# the original file so each excerpt can be checked against the source.

# ---- app/kernel.py:560-572 ----
def verify_quotes(quotes: list[str], source: str) -> list[str]:
    """Return the quotes that do NOT appear in the source.

    Whitespace- and quote-mark-normalised, because extraction from PDF mangles
    both. Anything still missing is a fabrication and must fail the run — a
    fabricated quotation in a marking context is not a nuisance bug.

    Provider-independent by construction, which is exactly the point: this
    check is worth more than any model-based verification precisely because it
    does not depend on which model produced the text.
    """
    hay = _normalise(source)
    return [q for q in quotes if q.strip() and _normalise(q) not in hay]

# ---- app/kernel.py:384-471 ----
def structured(model_cls, *, model: str = MID, system: str | list,
               messages: list, max_tokens: int = 4000,
               budget: Optional[Budget] = None,
               temperature: Optional[float] = None,
               provider_key: Optional[str] = None,
               repair_attempts: int = 1,
               thinking_budget: Optional[int] = None):
    """Schema-constrained call returning a validated object.

    Where the backend supports constrained decoding this is one call and the
    shape is guaranteed. Where it does not — most open-weight models on NIM
    and Ollama — the provider layer has already appended the schema to the
    system prompt and stripped any code fence, and what remains is the part
    no prompt can guarantee: the reply might still not validate.

    So there is a bounded repair loop. The failing output and the validation
    error go back with an instruction to fix it. One attempt catches the
    common cases (a missing field, a number sent as a string); needing more
    than two is a sign the model cannot do the task, and the right response is
    to choose a different model rather than to keep asking.
    """
    schema = _forbid_additional_properties(model_cls.model_json_schema())
    caps = capabilities_for(provider_key or active_provider_key())
    attempt_messages = list(messages)
    last_error = ""

    for attempt in range(repair_attempts + 1):
        # Forwarded on every attempt, including repairs — the same
        # treatment budget/temperature/provider_key already get. A repair
        # attempt is fixing shape, not reasoning quality, but changing
        # whether thinking is on between attempt 0 and attempt 1 would be
        # an unannounced behavioural difference with no clear justification
        # either way, so it stays uniform.
        response = call(model=model, system=system, messages=attempt_messages,
                        max_tokens=max_tokens, output_schema=schema,
                        budget=budget, temperature=temperature,
                        provider_key=provider_key,
                        thinking_budget=thinking_budget)
        text = response.text()
        # Logged unconditionally, success or failure. Previously only a
        # validation FAILURE captured the raw text (for the repair loop) —
        # a call that parses cleanly but comes back semantically empty
        # (e.g. {"claims": []} from a document that plainly has claims)
        # left no trace of what was actually generated. This is what
        # makes that visible after the fact instead of requiring a
        # standalone reproduction to see it.
        runlog.info(f"{model_cls.__name__} attempt {attempt}: "
                    f"{len(text)} char(s) — {text[:400]!r}",
                    kind="structured_output", schema=model_cls.__name__,
                    attempt=attempt, chars=len(text))
        try:
            return model_cls.model_validate_json(text)
        except Exception as exc:                            # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            try:                       # a second chance at loosely wrapped JSON
                return model_cls.model_validate(extract_json(text))
            except Exception:                               # noqa: BLE001
                pass
            if attempt >= repair_attempts:
                runlog.error(f"structured output still invalid after "
                             f"{repair_attempts} repair(s): {last_error[:200]}",
                             kind="validation_failed")
                break
            runlog.warn(
                f"[{model}] {model_cls.__name__} did not validate "
                f"({last_error[:110]}) — repairing. "
                + ("This provider has no native structured output, so every "
                   "failure costs an extra call."
                   if not caps.json_schema else ""),
                kind="validation_retry", native_schema=caps.json_schema,
                role=model, contract=model_cls.__name__)
            log.warning("structured output invalid (%s), repairing", last_error)
            attempt_messages = list(messages) + [
                {"role": "assistant", "content": text[:6000]},
                {"role": "user", "content":
                 ("That reply did not validate against the required schema.\n"
                  f"Error: {last_error}\n\nReturn the corrected JSON object "
                  "only — no prose, no code fence.")},
            ]

    hint = ""
    if not caps.json_schema:
        hint = (" This provider has no native structured-output support, so "
                "the schema was requested in the prompt only. A model that "
                "cannot follow it reliably is the wrong model for this agent.")
    raise ProviderError(
        f"Could not obtain a valid {model_cls.__name__}: {last_error}.{hint}"
    )

