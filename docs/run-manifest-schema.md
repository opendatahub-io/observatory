# Run Manifest Schema

The run manifest (`run-manifest.json`) is a JSON file produced by a CI pipeline job and stored as a build artifact. When Observatory's collector downloads artifacts, it parses this file and populates the provenance tables (commands, packages, containers).

---

## Schema definition

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | `string` | Yes | Schema version. Currently always `"1"`. |
| `pipeline_slug` | `string` | No | Observatory pipeline slug for correlation. If omitted, the collector uses the pipeline it is already scraping. |
| `commands` | `array[Command]` | No | Ordered list of commands executed during the run. |
| `packages` | `object` | No | Map of package manager name to list of packages. Keys are manager names (e.g. `"pip"`, `"npm"`, `"rpm"`). |
| `containers` | `array[Container]` | No | List of container images used or built during the run. |

### Command object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `step` | `integer` | Yes | Execution order (0-indexed). |
| `command` | `string` | Yes | The command that was run. |
| `exit_code` | `integer` | No | Exit code of the command (0 = success). |
| `duration_ms` | `integer` | No | How long the command took in milliseconds. |

### Package object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Package name (e.g. `requests`, `numpy`). |
| `version` | `string` | Yes | Installed version (e.g. `2.31.0`). |

### Container object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image_ref` | `string` | Yes | Full image reference (e.g. `quay.io/rhai/runner:v1.2`). |
| `image_digest` | `string` | No | Image digest (e.g. `sha256:abc123...`). |
| `platform` | `string` | No | Target platform (e.g. `linux/amd64`). |

---

## Example manifest

```json
{
  "version": "1",
  "pipeline_slug": "autofix-triage",
  "commands": [
    {
      "step": 0,
      "command": "pip install -r requirements.txt",
      "exit_code": 0,
      "duration_ms": 12340
    },
    {
      "step": 1,
      "command": "python -m autofix.triage --project RHOAIENG",
      "exit_code": 0,
      "duration_ms": 184200
    }
  ],
  "packages": {
    "pip": [
      { "name": "anthropic", "version": "0.52.0" },
      { "name": "httpx", "version": "0.28.1" },
      { "name": "pydantic", "version": "2.11.0" },
      { "name": "jira", "version": "3.8.0" }
    ],
    "npm": [
      { "name": "typescript", "version": "5.5.0" }
    ]
  },
  "containers": [
    {
      "image_ref": "quay.io/rhai/claude-runner:2026.05",
      "image_digest": "sha256:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "platform": "linux/amd64"
    },
    {
      "image_ref": "registry.access.redhat.com/ubi9/python-311:latest"
    }
  ]
}
```

---

## Integration guide for GitLab CI

Add the following to your `.gitlab-ci.yml` job script to generate and upload the manifest as a build artifact:

```yaml
my-pipeline-job:
  image: quay.io/rhai/claude-runner:2026.05
  script:
    - pip install -r requirements.txt
    - python -m my_pipeline.main

    # Generate run-manifest.json
    - pip freeze > /tmp/pip-packages.txt
    - python -c "
      import json
      packages = [{'name': p.split('==')[0], 'version': p.split('==')[1]}
                   for p in open('/tmp/pip-packages.txt').read().strip().split('\n') if '==' in p]
      manifest = {
          'version': '1',
          'pipeline_slug': '$CI_PROJECT_NAME',
          'packages': {'pip': packages},
          'containers': [{'image_ref': '$CI_JOB_IMAGE'}]
      }
      json.dump(manifest, open('run-manifest.json', 'w'), indent=2)
      "
  artifacts:
    paths:
      - run-manifest.json
    expire_in: 30 days
```

Key points:
- The file must be named `run-manifest.json` (this is what the collector looks for in artifacts).
- `$CI_PROJECT_NAME` maps to the pipeline slug in Observatory. Make sure they match.
- `$CI_JOB_IMAGE` captures the container image used by the job.
- List the file under `artifacts.paths` so Observatory's collector can download it.

