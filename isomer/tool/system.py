#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# Isomer - The distributed application framework
# ==============================================
# Copyright (C) 2011-2020 Heiko 'riot' Weinen <riot@c-base.org> and others.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

Module: system
==============

Contains system setup tasks.

    system all
    system dependencies
    system user
    system paths

"""

import os
import time
import click
import shutil
import pwd

from click_didyoumean import DYMGroup
from tomlkit import loads, dumps
from tomlkit.exceptions import NonExistentKey
from tomlkit import document, table, nl, comment

from isomer.logger import error, warn, verbose
from isomer.misc.path import locations, get_path, get_log_path, get_etc_path, \
    get_prefix_path
from isomer.tool import platforms, install_isomer, log, run_process, ask, finish, \
    questionnaire
from isomer.tool.etc import create_configuration, write_configuration, upgrade_table,\
    load_instances
from isomer.tool.instance import create, set_parameter
from isomer.error import abort, EXIT_NOT_OVERWRITING_CONFIGURATION


@click.group(
    cls=DYMGroup,
    short_help="System and platform management tasks"
)
@click.pass_context
@click.option(
    "--platform",
    "-p",
    default=None,
    help="Platform name, one of %s" % list(platforms.keys()),
)
@click.option("--omit-platform", is_flag=True, default=False)
@click.option("--use-sudo", "-u", is_flag=True, default=False)
@click.option(
    "--log-actions",
    "-l",
    help="Show what would be installed",
    is_flag=True,
    default=False,
)
def system(ctx, platform, omit_platform, use_sudo, log_actions):
    """[GROUP] Various aspects of Isomer system handling"""

    ctx.obj["platform"] = platform
    ctx.obj["omit_platform"] = omit_platform

    ctx.obj["use_sudo"] = use_sudo
    ctx.obj["log_actions"] = log_actions


@system.command(name="all", short_help="Perform all system setup tasks")
@click.pass_context
def system_all(ctx):
    """Performs all system setup tasks"""

    use_sudo = ctx.obj["use_sudo"]

    log("Generating configuration")
    if os.path.exists(get_etc_path()):
        abort(EXIT_NOT_OVERWRITING_CONFIGURATION)
    ctx = create_configuration(ctx)

    log("Installing Isomer system wide")
    install_isomer(
        ctx.obj["platform"], use_sudo, show=ctx.obj["log_actions"],
        omit_platform=ctx.obj['omit_platform'], omit_common=True
    )

    log("Adding Isomer system user")
    _add_system_user(use_sudo)

    log("Creating Isomer filesystem locations")
    _create_system_folders(use_sudo)

    finish(ctx)


@system.command(short_help="Generate a skeleton configuration for Isomer (needs sudo)")
@click.pass_context
def configure(ctx):
    """Generate a skeleton configuration for Isomer (needs sudo)"""

    if os.path.exists(os.path.join(get_etc_path(), "isomer.conf")):
        abort(EXIT_NOT_OVERWRITING_CONFIGURATION)
    ctx = create_configuration(ctx)
    write_configuration(ctx.obj['config'])

    finish(ctx)


@system.command(short_help="Install system dependencies")
@click.pass_context
def dependencies(ctx):
    """Install Isomer platform dependencies"""

    log("Installing platform dependencies")

    install_isomer(
        ctx.obj["platform"],
        ctx.obj["use_sudo"],
        show=ctx.obj["log_actions"],
        omit_platform=ctx.obj['platform'],
        omit_common=True,
    )

    finish(ctx)


@system.command(name="user", short_help="create system user")
@click.pass_context
def system_user(ctx):
    """instance Isomer system user (isomer.isomer)"""

    _add_system_user(ctx.obj["use_sudo"])
    finish(ctx)


def _add_system_user(use_sudo=False):
    """instance Isomer system user (isomer.isomer)"""

    command = [
        "/usr/sbin/adduser",
        "--system",
        "--quiet",
        "--home",
        "/var/run/isomer",
        "--group",
        "--disabled-password",
        "--disabled-login",
        "isomer",
    ]

    success, output = run_process("/", command, sudo=use_sudo)
    if success is False:
        log("Error adding system user:", lvl=error)
        log(output, lvl=error)

    command = ["/usr/sbin/adduser", "isomer", "dialout"]

    success, output = run_process("/", command, sudo=use_sudo)
    if success is False:
        log("Error adding system user to dialout group:", lvl=error)
        log(output, lvl=error)

    time.sleep(2)


@system.command(name="paths", short_help="create system paths")
@click.pass_context
def system_paths(ctx):
    """instance Isomer system paths (/var/[local,lib,cache]/isomer)"""

    _create_system_folders(ctx.obj["use_sudo"])
    finish(ctx)


def _create_system_folders(use_sudo=False):
    target_paths = [
        "/var/www/challenges",  # For LetsEncrypt acme certificate challenges
        "/var/backups/isomer",
        "/var/log/isomer",
        "/var/run/isomer",
    ]
    for item in locations:
        target_paths.append(get_path(item, ""))

    target_paths.append(get_log_path())

    for item in target_paths:
        run_process("/", ["sudo", "mkdir", "-p", item], sudo=use_sudo)
        run_process("/", ["sudo", "chown", "isomer", item], sudo=use_sudo)

    # TODO: The group/ownership should be assigned per instance.user/group
    run_process("/", ["sudo", "chgrp", "isomer", "/var/log/isomer"], sudo=use_sudo)
    run_process("/", ["sudo", "chmod", "g+w", "/var/log/isomer"], sudo=use_sudo)


@system.command(short_help="Remove all instance data")
def uninstall():
    """Uninstall data and resource locations"""

    response = ask(
        "This will delete all data of your Isomer installations! Type"
        "YES to continue:",
        default="N",
        show_hint=False,
    )
    if response == "YES":
        shutil.rmtree("/var/lib/isomer")
        shutil.rmtree("/var/cache/isomer")


@system.command(short_help="Checks overall system health")
@click.option("--acknowledge", "-a", is_flag=True, default=False,
              help="Acknowledge (log) positive checks")
@click.pass_context
def check(ctx, acknowledge):
    """Performs some basic system configuration tests to estimate platform health

    The checks range from file and folder location existance to checking if there
    is a system isomer user"""

    etc_path = get_etc_path()
    prefix_path = get_prefix_path()

    log("Checking etc in '%s' and prefix in '%s'" % (etc_path, prefix_path))

    def check_exists(path):
        if not os.path.exists(path):
            log("Location '%s' does not exist" % path, lvl=warn)
        elif acknowledge:
            log("Location '%s' exists" % path)

    locations_etc = [
        '',
        'isomer.conf',
        'instances'
    ]

    locations_prefix = [
        'var/lib/isomer',
        'var/local/isomer',
        'var/cache/isomer',
        'var/log/isomer',
        'var/run/isomer',
        'var/backups/isomer',
        'var/www/challenges'
    ]

    for location in locations_etc:
        check_exists(os.path.join(etc_path, location))
    for location in locations_prefix:
        check_exists(os.path.join(prefix_path, location))

    try:
        pwd.getpwnam("isomer")
        log("Isomer user exists")
    except KeyError:
        log("Isomer user does not exist", lvl=warn)



@system.command(help="(WiP!) Upgrade older configuration files to the current version")
@click.argument("filename")
@click.pass_context
def upgrade(ctx, filename):
    """Work in progress, currently only lists the necessary transformations."""

    log("You'll have to implement these manually, until this function is developed "
        "completely!", lvl=warn)

    with open(filename, 'r') as f:
        old_configuration = loads(f.read())

    old_version = old_configuration.get('version', 0)

    log(old_configuration["web"]["address"])

    backup_filename = filename + ".%s.backup" % old_version
    log("Backing up old configuration to", backup_filename)

    try:
        shutil.copyfile(filename, backup_filename)
    except PermissionError as e:
        log("Could not backup configuration!", lvl=warn)

    log(old_configuration, pretty=True, lvl=verbose)
    log(old_version, max(upgrade_table), lvl=verbose)

    for upgrade in range(old_version, max(upgrade_table)):
        log("Processing meta upgrade to", upgrade)

        for operation in upgrade_table[old_version + 1]:
            log(operation, pretty=True)
            for rule, transformations in operation.items():
                if rule == 'add':
                    for item, default_value in transformations.items():
                        if item not in old_configuration:
                            old_configuration.add(item, default_value)
                        else:
                            log("Item %s is already present" % item)
                if rule == 'tableize':
                    for item, table_values in transformations.items():
                        log('Tableizing attributes under', item)
                        new_table = table()

                        for table_value in table_values:
                            current_value = old_configuration[table_value]
                            log("Tableizing", table_value, "and its value", current_value)
                            del old_configuration[table_value]
                            new_table.add(table_value, current_value)

                        log(new_table, pretty=True)
                        old_configuration.add(item, new_table)

    new_configuration = dumps(old_configuration)

    for upgrade in range(old_version, max(upgrade_table)):
        log("Processing textual upgrade to", upgrade)

        for operation in upgrade_table[old_version + 1]:
            for rule, transformations in operation.items():
                if rule == 'rename':
                    for rename_value in transformations:
                        log("Renaming", rename_value[0], rename_value[1])
                        new_configuration = new_configuration.replace(rename_value[0], rename_value[1])

    log(new_configuration, pretty=True)
