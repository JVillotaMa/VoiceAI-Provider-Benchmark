"""The caller agent: the instrument that places the call.

One agent, frozen. The only thing that varies between measurement runs is the platform being
dialled, and from here that is a phone number the caller never sees. The transport is an argument
so the same pipeline works against a browser today and a phone line later.

Nothing here is a measurement. Latency is extracted offline from the recorded audio; Pipecat's own
timing observers are platform-internal telemetry and deliberately unused.
"""

import os
import sys

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndWorkerFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    AssistantTurnStoppedMessage,
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
    UserTurnStoppedMessage,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from voicebench.caller.prompt import PERSONALITY_EASY, build_system_prompt

# --- The instrument. Frozen. -------------------------------------------------------------------
# Changing any of these invalidates comparability with runs already published in results/.

# Dated snapshot on purpose: "gpt-4.1-mini" is a moving alias, and a repointed alias would
# silently change the caller between runs. The caller's own LLM speed is outside the metric —
# the stopwatch starts at the caller's last audio frame with energy — so this is chosen for
# script-following, not latency.
CALLER_LLM_MODEL = "gpt-4.1-mini-2025-04-14"

# The voice IS the stimulus: how an utterance ends prosodically is what triggers the endpointing
# of the agent under test. Not a parameter.
CALLER_VOICE_ID = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

# Pinned for the same reason as the voice, and easy to forget precisely because the library
# supplies a default: a pipecat bump inside our own `>=1.7,<2` range can change the default TTS
# model, and the voice would come out of a different synthesiser without a single line of our code
# changing. A voice id alone does not freeze the stimulus — the model that renders it does.
CALLER_TTS_MODEL = "sonic-3.5"

# The transcription model is not part of the stimulus — the agent under test never hears it — but
# it decides what our caller believes it was told, which is what drives the script forward. Pinned
# so a run that derails can be attributed rather than guessed at.
CALLER_STT_MODEL = "nova-3-general"

# The instrument is always a phone call, so the audio rate belongs to the caller rather than to
# whichever transport happens to be plugged in. Cartesia is told to render at 8 kHz directly
# instead of letting the telephony serializer resample down from 24 kHz — one resample fewer, and
# the stimulus is then defined end to end: not "that voice" but that voice through mu-law 8 kHz,
# which is what every platform under test actually hears.
AUDIO_SAMPLE_RATE = 8000

# How much silence before we treat the other party's turn as over. Pipecat 1.x defaults this to
# 0.2s, which is aggressive enough that any mid-sentence pause by the agent under test would make
# our caller talk over it. Waiting longer costs the measurement nothing (caller-side turn
# detection is outside the metric), but waiting far too long invites platforms to fill the silence
# with "are you still there?", so this is deliberate and moderate rather than maximal.
VAD_STOP_SECS = 0.8
USER_TURN_STOP_TIMEOUT_SECS = 5.0

# The caller never re-prompts a slow agent: a re-prompt truncates that agent's latency sample and
# would systematically censor exactly the platforms P99 exists to expose. It waits, and if nothing
# ever comes the call ends here. No usable voice agent answers at 20s, so reaching this ceiling is
# a failed turn for the analysis layer to record as censored — never a slow one, never discarded.
IDLE_TIMEOUT_SECS = 20.0

REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "CARTESIA_API_KEY")


def require_env() -> dict[str, str]:
    """Read the credentials, naming what is missing instead of failing deep in a client.

    `RuntimeError`, not `SystemExit`: the latter is a BaseException, so it walks straight through
    the `except Exception` of any caller — including a websocket handler holding a live, billed
    phone call open.

    Reads the environment and nothing else. It deliberately does not call `load_dotenv()`: a
    validation function that quietly repopulates the process environment from a file on every
    call cannot be reasoned about, and cannot be tested — unsetting a variable would simply be
    undone. Loading `.env` happens once, where the process starts.
    """
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"Missing environment variable(s): {', '.join(missing)}. "
            f"Copy .env.example to .env and fill them in."
        )
    return {name: os.environ[name] for name in REQUIRED_ENV_VARS}


async def end_call(params: FunctionCallParams) -> None:
    """End the phone call. Call this once you have thanked them and said goodbye."""
    logger.info("caller: end_call")
    await params.result_callback({"status": "call ended"})
    await params.llm.push_frame(EndWorkerFrame(), FrameDirection.DOWNSTREAM)


async def run_caller(
    transport: BaseTransport,
    personality: str = PERSONALITY_EASY,
) -> None:
    """Run one call to completion over the given transport."""
    env = require_env()

    stt = DeepgramSTTService(api_key=env["DEEPGRAM_API_KEY"], model=CALLER_STT_MODEL)
    llm = OpenAILLMService(api_key=env["OPENAI_API_KEY"], model=CALLER_LLM_MODEL)
    tts = CartesiaTTSService(
        api_key=env["CARTESIA_API_KEY"],
        voice_id=CALLER_VOICE_ID,
        model=CALLER_TTS_MODEL,
        sample_rate=AUDIO_SAMPLE_RATE,
    )

    context = LLMContext(
        messages=[{"role": "system", "content": build_system_prompt(personality)}],
        tools=[end_call],
    )
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            # Silero supports 8 kHz natively but is less accurate there than at 16 kHz, which
            # makes the framework's 0.2s default worse rather than better. Rate passed explicitly
            # rather than relying on it being propagated.
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=AUDIO_SAMPLE_RATE,
                params=VADParams(stop_secs=VAD_STOP_SECS),
            ),
            user_turn_stop_timeout=USER_TURN_STOP_TIMEOUT_SECS,
            # Empty on purpose: when the agent under test talks over the caller, the caller
            # yields, as a human caller would. That turn is an overlapping and therefore invalid
            # latency sample for the analysis layer to discard — not something to prevent by
            # muting the other party into behaviour it never meets in production.
            user_mute_strategies=[],
        ),
    )

    @aggregators.user().event_handler("on_user_turn_stopped")
    async def _log_them(
        _aggregator: object, _strategy: object, msg: UserTurnStoppedMessage
    ) -> None:
        logger.info(f"THEM: {msg.content}")

    @aggregators.assistant().event_handler("on_assistant_turn_stopped")
    async def _log_us(_aggregator: object, msg: AssistantTurnStoppedMessage) -> None:
        # `interrupted` marks turns the agent under test talked over. Those turns cannot yield a
        # usable latency sample, and the analysis layer needs to know which ones they were.
        mark = " [INTERRUPTED]" if msg.interrupted else ""
        logger.info(f"CALLER{mark}: {msg.content}")

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )

    # No kickoff frame: the caller stays silent until the other party speaks, matching a real
    # outbound call where the shop answers the phone.
    worker = PipelineWorker(
        pipeline,
        idle_timeout_secs=IDLE_TIMEOUT_SECS,
        params=PipelineParams(
            audio_in_sample_rate=AUDIO_SAMPLE_RATE,
            audio_out_sample_rate=AUDIO_SAMPLE_RATE,
        ),
    )
    await WorkerRunner().run(worker)


def setup_logging() -> None:
    """Keep the turn-by-turn transcript readable instead of buried under pipecat's DEBUG."""
    logger.remove()
    logger.add(sys.stderr, level="INFO")
