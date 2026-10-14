"""Thin wrapper over the Anthropic Python SDK.

Every call:
- sends a JSON schema through structured outputs so the reply always parses,
- caches the system prompt (the stable part: instructions, interests, tags),
- sets `effort` per task (low for classification, medium for summaries, high for the weekly report),
- opts into server-side fallback when Claude declines (not available on the Batches API),
- records token usage and cost in `ai_usage`.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from sqlalchemy.orm import Session

from radar.models import AIUsage
from radar.settings import get_settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(RuntimeError):
    pass


class AIRefusal(AIError):
    pass


@dataclass
class CallSpec:
    task: str
    system: str
    user: str
    schema: dict[str, Any]
    effort: str = "low"
    max_tokens: int = 16000


def _system_blocks(system: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _output_config(spec: CallSpec) -> dict[str, Any]:
    return {"effort": spec.effort, "format": {"type": "json_schema", "schema": spec.schema}}


def parse_json_message(message: Any) -> dict[str, Any]:
    if message.stop_reason == "refusal":
        category = getattr(getattr(message, "stop_details", None), "category", None)
        raise AIRefusal(f"Claude từ chối yêu cầu (category={category})")
    if message.stop_reason == "max_tokens":
        raise AIError("Kết quả bị cắt vì chạm max_tokens")
    text = "".join(block.text for block in message.content if block.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIError(f"Claude trả về JSON không hợp lệ: {exc}") from exc


class ClaudeClient:
    def __init__(
        self,
        session: Session,
        model: str,
        pricing: dict[str, dict[str, float]] | None = None,
        fallbacks: bool = True,
        client: Any | None = None,
    ) -> None:
        self.session = session
        self.model = model
        self.pricing = pricing or {}
        self.fallbacks = fallbacks
        if client is None:
            key = get_settings().anthropic_api_key
            client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        self.client = client

    # ── single request ──────────────────────────────────────────────
    def call_json(self, spec: CallSpec) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": spec.max_tokens,
            "system": _system_blocks(spec.system),
            "messages": [{"role": "user", "content": spec.user}],
            "output_config": _output_config(spec),
        }
        try:
            if self.fallbacks:
                message = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                message = self.client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            raise AIError(f"Lỗi Anthropic API {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError(f"Không kết nối được Anthropic API: {exc}") from exc
        except TypeError as exc:
            # The SDK raises TypeError at request time when no credentials are configured.
            raise AIError(f"Chưa cấu hình Anthropic API (ANTHROPIC_API_KEY): {exc}") from exc
        self.record_usage(spec.task, message, batch=False)
        return parse_json_message(message)

    # ── Message Batches (50% cost, asynchronous) ────────────────────
    def submit_batch(self, specs: dict[str, CallSpec]) -> str:
        requests = [
            Request(
                custom_id=custom_id,
                params=MessageCreateParamsNonStreaming(
                    model=self.model,
                    max_tokens=spec.max_tokens,
                    system=_system_blocks(spec.system),
                    messages=[{"role": "user", "content": spec.user}],
                    output_config=_output_config(spec),
                ),
            )
            for custom_id, spec in specs.items()
        ]
        batch = self.client.messages.batches.create(requests=requests)
        return batch.id

    def batch_ended(self, batch_id: str) -> bool:
        return self.client.messages.batches.retrieve(batch_id).processing_status == "ended"

    def wait_batch(self, batch_id: str, timeout_s: int, poll_s: int = 30) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.batch_ended(batch_id):
                return True
            time.sleep(poll_s)
        return self.batch_ended(batch_id)

    def batch_results(self, batch_id: str, task: str) -> dict[str, dict[str, Any] | Exception]:
        """Results keyed by custom_id (results arrive in any order)."""
        out: dict[str, dict[str, Any] | Exception] = {}
        for result in self.client.messages.batches.results(batch_id):
            kind = result.result.type
            if kind == "succeeded":
                message = result.result.message
                self.record_usage(task, message, batch=True)
                try:
                    out[result.custom_id] = parse_json_message(message)
                except AIError as exc:
                    out[result.custom_id] = exc
            else:
                out[result.custom_id] = AIError(f"Batch request {kind}")
        return out

    # ── usage ───────────────────────────────────────────────────────
    def cost(self, model: str, usage: Any, batch: bool) -> float:
        price = self.pricing.get(model) or self.pricing.get(self.model) or {}
        if not price:
            return 0.0
        total = (
            (usage.input_tokens or 0) * price.get("input", 0)
            + (usage.output_tokens or 0) * price.get("output", 0)
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * price.get("cache_read", 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * price.get("cache_write", 0)
        ) / 1_000_000
        return total * (0.5 if batch else 1.0)

    def record_usage(self, task: str, message: Any, batch: bool) -> None:
        usage = message.usage
        model = getattr(message, "model", None) or self.model
        self.session.add(
            AIUsage(
                task=task,
                model=model,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                batch=batch,
                cost_usd=self.cost(model, usage, batch),
                request_id=str(getattr(message, "_request_id", "") or getattr(message, "id", "")),
            )
        )
        self.session.flush()
