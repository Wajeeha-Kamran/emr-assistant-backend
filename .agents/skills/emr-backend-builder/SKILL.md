---
name: emr-backend-builder
description: Guides implementation of the AI-Powered EMR Assistant backend (FastAPI/PostgreSQL) phase by phase, following this project's own SPMP/SRS/SDD/STD documentation. Use when building, continuing, or resuming backend work on the EMR Assistant project, or when the user asks to build the backend, start the next module, continue the roadmap, or mentions consultation sessions, transcripts, SOAP notes, ICD-10/CPT code suggestions, doctor sign-off, or EMR sync for this project.
---

# EMR Assistant Backend Builder

## What this skill does
Implements the AI-Powered EMR Assistant backend one roadmap module at a time, in the exact phase order defined in `resources/backend_roadmap.md`. Each module is one self-contained unit of work: implement → test → checklist → pause for approval → next module. This skill is intentionally sequential, not autonomous end-to-end — the project involves authentication, clinical data, and signed records, so checkpoints are mandatory, not optional.

## Before doing anything: read the roadmap
Read `resources/backend_roadmap.md` in full before starting or resuming work. It contains the tech stack, dependency list, folder structure, and every module's Objective / Why it comes now / Features / Files & folders / Database changes / API endpoints / Dependencies / Testing requirements / Completion checklist. Treat it as the source of truth. Do not invent modules, reorder phases, merge modules together, or skip ahead to a later phase to "save time."

If anything in the roadmap seems wrong, outdated, or in conflict with code already in the repo, say so and ask — do not silently reinterpret a requirement (e.g. the four mandatory SOAP sections, two-role diarization, the ≤5-minute retention window, the 85% accuracy targets) to make implementation easier.

## Figuring out where we are
- Look for `PROGRESS.md` at the project root.
- If it doesn't exist, create it: list every phase and module from the roadmap with an empty checkbox (`- [ ]`), and start at Phase 0 / Module 0.1.
- If it exists, resume at the first unchecked module. Don't restart finished work.
- After a module is genuinely complete (see checklist step below), check it off in `PROGRESS.md` and commit that change.

## Environment checks — always check before installing anything
Never install or upgrade a system-level tool without checking first, and never do it silently.
1. **Python:** run `python3 --version` (or `python --version` on Windows). If it reports 3.11 or newer, use it as-is — do not reinstall, upgrade, or touch it. Only install Python if it's genuinely missing or older than 3.11, and tell the user before doing so.
2. **PostgreSQL, Docker, Git, FFmpeg:** check the same way (`psql --version`, `docker --version`, `git --version`, `ffmpeg -version`). Report what's already present. Only propose installing what's actually missing.
3. **Virtual environment:** always create and use a project-local `.venv` for Python packages. Never run `pip install` against the system/global Python interpreter.
4. **Python packages:** before installing anything, check `requirements.txt` / `pip freeze` so nothing already present gets reinstalled or duplicated.
5. If a check turns up a version that's close but slightly old, ask the user before upgrading rather than assuming it's fine to change.

## Keep everything minimal — no speculative code
Build exactly what the current module's checklist requires, nothing more.
- Do not add dependencies, config options, environment variables, or settings fields that the current module doesn't actually use yet — even if a later module will need something similar. Add it when that module arrives, not before.
- Do not scaffold folders, files, or stub functions for future modules ahead of time. Empty placeholders are clutter, not progress.
- No dead code, no commented-out alternate implementations, no "just in case" try/except branches for situations that can't currently occur.
- Prefer the simplest tool that satisfies the module's requirement. Concretely: use FastAPI's built-in `BackgroundTasks` instead of Celery+Redis until Phase 8.3 specifically requires true task-queue concurrency; use `APScheduler` instead of Celery for the Phase 7 retention job unless a later module proves it's insufficient. Don't introduce Redis, Celery, or other extra services before the roadmap actually calls for them.
- If unsure whether something is in scope for the current module, leave it out and ask, rather than including it "to be safe."

## Language scope — English-only for now
This build only needs to handle English-language consultation audio.
- Lock Whisper's transcription call to `language="en"` explicitly — do not rely on or build out auto-language-detection.
- Do not add multi-language handling, language-selection config, or any i18n/l10n groundwork. This is a deliberate, temporary scope limit, not an oversight — leave a short code comment noting it's English-only by design so it's clear to anyone reading it later.
- If multi-language support is wanted later, that's a new, explicitly-requested module — don't build toward it preemptively.

## Hardware-heavy steps — handle carefully
Whisper, BioGPT, and ClinicalBERT are large ML models and can be slow or memory-hungry on an ordinary laptop.
- Default to the smallest model checkpoint that works for development (e.g. Whisper `base` or `small`, not `large`).
- Before downloading any model file over roughly 1GB, tell the user its approximate size and wait for confirmation.
- Default to CPU execution. Check for a GPU (e.g. `torch.cuda.is_available()`) before assuming one exists, and fall back to CPU automatically rather than erroring out.
- If something is clearly too slow on CPU (e.g. full-size BioGPT inference), say so plainly and suggest the lighter option from the roadmap rather than pushing through a bad experience silently.

## Working through a module
For each module, in order:
1. Announce which module is starting; paste its Objective and Completion Checklist from the roadmap so the target is visible before work begins.
2. Use Plan mode first — produce an implementation plan artifact before writing code, especially for anything beyond trivial boilerplate.
3. Touch only the files/folders listed for that module. Do not modify files reserved for a later module.
4. Install only the dependencies listed for that specific module (after the environment check above).
5. Write and run the tests specified for that module. The module is not complete until its tests pass — code existing is not the same as the module being done.
6. Walk through the module's completion checklist item by item and confirm each box is genuinely satisfied, not just plausible.
7. Check the module off in `PROGRESS.md`, commit with a descriptive message, and give a short plain-language summary of what changed.
8. **Stop and wait for explicit go-ahead before starting the next module.** Do not chain multiple modules together in one unattended run, even if a fast mode or full-autonomy setting is active.

## Mandatory hard stops
On top of the normal per-module pause above, these specific points always require the user's own explicit review — never self-approve them, no matter what autonomy mode is active:
- **Module 0.3** (Doctor Authentication) — before finalizing JWT secret handling and password hashing configuration.
- **Module 5.2** (Signature & Sign endpoint) — before finalizing the logic that makes a signed SOAP note immutable.
- **Module 8.1** (Security Hardening) — the entire module needs a human read-through; summarize the changes and wait.
- Anything that deletes data, drops a database or table, force-pushes, or rewrites git history.
- Installing any package or tool outside the project's virtual environment or containers.

## Definition of done for the whole backend
Only consider the backend finished when every item in the roadmap's final "Definition of Done" checklist (Module 10.4) is checked — all use cases, functional requirements, and STD test cases implemented and passing, and the security module manually reviewed.
