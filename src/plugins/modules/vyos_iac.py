"""Documentation stub for the paired controller-only action plugin."""

DOCUMENTATION = r"""
---
module: vyos_iac
short_description: Render or safely replace the entire VyOS configuration
description:
  - Controller-only action with guarded commit-confirm, SSH checks, and private artifacts.
options:
  mode:
    description: Operation to perform.
    type: str
    required: true
    choices: [render, plan, apply, backup, save]
  device:
    description: Validated device object defined by src/schemas/device.json.
    type: dict
    required: true
  known_hosts:
    description: Controller known_hosts file for SFTP and fresh SSH connections.
    type: path
  key_file:
    description: Controller private key; otherwise use the SSH agent.
    type: path
  minutes:
    description: Confirmation deadline in minutes, from 2 to 30.
    type: int
    default: 10
author:
  - techfish
"""

EXAMPLES = r"""
- name: Render validated configuration
  vyos_iac:
    mode: render
    device: "{{ vyos_device }}"
  no_log: true
"""

RETURN = r"""
phase:
  description: Last transaction phase.
  type: str
  returned: always
state:
  description: Recovery state without secret configuration content.
  type: str
  returned: on execution
artifact_path:
  description: Private controller artifact directory.
  type: str
  returned: on rendering
"""


def main():
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(argument_spec={}, supports_check_mode=True)
    module.fail_json(msg="This module requires its paired controller action plugin")


if __name__ == "__main__":
    main()
