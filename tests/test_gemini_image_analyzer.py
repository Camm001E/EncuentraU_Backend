from app.domain.image_analysis import ObjectImageAnalysis
from app.infrastructure.gemini_image_analyzer import (
    GeminiImageAnalyzer,
    build_analysis_prompt,
)


class FakeResponse:
    def __init__(self, parsed: ObjectImageAnalysis) -> None:
        self.parsed = parsed.model_dump()
        self.text = parsed.model_dump_json()


class FakeModels:
    def __init__(self, result: ObjectImageAnalysis) -> None:
        self._result = result
        self.last_request: dict | None = None

    def generate_content(self, **kwargs) -> FakeResponse:
        self.last_request = kwargs
        return FakeResponse(self._result)


class FakeGeminiClient:
    def __init__(self, result: ObjectImageAnalysis) -> None:
        self.models = FakeModels(result)


def test_gemini_analyzer_sends_image_and_parses_schema() -> None:
    expected = ObjectImageAnalysis(
        object_detected=True,
        object_type="morral",
        category="bolsos",
        primary_color="negro",
        secondary_colors=["blanco"],
        brand="nike",
        shape="rectangular",
        visible_features=["logotipo blanco en el frente"],
        visible_text=["nike"],
        image_quality="buena",
        confidence="alta",
        requires_another_photo=False,
        warnings=[],
    )
    fake_client = FakeGeminiClient(expected)
    analyzer = GeminiImageAnalyzer(
        api_key="test-key",
        model="gemini-test-model",
        client=fake_client,
    )

    result = analyzer.analyze(
        image_bytes=b"image-bytes",
        mime_type="image/png",
        description="Morral negro encontrado",
    )

    assert result == expected
    request = fake_client.models.last_request
    assert request is not None
    assert request["model"] == "gemini-test-model"
    image_part = request["contents"][1]
    assert image_part.inline_data.mime_type == "image/png"
    assert image_part.inline_data.data == b"image-bytes"
    assert request["config"].response_mime_type == "application/json"
    assert request["config"].response_schema is None
    assert (
        request["config"].response_json_schema
        == ObjectImageAnalysis.model_json_schema()
    )
    assert request["config"].response_json_schema["additionalProperties"] is False


def test_prompt_requests_geometry_and_unknown_instead_of_component_names() -> None:
    prompt = build_analysis_prompt("Descripción no verificada")
    assert "shape debe describir exclusivamente geometría" in prompt
    assert "devuelve null" in prompt
    assert "No repitas object_type, category ni el nombre de una pieza" in prompt
