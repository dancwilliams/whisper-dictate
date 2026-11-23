# Idle GPU memory and native crashes, 2026-11

Should ASR and S1 move into a child process that is killed on idle? The audit of
2026-11-21 proposed it for two reasons: to give back the CUDA context `asr.py` says is
held for life, and to keep a native crash away from the hotkey. This records both
checks (`plans/2026-11-21-audit-follow-up.md`, Phase 9).

## Idle GPU memory

Measured 2026-11-21 on the running app (started 2026-11-11 13:01, 236.7 hours up, 166
Whisper loads in that time), with Windows' `\GPU Process Memory(pid_*)\Dedicated Usage`
counter:

| State | Dedicated GPU memory |
|---|---|
| Whisper large-v3-turbo and S1 loaded | 3,908 MB |
| Both released by the idle timer, eight seconds later | 568 MB |

The card is an RTX 5090 with 32,607 MB, so the idle app holds 1.7% of it. The old leak
was 64 MB per load (`asr.py`, the `_parked` comment): 166 loads would have been about
10.6 GB. Park-and-reload is holding and nothing grows. A child process would give back
about half a gigabyte and add a process start and a CUDA start to every cold dictation.

## Native crashes, 2026-09-18 to 2026-11-22

The Application event log could not answer this: it is a 20 MB circular log and its
oldest event is 2026-11-22 18:03. The Windows Error Reporting archive
(`C:\ProgramData\Microsoft\Windows\WER\ReportArchive`, oldest entry 2026-05-20) and
`%LOCALAPPDATA%\CrashDumps` go back far enough, so they were searched instead.

| When (local) | Report | What it was | Python traceback in the app log |
|---|---|---|---|
| 2026-09-20 11:18 | `AppHang_python.exe` | The September build on Python 3.11, run from a console, Cohere backend. Windows marked it not responding and closed it. A hang, not a crash. | No |
| 2026-10-14 09:56 | `AppCrash_pythonw.exe` (two reports, two dumps, one process, pid 57420) | The app. `c0000409` in `ucrtbase.dll` with data `7`, `FAST_FAIL_FATAL_APP_EXIT`: `abort()` | No |

One native crash in 66 days. The app log puts it during testing of the tuned-model
picker (#102, merged that day): the `smoke` fine-tune was picked three times in 42
seconds, each pick releasing the resident model (`_reload_backend`), and the app died 15
seconds after the third with no dictation in between. A scan of the faulting thread's stack finds `ctranslate2.dll`,
`cudnn64_9.dll` and `VCRUNTIME140.dll` frames just above the abort, which fits an
uncaught C++ exception inside CTranslate2. The dump holds only that thread and there are
no symbols, so this is a lead, not a proof.

Since then: 438 Whisper loads and 1,485 pastes (to 2026-11-22 20:08) with no further
crash report.

## Decision

**Not built.** The memory half does not pay: 568 MB idle, flat. The crash half is one
`abort()` in CTranslate2 under a burst of model switches on a test day, not seen again
in 438 loads. A child process would turn such a crash into one failed dictation, at the
price of a process start on every cold dictation and a pipe through the pipeline.

What reopens it: a second native crash of the app, above all one in ordinary dictation
rather than model switching. Or idle memory that climbs: the same counter well above
568 MB after a comparable uptime. A move to ONNX Runtime would change the numbers and
need a fresh reading.

If reopened, the shape is a `Resident` factory that spawns the child with
`multiprocessing` and returns a proxy whose `transcribe` and `clean` go over a pipe and
whose `unload()` terminates the child; `gui.py` does not change and `_parked` is
deleted.

To repeat the crash search: list `ReportArchive` and `ReportQueue` folders whose name
contains `python`, read each `Report.wer`, and check `%LOCALAPPDATA%\CrashDumps` for
`pythonw.exe.*.dmp`.
