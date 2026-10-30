## Summary

<!-- Describe the workflow or implementation change. Do not include secrets or live PHI. -->

## Test plan

- [ ] `pytest -q tests`
- [ ] `python -m compileall -q api modules services components`
- [ ] `docker compose --env-file docker/.env.example -f docker/docker-compose.yml config`
- [ ] FastAPI health check passes
- [ ] Langflow component reload tested, when applicable

## Security and data

- [ ] No credentials, tokens, audio, transcripts, or PHI included
- [ ] No generated reports, cache files, or model files included
