# Feature Specification: SageAttention Update and SageAttention 3 Support

**Feature Branch**: `002-sage-attention-update`
**Created**: 2026-01-31
**Status**: Draft
**Input**: User description: "Update the version of sage (sage attention 2) as well as add sage attention 3. Rebuild the images and test they are installed and working. https://github.com/pixeloven/SageAttention/releases/tag/v2.2.0-build.13"

## Clarifications

### Session 2026-01-31

- Q: How should SageAttention 3 be installed? → A: Separate wheel - sageattn3 v3.0.0 is a distinct package from the same release (corrected after research)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Verify SageAttention 2 Installation (Priority: P1)

As a ComfyUI user running the complete profile, I want SageAttention 2 to be updated to the latest version (v2.2.0-build.13) so that I have the most current optimizations and bug fixes.

**Why this priority**: This is the core functionality that already exists. Ensuring the existing SageAttention 2 continues to work correctly after the update is critical for all current users.

**Independent Test**: Can be fully tested by running the complete-cuda container and executing `python -c "import sageattention; print(sageattention.__version__)"` to verify the correct version is installed.

**Acceptance Scenarios**:

1. **Given** a freshly built complete-cuda Docker image, **When** a user imports the sageattention module, **Then** the module loads successfully without errors
2. **Given** the sageattention module is loaded, **When** a user checks the version, **Then** version 2.2.0 is reported
3. **Given** a ComfyUI workflow using SageAttention, **When** the workflow executes, **Then** attention operations complete successfully using the optimized kernels

---

### User Story 2 - Add SageAttention 3 Support (Priority: P2)

As a ComfyUI user with a compatible GPU (Blackwell architecture), I want access to SageAttention 3 (SageAttn3) so that I can leverage the latest GPU-optimized attention kernels for improved performance.

**Why this priority**: This adds new functionality that extends the optimization options available to users with newer hardware. It builds on top of the working SageAttention 2 installation.

**Independent Test**: Can be fully tested by running the complete-cuda container and executing `python -c "from sageattention import sageattn3; print('SageAttn3 OK')"` to verify the module is available.

**Acceptance Scenarios**:

1. **Given** a freshly built complete-cuda Docker image, **When** a user imports the sageattn3 module from sageattention, **Then** the module loads successfully without errors
2. **Given** SageAttn3 is available, **When** a user with compatible GPU runs a workflow, **Then** the optimized Blackwell kernels can be utilized

---

### User Story 3 - Rebuild and Validate Docker Images (Priority: P1)

As a maintainer, I need to rebuild the Docker images with the updated SageAttention packages and verify they build successfully so that users can pull working images.

**Why this priority**: Without successful image builds, no users can access the updates. This is a prerequisite for deployment.

**Independent Test**: Can be fully tested by running `docker buildx bake complete-cuda` and verifying the build completes without errors.

**Acceptance Scenarios**:

1. **Given** the updated requirements file with new wheel URLs, **When** the Docker build is executed, **Then** the build completes successfully
2. **Given** a successful build, **When** the image is started, **Then** the container runs without errors

---

### Edge Cases

- What happens when the wheel download fails during build?
  - The Docker build should fail with a clear error message indicating the download URL was unreachable
- What happens when a user with incompatible GPU attempts to use SageAttn3?
  - The import should succeed but runtime usage should fall back to standard attention or SageAttention 2 gracefully
- What happens when both SageAttention 2 and 3 are used in the same workflow?
  - Both should coexist without conflicts; users should be able to choose which implementation to use based on their hardware

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST install SageAttention 2 version 2.2.0 from the v2.2.0-build.13 release
- **FR-002**: System MUST install SageAttention 3 (sageattn3) v3.0.0 as a separate wheel for Blackwell GPU support
- **FR-003**: Both SageAttention versions MUST be importable within the Python environment
- **FR-004**: System MUST use pre-built wheel files matching the container's Python version (3.12), PyTorch version (2.8+), and CUDA version (12.8+)
- **FR-005**: Docker image builds MUST complete successfully with both packages installed
- **FR-006**: Installation MUST NOT break existing ComfyUI functionality or other custom node dependencies

### Key Entities

- **SageAttention 2**: The existing attention optimization library, being updated to v2.2.0-build.13
- **SageAttention 3 (SageAttn3)**: New attention optimization targeting Blackwell GPU architecture
- **Pre-built Wheels**: Platform-specific compiled packages from the pixeloven/SageAttention GitHub releases
- **extra-requirements.txt**: The file in `services/comfy/complete/` that specifies which wheels to install

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: SageAttention 2 module imports successfully and reports version 2.2.0
- **SC-002**: SageAttention 3 (sageattn3) module imports successfully without errors
- **SC-003**: Docker image build completes within normal build time (no significant regression)
- **SC-004**: Container startup completes without import errors or dependency conflicts
- **SC-005**: Existing ComfyUI workflows using SageAttention continue to function correctly

## Assumptions

- The pixeloven/SageAttention GitHub releases contain pre-built wheels for the required platform specifications (Python 3.12, PyTorch 2.8+, CUDA 12.8+, Linux x86_64)
- SageAttention 3 (sageattn3) v3.0.0 is available as a separate wheel in the same v2.2.0-build.13 release
- The wheel naming convention follows the pattern used by existing wheels
- No breaking API changes exist between current and updated SageAttention 2 versions
