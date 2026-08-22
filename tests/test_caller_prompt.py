"""The stimulus must survive edits intact — it is the one thing identical across all platforms."""

from voicebench.caller.prompt import (
    PERSONALITY_EASY,
    PRODUCT,
    TASK,
    build_system_prompt,
)

# The seven intents, in the order the caller must pursue them. Fragments, not whole sentences, so
# the test pins the script's shape without freezing its wording.
INTENTS = (
    "have the",
    "how much it costs",
    "ship to Canada",
    "shipping to Canada costs",
    "negotiate",
    "Accept the price",
    "Thank them",
)


def test_prompt_contains_both_parts() -> None:
    prompt = build_system_prompt(PERSONALITY_EASY)
    assert TASK in prompt
    assert PERSONALITY_EASY in prompt


def test_task_is_frozen_across_personalities() -> None:
    a = build_system_prompt("You are terse.")
    b = build_system_prompt("You are chatty.")
    assert TASK in a
    assert TASK in b
    assert a.replace("You are terse.", "") == b.replace("You are chatty.", "")


def test_default_personality_is_easy() -> None:
    assert build_system_prompt() == build_system_prompt(PERSONALITY_EASY)


def test_seven_intents_appear_in_order() -> None:
    positions = [TASK.find(intent) for intent in INTENTS]
    assert all(p != -1 for p in positions), dict(zip(INTENTS, positions, strict=True))
    assert positions == sorted(positions)


def test_product_is_a_concrete_model_not_a_category() -> None:
    # A category ("a grill") lets the agent under test wander about what is being bought, and then
    # each platform negotiates over something different.
    assert PRODUCT in TASK
    assert len(PRODUCT.split()) >= 3


def test_negotiation_is_bounded() -> None:
    # Without this rule negotiation length varies per platform and the samples stop being drawn
    # from the same distribution.
    assert "SECOND counteroffer" in TASK


def test_caller_does_not_speak_first() -> None:
    assert "Wait for them to speak" in TASK


def test_every_model_is_pinned_not_left_to_a_library_default() -> None:
    # A library default is not frozen: a dependency bump inside our own allowed range can change
    # it, and the stimulus would change with no line of our code touched. A voice id alone does
    # not freeze the stimulus — the model that renders it does.
    from voicebench.caller import agent

    assert agent.CALLER_LLM_MODEL == "gpt-4.1-mini-2025-04-14"  # dated, not a moving alias
    assert agent.CALLER_TTS_MODEL
    assert agent.CALLER_STT_MODEL
    assert agent.CALLER_VOICE_ID
    assert agent.AUDIO_SAMPLE_RATE == 8000
