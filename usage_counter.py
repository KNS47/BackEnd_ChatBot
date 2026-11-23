from contextvars import ContextVar

# Child tasks created by asyncio.wait_for share this request's mutable counter.
generation_usage: ContextVar[list[int] | None] = ContextVar("generation_usage", default=None)


def add_generation_usage(response: dict) -> None:
    counter = generation_usage.get()
    metadata = response.get("usageMetadata")
    if counter is not None and isinstance(metadata, dict):
        tokens = metadata.get("totalTokenCount")
        if type(tokens) is int and tokens >= 0:
            counter[0] += tokens
