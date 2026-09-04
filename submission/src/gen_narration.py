"""Regenerate the 8 narration clips with Kokoro (af_heart) instead of macOS `say`."""
from kokoro import KPipeline
# misaki.espeak (imported by kokoro) points EspeakWrapper at its own bundled
# espeak-ng-data, whose baked-in path is broken on this platform (a build-CI
# path, not a runtime one). Re-point it at Homebrew's espeak-ng AFTER the
# kokoro import, since misaki's own import-time call would otherwise win.
from phonemizer.backend.espeak.wrapper import EspeakWrapper
EspeakWrapper.set_library("/opt/homebrew/lib/libespeak-ng.dylib")
EspeakWrapper.set_data_path("/opt/homebrew/Cellar/espeak-ng/1.52.0/share/espeak-ng-data")

import soundfile as sf
import numpy as np

BEATS = [
    "Momentum plus Options Agents: five autonomous agents that trade momentum "
    "stocks and sell option spreads against them, with one risk officer that "
    "can veto anything.",

    "A market-data agent scores momentum and reads real SEC earnings filings. "
    "A strategy agent proposes trades. An optional AI agent can flag risk, but "
    "can never invent or size a trade. A risk agent has hard veto power over "
    "everything. And only the execution agent is allowed to talk to the "
    "broker; it refuses anything that wasn't approved.",

    "The strategy: hold the six strongest momentum stocks, add names with a "
    "confirmed earnings beat, and sell put credit spreads against stocks it "
    "already owns, all sharing one pot of capital that can never be spent "
    "twice.",

    "Backtested from 2011 through 2026, the test period alone returned over a "
    "thousand percent, with a Sharpe ratio of 1.88 and 64 and a half percent "
    "annualized alpha, run once, never tuned on.",

    "But on a mechanically screened, survivorship-bias-free universe of over "
    "900 stocks, about 40 percent of that headline number turns out to be "
    "universe selection, not edge. We say so, up front.",

    "Here's the proof it's not just a backtest. On August 28th, three option "
    "spread orders went out, and every single one expired unfilled, a real "
    "bug in how the limit price was calculated. We fixed it. This morning, at "
    "ten thirty three a m Eastern, the system sold its first real put credit "
    "spread on paper money, and collected the premium, live, with no human in "
    "the loop.",

    "It's paper trading only, behind four independent safety gates, with "
    "capital math that structurally can't double-spend, and sixty four "
    "automated tests to prove it.",

    "Five agents. One veto. Real fills.",
]

pipeline = KPipeline(lang_code='a')

for i, text in enumerate(BEATS, start=1):
    chunks = []
    for _, _, audio in pipeline(text, voice='af_heart', speed=1.0):
        chunks.append(audio.numpy() if hasattr(audio, "numpy") else audio)
    full = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    out = f"beat_{i:02d}_kokoro.wav"
    sf.write(out, full, 24000)
    print(f"beat {i}: {len(full)/24000:.2f}s -> {out}")