---

## Integration guide for GitHub Actions

Add a step to your workflow that generates the manifest and uploads it as a workflow artifact:

```yaml
jobs:
  my-pipeline:
    runs-on: ubuntu-latest
    container:
      image: quay.io/rhai/claude-runner:2026.05
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run pipeline
        run: python -m my_pipeline.main

      - name: Generate run manifest
        run: |
          pip freeze > /tmp/pip-packages.txt
          python3 -c "
          import json, os
          packages = [{'name': p.split('==')[0], 'version': p.split('==')[1]}
                       for p in open('/tmp/pip-packages.txt').read().strip().split('\n') if '==' in p]
          manifest = {
              'version': '1',
              'pipeline_slug': os.environ.get('GITHUB_REPOSITORY', '').split('/')[-1],
              'packages': {'pip': packages},
              'containers': [{'image_ref': os.environ.get('GITHUB_ACTION_IMAGE', 'unknown')}]
          }
          json.dump(manifest, open('run-manifest.json', 'w'), indent=2)
          "

      - name: Upload run manifest
        uses: actions/upload-artifact@v4
        with:
          name: run-manifest
          path: run-manifest.json
          retention-days: 30
```

Key points:
- Use `actions/upload-artifact` to make the file downloadable by the collector.
- `GITHUB_REPOSITORY` is `owner/repo`; the script splits on `/` to get the repo name as the pipeline slug.
- If your container image is set in the `container.image` field, capture it explicitly since GitHub Actions does not expose it as an environment variable.

---

## How Observatory processes the manifest

1. **Collector scrapes runs** -- the background collector (`backend/collector/scheduler.py`) polls GitLab/GitHub APIs on the configured interval for new pipeline runs.

2. **Artifact download** -- for each run where `artifacts_scraped = FALSE`, the collector downloads build artifacts and looks for a file named `run-manifest.json`.

3. **Manifest parsing** -- `backend/collector/parsers/manifest.py` parses the JSON and inserts rows into three tables:
   - `run_commands` -- one row per command entry
   - `run_packages` -- one row per package, keyed by manager
   - `run_containers` -- one row per container image

4. **Idempotent** -- if the manifest is re-scraped (e.g. after a collector restart), existing provenance rows for that run are deleted and re-inserted.

5. **Fallback** -- if no `run-manifest.json` is found but the CI API provides a job image (e.g. GitLab's `image` field), a single `run_containers` row is inserted with `source = 'api'`.

6. **Provenance API** -- the data is queryable via:
   - `GET /api/pipelines/{slug}/runs/{run_id}/provenance` -- all provenance for a run
   - `GET /api/pipelines/{slug}/runs/{run_id}/commands` -- commands only
   - `GET /api/pipelines/{slug}/runs/{run_id}/packages?manager=pip` -- packages, optionally filtered by manager
   - `GET /api/pipelines/{slug}/runs/{run_id}/containers` -- containers only
   - `GET /api/provenance/packages` -- cross-pipeline package inventory
   - `GET /api/provenance/containers` -- cross-pipeline container inventory

7. **SBOM generation** -- if a container has an `image_digest`, the SBOM generator job (`backend/jobs/sbom_generator.py`) can run `syft` against the image to produce an SPDX SBOM, which is then scanned for vulnerabilities by `grype`.

---

## Validation

Use the formal JSON Schema at `schemas/run-manifest.v1.schema.json` to validate manifests before uploading:

```bash
# Using python-jsonschema
pip install jsonschema
python -c "
import json, jsonschema
schema = json.load(open('schemas/run-manifest.v1.schema.json'))
manifest = json.load(open('run-manifest.json'))
jsonschema.validate(manifest, schema)
print('Valid')
"
```

Or in CI:

```bash
pip install check-jsonschema
check-jsonschema --schemafile schemas/run-manifest.v1.schema.json run-manifest.json
```
