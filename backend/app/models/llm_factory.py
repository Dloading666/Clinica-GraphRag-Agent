"""LLM and Embedding factory - returns configured OpenAI-compatible clients"""
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.config.settings import settings


def get_llm(streaming: bool = False) -> ChatOpenAI:
    """Return configured LLM (Qwen via DashScope)"""
    return ChatOpenAI(
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        model=settings.llm.model,
        streaming=streaming,
        temperature=0.1,
    )


def get_embeddings() -> OpenAIEmbeddings:
    """Return configured embedding model"""
    return OpenAIEmbeddings(
        api_key=settings.embedding.api_key,
        base_url=settings.embedding.base_url,
        model=settings.embedding.model,
    )
