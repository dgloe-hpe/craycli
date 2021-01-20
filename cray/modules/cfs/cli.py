"""
cfs - Configuration Framework Service

This module generates the CLI from the OpenAPI specification, but customizes the
target section of the spec so that multiple groups with individual names and
member lists can be specified on the command line for the create subcommand.

This is accomplished by removing the autogenerated target-groups-members and
target-groups-name options and replacing them with a single target-group
option. A custom callback is provided to gather data from this new option into
a payload for passing on to the API.

MIT License

(C) Copyright [2020] Hewlett Packard Enterprise Development LP

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
"""
# pylint: disable=invalid-name
# pylint: disable=too-many-arguments
import json

import click

from cray.core import option
from cray.generator import generate, _opt_callback
from cray.constants import FROM_FILE_TAG

CURRENT_VERSION = 'v2'
SWAGGER_OPTS = {
    'vocabulary': {
        'deleteall': 'deleteall'
    }
}

cli = generate(__file__, condense=False, swagger_opts=SWAGGER_OPTS)
cli.commands = cli.commands[CURRENT_VERSION].commands


# CONFIGURATIONS #

def create_configurations_shim(update_callback, patch_callback):
    """ Callback function to custom create our own payload """
    def _decorator(configuration_id, file, update_branches, **kwargs):
        file_name = file['value']
        if file_name:  # pylint: disable=no-else-return
            with open(file['value'], 'r') as f:
                data = json.loads(f.read())
            payload = data
            # Hack to tell the CLI we are passing our own payload; don't generate
            kwargs[FROM_FILE_TAG] = {"value": payload, "name": FROM_FILE_TAG}
            return update_callback(configuration_id=configuration_id, **kwargs)
        elif update_branches['value']:
            return patch_callback(configuration_id=configuration_id, **kwargs)
        else:
            raise Exception('Either --file or --update-branches must be set for updates')
    return _decorator


def setup_configuration_from_file(cfs_cli):
    """ Adds a --file parameter for configuration creation """
    tmp_swagger_opts = {
        'vocabulary': {
            'patch': 'patch'
        }
    }
    tmp_cli = generate(__file__, condense=False, swagger_opts=tmp_swagger_opts)
    tmp_cli.commands = tmp_cli.commands[CURRENT_VERSION].commands

    update_command = tmp_cli.commands['configurations'].commands['update']
    patch_command = tmp_cli.commands['configurations'].commands['patch']

    option('--file', callback=_opt_callback, type=str, metavar='TEXT',
           help="A file containing the json for a configuration"
                " (Required unless updating branches)")(update_command)
    option('--update-branches', callback=_opt_callback, is_flag=True,
           help="Updates the commit ids for all config layers with branches")(update_command)
    new_params = update_command.params[-2:]
    for param in update_command.params[:-2]:
        if not param.name.startswith('layers_'):
            new_params.append(param)
    update_command.params = new_params
    update_command.callback = create_configurations_shim(update_command.callback,
                                                         patch_command.callback)

    cfs_cli.commands['configurations'].commands['update'] = update_command


setup_configuration_from_file(cli)


# SESSIONS #

GROUP_MEMBERS_PAYLOAD = 'target-groups-members'
GROUP_NAME_PAYLOAD = 'target-groups-name'
GROUPS_PAYLOAD = 'target-group'
CREATE_CMD = cli.commands['sessions'].commands['create']

# Update session should only be in the api as it is not user friendly and
# is only used by CFS to update session status.
del cli.commands['sessions'].commands['update']


def _targets_callback(cb):
    """
    Coerce the targets/group members from a comma-separated list to a list of
    mappings. Callback function for the target-groups option.
    """
    def _cb(ctx, param, value):
        groups = []
        for group, members in value:
            members = [m.strip() for m in members.split(',')]
            groups.append({"name": group, "members": members})
        if cb:
            return cb(ctx, param, groups)
        return groups
    return _cb


# Create a new option which can handle multiple groups with individual names
# and member lists. `option` acts as a decorator here.
option('--'+GROUPS_PAYLOAD, nargs=2, type=click.Tuple([str, str]), multiple=True,
       payload_name=GROUPS_PAYLOAD, callback=_targets_callback(_opt_callback),
       metavar='GROUPNAME MEMBER1[, MEMBER2, MEMBER3, ...]',
       help="Group members for the inventory. When the inventory definition is "
            "'image', only one group with a single IMS image id should be "
            "specified. Multiple groups can be specified.")(CREATE_CMD)

# Remove the generated params for the group names and group member lists.
# Add the new target-groups option.
params = []
for p in CREATE_CMD.params:
    if p.payload_name in (GROUP_MEMBERS_PAYLOAD, GROUP_NAME_PAYLOAD):
        continue
    # Hack to force order in list in front of globals
    # only for making the UX better
    if p.payload_name == GROUPS_PAYLOAD:
        params.insert(1, p)
    else:
        params.append(p)

# Update the command with the new params
CREATE_CMD.params = params


def create_sessions_shim(func):
    """ Callback function to custom create our own payload """
    def _decorator(target_definition, target_group, **kwargs):
        payload = {v['name']: v['value'] for _, v in kwargs.items() if v['value'] is not None}
        payload['target'] = {
            'definition': target_definition["value"],
            'groups': target_group['value']
        }

        # Hack to tell the CLI we are passing our own payload; don't generate
        kwargs[FROM_FILE_TAG] = {'value': payload, 'name': FROM_FILE_TAG}
        return func(**kwargs)
    return _decorator


# Update the create command with the callback
CREATE_CMD.callback = create_sessions_shim(CREATE_CMD.callback)


# COMPONENTS #

def create_components_shim(func):
    """ Callback function to custom create our own payload """
    def _decorator(component_id, state, **kwargs):
        payload = {v['name']: v['value'] for _, v in kwargs.items() if v['value'] is not None}
        if state['value']:
            payload['state'] = json.loads(state['value'])

        # Hack to tell the CLI we are passing our own payload; don't generate
        kwargs[FROM_FILE_TAG] = {'value': payload, 'name': FROM_FILE_TAG}
        return func(component_id=component_id, **kwargs)
    return _decorator


def setup_component_state(cfs_cli):
    """ Adds a --state parameter for component updates """
    command = cfs_cli.commands['components'].commands['update']
    option('--state', callback=_opt_callback, required=False, type=str, metavar='TEXT',
           help="The component state. Set to [] to clear.")(command)
    new_params = [command.params[-1]]
    for param in command.params[:-1]:
        if not param.name.startswith('state_'):
            new_params.append(param)
    command.params = new_params
    command.callback = create_components_shim(command.callback)


setup_component_state(cli)
