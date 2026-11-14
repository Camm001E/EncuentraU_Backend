import base64

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import ValidationError

from app.domain.image_analysis import ObjectImageAnalysis
from app.infrastructure.analysis_errors import ImageAnalysisProviderError
from app.infrastructure.gemini_image_analyzer import build_analysis_prompt


class OpenAIImageAnalyzer:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.ai_timeout_seconds,
            max_retries=0,
        )

    def analyze(self, image_bytes, mime_type, description):
        encoded_image = base64.b64encode(image_bytes).decode()
        schema = ObjectImageAnalysis.model_json_schema()
        schema["required"] = list(schema["properties"])
        try:
            response = self.client.responses.create(
                model=self.settings.openai_model,
                store=False,
                reasoning={"effort": self.settings.openai_reasoning_effort},
                max_output_tokens=self.settings.openai_max_output_tokens,
                instructions=build_analysis_prompt(
                    "La descripción va en el mensaje del usuario."
                ),
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": description},
                            {
                                "type": "input_image",
                                "detail": "high",
                                "image_url": f"data:{mime_type};base64,{encoded_image}",
                            },
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "object_analysis",
                        "strict": True,
                        "schema": schema,
                    }
                },
            )
            for item in response.output:
                for part in getattr(item, "content", []):
                    if getattr(part, "type", None) == "refusal":
                        raise ImageAnalysisProviderError("refusal")
            if response.status != "completed":
                raise ImageAnalysisProviderError("incomplete", fallback_allowed=True)
            result = ObjectImageAnalysis.model_validate_json(
                response.output_text, strict=True
            )
            if result.object_detected and not (result.object_type or "").strip():
                raise ImageAnalysisProviderError("incoherent", fallback_allowed=True)
            if not result.object_detected and not result.requires_another_photo:
                raise ImageAnalysisProviderError("incoherent", fallback_allowed=True)
            result._metadata = {
                "provider": "openai",
                "model": response.model,
                "usage": response.usage.model_dump() if response.usage else None,
            }
            return result
        except ImageAnalysisProviderError:
            raise
        except (APITimeoutError, APIConnectionError):
            raise ImageAnalysisProviderError(
                "connection_or_timeout", fallback_allowed=True
            ) from None
        except APIStatusError as exc:
            transient = exc.status_code in {408, 409, 429} or exc.status_code >= 500
            if exc.code == "insufficient_quota":
                transient = False
            raise ImageAnalysisProviderError(
                "transient_http" if transient else "configuration_or_access",
                fallback_allowed=transient,
            ) from None
        except (ValidationError, ValueError, TypeError, AttributeError):
            raise ImageAnalysisProviderError(
                "invalid_output", fallback_allowed=True
            ) from None
