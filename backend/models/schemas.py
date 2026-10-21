"""Pydantic schemas for chat requests, conversation messages, and answers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatMessage(BaseModel):
    """One prior user or assistant message used as conversation context."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10_000)


class Citation(BaseModel):
    """A source page used to support an assistant answer."""

    title: str = ""
    url: str = Field(min_length=1, max_length=2_048)


class ChatRequest(BaseModel):
    """Question and bounded conversation history for a single chat turn."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(min_length=1, max_length=4_000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question must not be blank.")
        return value


class ChatResponse(BaseModel):
    """Generated answer and source citations for a chat turn."""

    answer: str
    citations: list[Citation] = Field(default_factory=list)
