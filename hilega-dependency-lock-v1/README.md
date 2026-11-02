# Scoped candidate dependency lock

On the VM:

    .venv/bin/python hilega-dependency-lock-v1/apply_and_test.py --repo "$PWD" --integration

This reruns the preceding 260 cases, then eight new tests: 268 total. Behavioral tests are not run in the packaging workspace. Targeted mode runs the preceding six review tests plus eight new tests, with its bounded live health checkpoint.

The tool downloads only the python-dotenv 1.2.3 binary wheel from public PyPI using isolated pip, with no dependencies and no installation. It compares every dotenv Python source against the installed distribution snapshot, validates wheel metadata and paths, and saves the wheel, SHA256 lock and requirements-candidate.lock. If public PyPI is unavailable, supply an existing wheel with --wheel /absolute/path/python_dotenv-1.2.3-py3-none-any.whl. It never changes package versions automatically. A mismatch stops the workflow.

Fixed dynamic collector entrypoints and their explicit aliases (rules and analysis) are added to the static import graph, alongside the candidate runtime. Existing reviewed loader/collector hash pins must match. Additional external imports or unknown dynamic loaders block this scoped review. Candidate code and broker clients are parsed, not executed by the review.

Outputs are scoped to the explicit candidate and its fixed collectors. They do not certify the complete API/worker/services environment, arbitrary future loading, full release regression, broker behavior or production authority. dependency_manifest_fully_reconciled remains false for the overall application release. No runtime registration is installed. No services, private contexts, controller state, package installation or live ownership are changed.

Next release work is reviewed runtime assembly plus supervisor approval reconciliation, then broker/authority/policy validation, full regression and closed deployment, followed by approved fresh-seed enrollment and a separately authorized controlled live pilot.
