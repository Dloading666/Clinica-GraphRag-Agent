"""LLM and embedding factory helpers."""

from typing import Any, AsyncIterator

from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import RunnableSerializable
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config.settings import settings


_RETRYABLE_MODEL_ERRORS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "529",
    "busy",
    "overloaded",
    "overloaded_error",
    "rate limit",
    "temporarily unavailable",
    "timeout",
    "connection reset",
    "service unavailable",
)


def _uses_anthropic_api(base_url: str) -> bool:
    normalized = (base_url or "").rstrip("/").lower()
    return normalized.endswith("/anthropic") or "/anthropic/" in normalized


def _is_retryable_model_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _RETRYABLE_MODEL_ERRORS)


def content_to_text(content: Any) -> str:
    """Normalize provider-specific message content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                item_type = item.get("type")
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
                if isinstance(text, dict):
                    value = text.get("value")
                    if isinstance(value, str):
                        parts.append(value)
                        continue
                if item_type:
                    continue
                continue
            parts.append(str(item))
        return "".join(part for part in parts if part)
    return str(content)


class FallbackChatModel(RunnableSerializable[Any, Any]):
    """Route retryable provider failures to a secondary model."""

    primary: Any
    fallback: Any | None = None

    model_config = {"arbitrary_types_allowed": True}

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        try:
            return self.primary.invoke(input, config=config, **kwargs)
        except Exception as exc:
            if self.fallback is None or not _is_retryable_model_error(exc):
                raise
            return self.fallback.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        try:
            return await self.primary.ainvoke(input, config=config, **kwargs)
        except Exception as exc:
            if self.fallback is None or not _is_retryable_model_error(exc):
                raise
            return await self.fallback.ainvoke(input, config=config, **kwargs)

    async def astream(
        self,
        input: Any,
        config: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        try:
            async for chunk in self.primary.astream(input, config=config, **kwargs):
                yield chunk
            return
        except Exception as exc:
            if self.fallback is None or not _is_retryable_model_error(exc):
                raise

        async for chunk in self.fallback.astream(input, config=config, **kwargs):
            yield chunk

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FallbackChatModel":
        primary = self.primary.bind_tools(tools, **kwargs)
        fallback = (
            self.fallback.bind_tools(tools, **kwargs)
            if self.fallback is not None
            else None
        )
        return FallbackChatModel(primary=primary, fallback=fallback)


def _build_chat_model(
    *,
    api_key: str,
    base_url: str,
    model: str,
    streaming: bool = False,
) -> Any:
    if _uses_anthropic_api(base_url):
        return ChatAnthropic(
            api_key=api_key,
            anthropic_api_url=base_url,
            model=model,
            streaming=streaming,
            temperature=0.1,
            max_tokens=4096,
            max_retries=4,
        )

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        streaming=streaming,
        temperature=0.1,
        max_retries=4,
    )


def get_llm(streaming: bool = False) -> Any:
    """Return the configured chat model client."""
    primary = _build_chat_model(
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        model=settings.llm.model,
        streaming=streaming,
    )

    fallback_settings = settings.llm_fallback
    if not (
        fallback_settings.enabled
        and fallback_settings.api_key
        and fallback_settings.base_url
        and fallback_settings.model
    ):
        return primary

    fallback = _build_chat_model(
        api_key=fallback_settings.api_key,
        base_url=fallback_settings.base_url,
        model=fallback_settings.model,
        streaming=streaming,
    )
    return FallbackChatModel(primary=primary, fallback=fallback)


def get_embeddings() -> OpenAIEmbeddings:
    """Return the configured embedding model."""
    return OpenAIEmbeddings(
        api_key=settings.embedding.api_key,
        base_url=settings.embedding.base_url,
        model=settings.embedding.model,
    )
