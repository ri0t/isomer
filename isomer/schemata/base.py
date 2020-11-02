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

Schema: Base
============

Basic Isomer object schema utilities

Contains
--------

uuid_object: For inserting UUID fields
base_object: For generating a basic Isomer object schema


"""

from isomer.misc import all_languages


def coordinate(
        title="Coordinate", description="A coordinate", default=None, display=True
):
    """Generates geo coordinate field"""

    result = {
        "type": "object",
        "title": title,
        "description": description,
        "items": [
            {
                'lat': {
                    'type': 'string',
                    'pattern': "^[-+]?([1-8]?\d(\.\d+)?|90(\.0+)?)$",
                    'title': 'Latitude',
                    'description': 'From 90 Degrees North (+) to South (-)'
                }
            },
            {
                'lon': {
                    'type': 'string',
                    'pattern': '^[-+]?(180(\.0+)?|((1[0-7]\d)|([1-9]?\d))(\.\d+)?)$',
                    'title': 'Longitude',
                    'description': 'From 180 Degrees East (+) to West (-)'
                }
            }
        ]
    }

    if not display:
        result["x-schema-form"] = {"condition": "false"}

    if default is not None:
        result["default"] = default

    return result


def uuid_object(
    title="Reference", description="Select an object", default=None, display=True
):
    """Generates a regular expression controlled UUID field"""

    uuid = {
        "pattern": "^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]"
                   "{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$",
        "type": "string",
        "title": title,
        "description": description,
    }

    if not display:
        uuid["x-schema-form"] = {"condition": "false"}

    if default is not None:
        uuid["default"] = default

    return uuid


def base_object(
    name,
    no_perms=False,
    no_color=False,
    has_owner=True,
    hide_owner=True,
    has_uuid=True,
    roles_write=None,
    roles_read=None,
    roles_list=None,
    roles_create=None,
    all_roles=None,
):
    """Generates a basic object with RBAC properties"""
    base_schema = {"id": "#" + name, "type": "object", "name": name, "properties": {}}

    if not no_perms:
        if all_roles:
            roles_create = ["admin", all_roles]
            roles_write = ["admin", all_roles]
            roles_read = ["admin", all_roles]
            roles_list = ["admin", all_roles]
        else:
            if roles_write is None:
                roles_write = ["admin"]
            if roles_read is None:
                roles_read = ["admin"]
            if roles_list is None:
                roles_list = ["admin"]
            if roles_create is None:
                roles_create = ["admin"]

        if isinstance(roles_create, str):
            roles_create = [roles_create]
        if isinstance(roles_write, str):
            roles_write = [roles_write]
        if isinstance(roles_read, str):
            roles_read = [roles_read]
        if isinstance(roles_list, str):
            roles_list = [roles_list]

        if has_owner:
            roles_write.append("owner")
            roles_read.append("owner")
            roles_list.append("owner")

        base_schema["roles_create"] = roles_create
        base_schema["properties"].update(
            {
                "perms": {
                    "id": "#perms",
                    "type": "object",
                    "name": "perms",
                    "properties": {
                        "write": {
                            "type": "array",
                            "default": roles_write,
                            "items": {"type": "string"},
                        },
                        "read": {
                            "type": "array",
                            "default": roles_read,
                            "items": {"type": "string"},
                        },
                        "list": {
                            "type": "array",
                            "default": roles_list,
                            "items": {"type": "string"},
                        },
                    },
                    "default": {},
                    "x-schema-form": {"condition": "false"},
                },
                "name": {"type": "string", "description": "Name of " + name},
            }
        )

        if has_owner:
            # TODO: Schema should allow specification of non-local owners as
            #  well as special accounts like admin or even system perhaps
            # base_schema['required'] = base_schema.get('required', [])
            # base_schema['required'].append('owner')
            base_schema["properties"].update(
                {"owner": uuid_object(title="Unique Owner ID", display=hide_owner)}
            )
    else:
        base_schema["no_perms"] = True

    if not no_color:
        base_schema["properties"].update(
            {"color": {"type": "string", "format": "colorpicker"}}
        )

    # TODO: Using this causes all sorts of (obvious) problems with the object
    # manager
    if has_uuid:
        base_schema["properties"].update(
            {"uuid": uuid_object(title="Unique " + name + " ID", display=False)}
        )
        base_schema["required"] = ["uuid"]

    return base_schema


def sql_object(*args, **kwargs):
    """Generates a basic SQL object with RBAC properties"""

    base_schema = base_object(*args, **kwargs)

    base_schema["class-properties"] = base_schema["properties"]["perms"]
    del base_schema["properties"]["perms"]

    base_schema["sql"] = True

    return base_schema


def language_field():
    schema = {
        "type": "string",
        "enum": all_languages(),
        "title": "Language",
        "description": "Select a language",
    }

    return schema
