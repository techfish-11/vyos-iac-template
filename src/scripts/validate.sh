#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
export ANSIBLE_CONFIG="$PWD/src/ansible.cfg"
export ANSIBLE_HOME="$PWD/src/.ansible"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python -m pytest -c src/pyproject.toml -q
ruff check --config src/pyproject.toml src
for playbook in src/playbooks/*.yml; do
    ansible-playbook -i src/tests/fixtures/inventory.yml "$playbook" --syntax-check
done
(
    cd src
    ansible-lint --offline -c .ansible-lint --project-dir .
)
ansible-playbook -i src/tests/fixtures/inventory.yml src/playbooks/render.yml
python -m vyos_iac check --inventory src/tests/fixtures/inventory.yml --json
