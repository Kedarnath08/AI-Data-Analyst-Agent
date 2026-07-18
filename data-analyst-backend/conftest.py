"""Shared test fixtures.

Mirrors the sibling RAG backend's strategy: mock ONLY the Gemini boundary
(llm.client.models.generate_content) and exercise everything else for real —
real DuckDB files, real pandas/pdfplumber/python-docx extraction, real
subprocess execution for run_python. This means the agent loop's own
part-parsing and function_response construction (the bug-prone part) is
covered for real, not faked.

Tests run against a temporary working directory so no real data/ files are
touched, and no Gemini/network calls are made.
"""
import os
from types import SimpleNamespace

import pytest
from google.genai import types


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Run each test in its own temp dir so data/datasets and data/uploads are
    fresh and isolated. Modules compute paths relative to cwd at call time."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "datasets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    yield


class FakeGeminiResponse:
    """Mimics GenerateContentResponse: .candidates[0].content.parts and .text."""

    def __init__(self, parts):
        content = SimpleNamespace(parts=parts, role="model")
        self.candidates = [SimpleNamespace(content=content)]

    @property
    def text(self):
        texts = [p.text for p in self.candidates[0].content.parts
                 if getattr(p, "text", None)]
        return "".join(texts) if texts else None


@pytest.fixture
def scripted_agent(monkeypatch):
    """Script a sequence of Gemini turns for llm.run_agent.

    Usage:
        scripted_agent([
            [("list_tables", {})],                 # turn 1: one function call
            [("run_sql", {"query": "SELECT ..."})],# turn 2: one function call
            "The answer is 42.",                    # turn 3: final text answer
        ])

    Each turn is either a list of (tool_name, args) tuples -> function_call
    parts, or a string -> a final text answer.
    """
    from src import llm as llm_module

    def make(turns):
        state = {"i": 0}

        def fake_generate_content(model, contents, config=None):
            if state["i"] >= len(turns):
                # Safety: if the loop asks for more turns than scripted, end it.
                return FakeGeminiResponse([types.Part.from_text(text="(end)")])
            turn = turns[state["i"]]
            state["i"] += 1
            if isinstance(turn, str):
                return FakeGeminiResponse([types.Part.from_text(text=turn)])
            parts = [types.Part.from_function_call(name=n, args=a) for n, a in turn]
            return FakeGeminiResponse(parts)

        monkeypatch.setattr(llm_module.client.models, "generate_content",
                            fake_generate_content)
        return state

    return make
