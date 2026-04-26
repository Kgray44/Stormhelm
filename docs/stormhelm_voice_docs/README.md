# Stormhelm Voice Documentation Pack

This pack documents Stormhelm's Voice and Speaking Pipeline before implementation.

Recommended read order:

1. `01_stormhelm_voice_master_book.md`
2. `02_openai_voice_research_and_provider_strategy.md`
3. `03_voice_architecture_and_data_contracts.md`
4. `04_voice_implementation_roadmap_and_codex_prompt.md`
5. `05_voice_acceptance_and_test_book.md`

This documentation assumes Stormhelm remains a backend-owned, local-first, truthful command system. Voice is an input/output surface; it must not bypass the Core, planner, trust gates, approvals, task graph, recovery, verification, or persona renderer.

Implementation note:

- Voice-0, Voice-1, Voice-2, Voice-3, and Voice-4 foundation status is summarized in `../voice-0-foundation.md`.
- Voice-1 adds manual transcript-to-Core routing only.
- Voice-2 adds controlled audio file/blob/fixture transcription through OpenAI STT and routes the transcript through the same Core bridge.
- Voice-3 adds controlled OpenAI TTS synthesis for Core-approved spoken response candidates and explicit safe test text.
- Voice-3 generates typed audio output artifacts or transient byte payloads. It does not imply playback, live speaking, or that a user heard the response.
- Voice-4 adds a controlled local playback boundary with typed playback requests/results, mock playback, truthful diagnostics/events, and stop playback support.
- Voice-4 does not implement production platform playback by default. The local provider is a stub unless a safe provider is explicitly added later.
- Voice-4 still does not implement microphone capture, wake detection, OpenAI Realtime, streaming transcription, VAD, full barge-in semantics, continuous listening, or voice command execution.
- The mock provider is only for tests and development diagnostics, and status output must identify it as mock.
- Raw audio remains transient by default and must not appear in diagnostics, logs, or event payloads.
- Generated speech audio remains transient by default and must not appear as raw bytes in diagnostics, logs, or event payloads.
- Playback completion means local playback completed through the provider boundary. It does not mean the user heard it and does not change Core task result state.
