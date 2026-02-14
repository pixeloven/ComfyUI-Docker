# Tasks: SageAttention Update and SageAttention 3 Support

**Input**: Design documents from `/specs/002-sage-attention-update/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, quickstart.md

**Tests**: Manual validation only (per spec - no automated tests requested)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Project structure**: `services/comfy/complete/` for requirements changes
- **Docker build**: Uses `docker-bake.hcl` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No setup required - this is a minimal dependency update. The project infrastructure already exists.

- [x] T001 Verify current state of services/comfy/complete/extra-requirements.txt

---

## Phase 2: User Story 3 - Rebuild and Validate Docker Images (Priority: P1) 🎯 MVP

**Goal**: Update requirements file and rebuild Docker images successfully

**Independent Test**: Run `docker buildx bake complete-cuda` and verify build completes without errors

**Note**: This is listed first because it's a prerequisite for validating the other user stories

### Implementation

- [x] T002 [US3] Update comment in services/comfy/complete/extra-requirements.txt to reflect accurate build version
- [x] T003 [US3] Update extra-requirements.txt with sageattention 2.2.0 and sageattn3 1.0.0 (build.15)
- [x] T004 [US3] Rebuild complete-cuda image with `docker buildx bake complete-cuda`
- [x] T005 [US3] Verify Docker build completes successfully without errors

**Checkpoint**: Docker image built successfully - package validation can now begin

---

## Phase 3: User Story 1 - Verify SageAttention 2 Installation (Priority: P1)

**Goal**: Confirm SageAttention 2 v2.2.0 is properly installed and importable

**Independent Test**: Run `docker compose exec complete-cuda python -c "import sageattention; print(sageattention.__version__)"` and verify output shows version 2.2.0

### Implementation

- [x] T006 [US1] Start complete-cuda container with `docker run`
- [x] T007 [US1] Verify sageattention module imports successfully in container
- [x] T008 [US1] Verify sageattention version reports 2.2.0

**Checkpoint**: SageAttention 2 validated - existing functionality confirmed working

---

## Phase 4: User Story 2 - Add SageAttention 3 Support (Priority: P2)

**Goal**: Confirm SageAttention 3 (sageattn3) v1.0.0 is properly installed and importable

**Independent Test**: Run `docker compose exec complete-cuda python -c "import sageattn3; print('sageattn3 OK')"` and verify no import errors

### Implementation

- [x] T009 [US2] Verify sageattn3 module imports successfully in container
- [x] T010 [US2] Verify sageattn3 provides sageattn3_blackwell function

**Checkpoint**: SageAttention 3 validated - sageattn3 1.0.0 installed and working

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and cleanup

- [x] T011 [P] Review docs/user-guides/performance.md for sageattn3 documentation needs
- [x] T012 Run validation - sageattention imports successfully, version 2.2.0 confirmed
- [x] T013 No persistent containers to stop (used docker run --rm)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies - verification only
- **Phase 2 (US3 - Build)**: Depends on Phase 1 - creates the Docker image
- **Phase 3 (US1)**: Depends on Phase 2 - requires built image
- **Phase 4 (US2)**: Depends on Phase 2 - requires built image (can run parallel with Phase 3)
- **Phase 5 (Polish)**: Depends on Phases 3 and 4

### User Story Dependencies

- **User Story 3 (Build)**: No dependencies on other stories - BLOCKS US1 and US2
- **User Story 1 (SageAttention 2)**: Depends on US3 (image must be built)
- **User Story 2 (SageAttention 3)**: Depends on US3 (image must be built), independent of US1

### Parallel Opportunities

- T006, T007, T008 (US1) can run in parallel with T009, T010 (US2) after T005 completes
- T011, T012 (Polish) are independent and can run in parallel

---

## Parallel Example: Validation Phase

```bash
# After Docker build completes (T005), launch US1 and US2 validation in parallel:
Task: "Verify sageattention module imports successfully in container"
Task: "Verify sageattn3 module imports successfully in container"
```

---

## Implementation Strategy

### MVP First (Minimal Change)

1. Complete T001: Verify current state
2. Complete T002-T005: Update requirements and rebuild image
3. **STOP and VALIDATE**: Confirm build succeeds
4. Complete T006-T008: Validate SageAttention 2
5. Complete T009-T010: Validate SageAttention 3

### Incremental Delivery

1. T001-T005 → Image built with both packages
2. T006-T008 → SageAttention 2 validated (core functionality)
3. T009-T010 → SageAttention 3 validated (new feature)
4. T011-T013 → Documentation and cleanup

---

## Notes

- This is a minimal change - single file modification plus validation
- Total tasks: 13
- No code changes required - only requirements.txt update
- All validation is manual (docker exec commands)
- US1 and US2 validation can proceed in parallel once build completes
- Commit after T003 (requirements change) and T005 (build validated)
