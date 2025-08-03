<!--
Thank you for contributing to ComfyUI Docker! 🎨

Before submitting this PR, please ensure you have:
1. ✅ Created a discussion first describing the problem and solution
2. ✅ Tested your changes locally with Docker Compose
3. ✅ Updated documentation if needed

For more details, see: https://github.com/pixeloven/ComfyUI-Docker#contributing
-->

## Description
Brief description of changes and motivation.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring

## Testing Checklist
Please verify the following before submitting:

### Build Testing
- [ ] All images build successfully: `docker buildx bake all`
- [ ] No build warnings or errors
- [ ] Build cache works correctly

### Runtime Testing
- [ ] Core mode: `docker compose up -d`
- [ ] Complete mode: `docker compose --profile complete up -d`
- [ ] CPU profile: `docker compose --profile cpu up -d`
- [ ] ComfyUI loads successfully (http://localhost:8188)
- [ ] Basic workflow execution works

### Configuration Testing
- [ ] Docker Compose configuration is valid: `docker compose config`
- [ ] Environment variables work correctly
- [ ] Volume mounts are preserved

## Documentation
- [ ] Updated relevant documentation
- [ ] Added/updated code comments where necessary
- [ ] Followed existing code style and patterns

## Additional Notes
Any additional information, context, or screenshots.

## Related Issues
Closes #(issue number)

---

**Reviewers:** @pixeloven/maintainers

<!-- Template version: 2.0 -->
