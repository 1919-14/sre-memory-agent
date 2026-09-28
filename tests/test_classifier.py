"""Classification must work with no network at all, and must escalate when unsure."""

from __future__ import annotations

from sre_agent.classify import Classifier, taxonomy
from sre_agent.config import Settings
from sre_agent.llm import ScriptedLLM
from sre_agent.models import ErrorClass, Fixability, Incident


def classify(error: str, *, confidence: float = 0.6) -> tuple[object, Classifier]:
    # A ScriptedLLM with no handlers raises, which exercises the heuristic fallback.
    llm = ScriptedLLM()
    settings = Settings(classifier_min_confidence=confidence)
    classifier = Classifier(llm, settings)
    incident = Incident(repository="demo", error=error)
    return classifier.classify(incident), classifier


def test_pool_exhaustion_is_connection_exhaustion() -> None:
    classification, _ = classify("RedisConnectionError: connection pool exhausted")

    assert classification.error_class is ErrorClass.CONNECTION_EXHAUSTION
    assert classification.source == "heuristic"
    assert classification.likely_fixability is Fixability.CODE_FIXABLE


def test_expired_credential_escalates() -> None:
    classification, _ = classify(
        "AuthenticationError: billing API token expired (HTTP 401 Unauthorized)"
    )

    assert classification.error_class is ErrorClass.AUTH_CREDENTIAL
    assert classification.likely_fixability is Fixability.ESCALATE
    assert classification.needs_escalation is True


def test_missing_module_is_dependency_drift() -> None:
    classification, _ = classify("ModuleNotFoundError: No module named 'redis'")

    assert classification.error_class is ErrorClass.DEPENDENCY_DRIFT


def test_unknown_failure_escalates() -> None:
    classification, _ = classify("something entirely unexpected happened")

    assert classification.error_class is ErrorClass.UNKNOWN
    assert classification.likely_fixability is Fixability.ESCALATE


def test_low_confidence_forces_escalation() -> None:
    """We must not patch what we cannot classify."""
    classification, _ = classify("connection pool exhausted", confidence=0.99)

    assert classification.likely_fixability is Fixability.ESCALATE
    assert classification.confidence < 0.99


def test_specialist_is_attached_for_enabled_classes() -> None:
    settings = Settings(classifier_min_confidence=0.1, specialist_classes=["connection-exhaustion"])
    incident = Incident(repository="demo", error="RedisConnectionError: connection pool exhausted")

    classification = Classifier(ScriptedLLM(), settings).classify(incident)

    assert classification.specialist == "connection_exhaustion"


def test_existing_error_class_beats_generic_config_keyword() -> None:
    classification, _ = classify(
        "redis.exceptions.ConnectionError: too many connections; check config"
    )

    assert classification.error_class in (
        ErrorClass.CONNECTION_EXHAUSTION,
        ErrorClass.CONFIG_REGRESSION,
    )


def test_taxonomy_covers_every_class() -> None:
    for error_class in ErrorClass:
        spec = taxonomy.spec_for(error_class)
        assert spec.label
    assert taxonomy.default_fixability(ErrorClass.AUTH_CREDENTIAL) is Fixability.ESCALATE
