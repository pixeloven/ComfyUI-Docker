# Tasks: Runtime UID/GID Support

**Input**: Design documents from `/specs/001-runtime-uid-gid/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, quickstart.md

**Tests**: Manual container testing specified in plan.md. No automated test tasks generated (tests not explicitly requested).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Docker infrastructure project**: `services/`, `examples/`, `docs/`
- Runtime Dockerfiles: `services/runtime/`
- Core Dockerfiles: `services/comfy/core/`
- Complete Dockerfiles: `services/comfy/complete/`
- Example compose files: `examples/*/docker-compose.yml`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install gosu in base runtime images (required for all profiles)

- [x] T001 [P] Add gosu installation to services/runtime/dockerfile.cuda.runtime
- [x] T002 [P] Add gosu installation to services/runtime/dockerfile.cpu.runtime

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core entrypoint infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Create new entrypoint.sh with dynamic user/group creation in services/comfy/core/entrypoint.sh
- [x] T004 Update services/comfy/core/dockerfile.comfy.core to remove hardcoded USER directive and run entrypoint as root

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Custom UID/GID Container Startup (Priority: P1) 🎯 MVP

**Goal**: Enable containers to run with any specified PUID/PGID, eliminating `getpwuid` errors

**Independent Test**: Run container with PUID=3000/PGID=3000, verify startup succeeds and files have correct ownership

### Implementation for User Story 1

- [x] T005 [US1] Add PUID/PGID validation logic to services/comfy/core/entrypoint.sh (numeric check, range validation, error messages)
- [x] T006 [US1] Add group creation logic to services/comfy/core/entrypoint.sh (create group if GID not found)
- [x] T007 [US1] Add user creation logic to services/comfy/core/entrypoint.sh (create user if UID not found, with /app home)
- [x] T008 [US1] Add chown for critical directories (/app, /app/ComfyUI) to services/comfy/core/entrypoint.sh
- [x] T009 [US1] Add gosu exec privilege drop to services/comfy/core/entrypoint.sh
- [x] T010 [US1] Add startup log line "Starting with UID:GID = X:Y" to services/comfy/core/entrypoint.sh
- [x] T011 [P] [US1] Update examples/core-gpu/docker-compose.yml to include PUID/PGID environment variables
- [x] T012 [P] [US1] Update examples/complete-gpu/docker-compose.yml to include PUID/PGID environment variables
- [x] T013 [P] [US1] Update examples/core-cpu/docker-compose.yml to include PUID/PGID environment variables

**Checkpoint**: At this point, User Story 1 should be fully functional and testable independently

---

## Phase 4: User Story 2 - Default UID/GID Backward Compatibility (Priority: P2)

**Goal**: Ensure existing deployments without PUID/PGID continue to work with default UID 1000:GID 1000

**Independent Test**: Run container without any PUID/PGID variables, verify it runs as UID 1000:GID 1000

### Implementation for User Story 2

- [x] T014 [US2] Add default value fallback (PUID=${PUID:-1000}, PGID=${PGID:-1000}) to services/comfy/core/entrypoint.sh
- [x] T015 [US2] Verify docker-compose.yml files use ${PUID:-1000} syntax for defaults in examples/core-gpu/docker-compose.yml
- [x] T016 [US2] Verify docker-compose.yml files use ${PGID:-1000} syntax for defaults in examples/core-cpu/docker-compose.yml
- [x] T017 [US2] Verify docker-compose.yml files use defaults in examples/complete-gpu/docker-compose.yml

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently

---

## Phase 5: User Story 3 - Security-Compliant Non-Root Execution (Priority: P3)

**Goal**: Ensure application processes run as non-root user after initialization, meeting security compliance

**Independent Test**: Inspect running container with `ps aux`, confirm no application processes run as root

### Implementation for User Story 3

- [x] T018 [US3] Add root warning log when PUID=0 specified to services/comfy/core/entrypoint.sh
- [x] T019 [US3] Verify exec gosu ensures no root shell remains (already implemented in T009, verify behavior)
- [x] T020 [US3] Add edge case handling for existing system users in services/comfy/core/entrypoint.sh

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, multi-profile testing, and final validation

- [x] T021 [P] Update docs/user-guides/running.md with PUID/PGID documentation section
- [x] T022 [P] Update README.md environment variables section with PUID/PGID reference
- [x] T023 Build and test core-cuda profile with custom PUID/PGID
- [x] T024 Build and test core-cpu profile with custom PUID/PGID
- [x] T025 Build and test complete-cuda profile with custom PUID/PGID
- [x] T026 Run quickstart.md validation checklist against all profiles

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - User Story 1 must complete before User Story 2 (US2 verifies US1 defaults work)
  - User Story 3 can run in parallel with US2 after US1 completes
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - Core implementation
- **User Story 2 (P2)**: Depends on User Story 1 - Verifies backward compatibility
- **User Story 3 (P3)**: Can start after User Story 1 - Security verification

### Within Each User Story

- Entrypoint logic tasks (T005-T010) must be sequential (same file)
- Compose file updates (T011-T013) can run in parallel
- Documentation tasks can run in parallel

### Parallel Opportunities

- Phase 1: T001 and T002 can run in parallel (different runtime Dockerfiles)
- Phase 3: T011, T012, T013 can run in parallel (different compose files)
- Phase 6: T021 and T022 can run in parallel (different documentation files)

---

## Parallel Example: Phase 1

```bash
# Launch both runtime Dockerfile updates together:
Task: "Add gosu installation to services/runtime/dockerfile.cuda.runtime"
Task: "Add gosu installation to services/runtime/dockerfile.cpu.runtime"
```

## Parallel Example: Phase 3 Compose Updates

```bash
# Launch all compose file updates together after T010:
Task: "Update examples/core-gpu/docker-compose.yml to include PUID/PGID environment variables"
Task: "Update examples/complete-gpu/docker-compose.yml to include PUID/PGID environment variables"
Task: "Update examples/core-cpu/docker-compose.yml to include PUID/PGID environment variables"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (install gosu)
2. Complete Phase 2: Foundational (new entrypoint, Dockerfile changes)
3. Complete Phase 3: User Story 1 (custom UID/GID support)
4. **STOP and VALIDATE**: Test with PUID=3000/PGID=3000
5. Can deploy/demo after Phase 3

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test custom UID/GID → MVP complete!
3. Add User Story 2 → Test default behavior → Backward compatibility verified
4. Add User Story 3 → Test security compliance → Full feature complete
5. Complete Polish → Documentation and multi-profile testing

### Single Developer Strategy

Execute in order: T001 → T002 → T003 → T004 → T005-T013 → T014-T017 → T018-T020 → T021-T026

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- T005-T010 modify the same file (entrypoint.sh) - execute sequentially
- Build and test tasks (T023-T025) require all code changes complete
