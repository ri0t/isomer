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

Module: Objects
===============

Object management functionality and utilities.

"""

from ast import literal_eval
from pprint import pprint

import bson
import deepdiff
import click
from click_didyoumean import DYMGroup

from isomer.logger import error, debug, warn, verbose
from isomer.tool import log, ask, finish
from isomer.tool.database import db


@db.group(
    cls=DYMGroup,
    short_help="Object operations"
)
@click.pass_context
def objects(ctx):
    """[GROUP] Object operations"""
    pass


@objects.command(short_help="modify field values of objects")
@click.option("--schema")
@click.option("--uuid")
@click.option("--filter", "--object-filter")
@click.argument("field")
@click.argument("value")
@click.pass_context
def modify(ctx, schema, uuid, object_filter, field, value):
    """Modify field values of objects"""
    database = ctx.obj["db"]

    model = database.objectmodels[schema]
    obj = None

    if uuid:
        obj = model.find_one({"uuid": uuid})
    elif object_filter:
        obj = model.find_one(literal_eval(object_filter))
    else:
        log("No object uuid or filter specified.", lvl=error)

    if obj is None:
        log("No object found", lvl=error)
        return

    log("Object found, modifying", lvl=debug)
    try:
        new_value = literal_eval(value)
    except ValueError:
        log("Interpreting value as string")
        new_value = str(value)

    obj._fields[field] = new_value
    obj.validate()
    log("Changed object validated", lvl=debug)
    obj.save()
    finish(ctx)


@objects.command(short_help="view objects")
@click.option("--schema", default=None)
@click.option("--uuid", default=None)
@click.option("--object-filter", "--filter", default=None)
@click.pass_context
def view(ctx, schema, uuid, object_filter):
    """Show stored objects"""

    database = ctx.obj["db"]

    if schema is None:
        log("No schema given. Read the help", lvl=warn)
        return

    model = database.objectmodels[schema]

    if uuid:
        obj = model.find({"uuid": uuid})
    elif object_filter:
        obj = model.find(literal_eval(object_filter))
    else:
        obj = model.find()

    if obj is None or model.count() == 0:
        log("No objects found.", lvl=warn)

    for item in obj:
        pprint(item._fields)

    finish(ctx)


@objects.command(short_help="view objects")
@click.option("--schema", default=None)
@click.option("--uuid", default=None)
@click.option("--object-filter", "--filter", default=None)
@click.option(
    "--yes", "-y", help="Assume yes to a safety question", default=False, is_flag=True
)
@click.pass_context
def delete(ctx, schema, uuid, object_filter, yes):
    """Delete stored objects (CAUTION!)"""

    database = ctx.obj["db"]

    if schema is None:
        log("No schema given. Read the help", lvl=warn)
        return

    model = database.objectmodels[schema]

    if uuid:
        count = model.count({"uuid": uuid})
        obj = model.find({"uuid": uuid}, validation=False)
    elif object_filter:
        count = model.count(literal_eval(object_filter))
        obj = model.find(literal_eval(object_filter), validation=False)
    else:
        count = model.count()
        obj = model.find(validation=False)

    if count == 0:
        log("No objects to delete found")
        return

    if not yes and not ask(
        "Are you sure you want to delete %i objects" % count,
        default=False,
        data_type="bool",
        show_hint=True,
    ):
        return

    for item in obj:
        item.delete()

    finish(ctx)


@objects.command(short_help="drop a whole collection of objects")
@click.option("--schema", default=None)
@click.option(
    "--yes", "-y", help="Assume yes to a safety question", default=False, is_flag=True
)
@click.pass_context
def drop(ctx, schema, yes):
    """Delete a whole collection of stored objects (CAUTION!)"""

    database = ctx.obj["db"]

    if schema is None:
        log("No schema given. Read the help", lvl=warn)
        return

    if not yes and not ask(
        "Are you sure you want to drop the whole collection",
        default=False,
        data_type="bool",
        show_hint=True,
    ):
        return

    model = database.objectmodels[schema]
    collection = model.collection()
    collection.drop()

    finish(ctx)


@objects.command(short_help="Validates stored objects")
@click.option("--schema", "-s", default=None, help="Specify object schema to validate")
@click.option(
    "--all-schemata",
    "--all",
    help="Agree to validate all objects, if no schema given",
    is_flag=True,
)
@click.pass_context
def validate(ctx, schema, all_schemata):
    """Validates all objects or all objects of a given schema."""

    database = ctx.obj["db"]

    if schema is None:
        if all_schemata is False:
            log("No schema given. Read the help", lvl=warn)
            return
        else:
            schemata = database.objectmodels.keys()
    else:
        schemata = [schema]

    for schema in schemata:
        try:
            things = database.objectmodels[schema]
            with click.progressbar(
                things.find(), length=things.count(), label="Validating %15s" % schema
            ) as object_bar:
                for obj in object_bar:
                    obj.validate()
        except Exception as e:

            log(
                "Exception while validating:",
                schema,
                e,
                type(e),
                "\n\nFix this object and rerun validation!",
                emitter="MANAGE",
                lvl=error,
            )

    finish(ctx)


@objects.command(short_help="find in object model fields")
@click.option(
    "--search",
    help="Argument to search for in object model fields",
    default=None,
    metavar="<text>",
)
@click.option("--by-type", help="Find all fields by type", default=False, is_flag=True)
@click.option(
    "--obj", default=None, help="Search in specified object model", metavar="<name>"
)
@click.pass_context
def find_field(ctx, search, by_type, obj):
    """Find fields in registered data models."""

    # TODO: Fix this to work recursively on all possible subschemes
    if search is None:
        search = ask("Enter search term")

    database = ctx.obj["db"]

    def find(search_schema, search_field, find_result=None, key=""):
        """Examine a schema to find fields by type or name"""

        if find_result is None:
            find_result = []
        fields = search_schema["properties"]
        if not by_type:
            if search_field in fields:
                find_result.append(key)
                # log("Found queried fieldname in ", model)
        else:
            for field in fields:
                try:
                    if "type" in fields[field]:
                        # log(fields[field], field)
                        if fields[field]["type"] == search_field:
                            find_result.append((key, field))
                            # log("Found field", field, "in", model)
                except KeyError as e:
                    log("Field access error:", e, type(e), exc=True, lvl=debug)

        if "properties" in fields:
            # log('Sub properties checking:', fields['properties'])
            find_result.append(
                find(
                    fields["properties"], search_field, find_result, key=fields["name"]
                )
            )

        for field in fields:
            if "items" in fields[field]:
                if "properties" in fields[field]["items"]:
                    # log('Sub items checking:', fields[field])
                    find_result.append(
                        find(
                            fields[field]["items"], search_field, find_result, key=field
                        )
                    )
                else:
                    pass
                    # log('Items without proper definition!')

        return find_result

    if obj is not None:
        schema = database.objectmodels[obj]._schema
        result = find(schema, search, [], key="top")
        if result:
            # log(args.object, result)
            print(obj)
            pprint(result)
    else:
        for model, thing in database.objectmodels.items():
            schema = thing._schema

            result = find(schema, search, [], key="top")
            if result:
                print(model)
                # log(model, result)
                print(result)

    finish(ctx)


@objects.command(short_help="Find illegal _id fields")
@click.option(
    "--delete-duplicates",
    "--delete",
    default=False,
    is_flag=True,
    help="Delete found duplicates",
)
@click.option(
    "--fix", default=False, is_flag=True, help="Tries to fix faulty object ids"
)
@click.option(
    "--test",
    default=False,
    is_flag=True,
    help="Test if faulty objects have clones with correct ids",
)
@click.option("--schema", default=None, help="Work on specified schema only")
@click.pass_context
def illegalcheck(ctx, schema, delete_duplicates, fix, test):
    """Tool to find erroneous objects created with old legacy bugs. Should be
    obsolete!"""

    database = ctx.obj["db"]

    if delete_duplicates and fix:
        log("Delete and fix operations are exclusive.")
        return

    if schema is None:
        schemata = database.objectmodels.keys()
    else:
        schemata = [schema]

    for thing in schemata:
        log("Schema:", thing)
        for item in database.objectmodels[thing].find():
            if not isinstance(item._fields["_id"], bson.objectid.ObjectId):
                if not delete_duplicates:
                    log(item.uuid)
                    log(item._fields, pretty=True, lvl=verbose)
                if test:
                    if database.objectmodels[thing].count({"uuid": item.uuid}) == 1:
                        log("Only a faulty object exists.")
                if delete_duplicates:
                    item.delete()
                if fix:
                    _id = item._fields["_id"]
                    item._fields["_id"] = bson.objectid.ObjectId(_id)
                    if not isinstance(item._fields["_id"], bson.objectid.ObjectId):
                        log("Object mongo ID field not valid!", lvl=warn)
                    item.save()
                    database.objectmodels[thing].find_one({"_id": _id}).delete()
    finish(ctx)


@objects.command(short_help="Find duplicates by UUID")
@click.option(
    "--delete-duplicates",
    "--delete",
    default=False,
    is_flag=True,
    help="Delete found duplicates",
)
@click.option(
    "--do-merge", "--merge", default=False, is_flag=True, help="Merge found duplicates"
)
@click.option("--schema", default=None, help="Work on specified schema only")
@click.pass_context
def dupcheck(ctx, delete_duplicates, do_merge, schema):
    """Tool to check for duplicate objects. Which should never happen."""

    def handle_schema(check_schema):
        dupes = {}
        dupe_count = 0
        count = 0

        for item in database.objectmodels[check_schema].find():
            if item.uuid in dupes:
                dupes[item.uuid].append(item)
                dupe_count += 1
            else:
                dupes[item.uuid] = [item]
            count += 1

        if len(dupes) > 0:
            log(
                dupe_count,
                "duplicates of",
                count,
                "items total of type",
                check_schema,
                "found:",
            )
            log(dupes.keys(), pretty=True, lvl=verbose)

        if delete_duplicates:
            log("Deleting duplicates")
            for item in dupes:
                database.objectmodels[check_schema].find_one({"uuid": item}).delete()

            log("Done for schema", check_schema)
        elif do_merge:

            def merge(a, b, path=None):
                """merges b into a"""

                if path is None:
                    path = []
                for key in b:
                    if key in a:
                        if isinstance(a[key], dict) and isinstance(b[key], dict):
                            merge(a[key], b[key], path + [str(key)])
                        elif a[key] == b[key]:
                            pass  # same leaf value
                        else:
                            log("Conflict at", path, key, ":", a[key], "<->", b[key])
                            resolve = ""
                            while resolve not in ("a", "b"):
                                resolve = ask("Choose? (a or b)")
                            if resolve == "a":
                                b[key] = a[key]
                            else:
                                a[key] = b[key]
                    else:
                        a[key] = b[key]
                return a

            log(dupes, pretty=True, lvl=verbose)

            for item in dupes:
                if len(dupes[item]) == 1:
                    continue
                ignore = False
                while len(dupes[item]) > 1 or ignore is False:
                    log(len(dupes[item]), "duplicates found:")
                    for index, dupe in enumerate(dupes[item]):
                        log("Candidate #", index, ":")
                        log(dupe._fields, pretty=True)
                    request = ask("(d)iff, (m)erge, (r)emove, (i)gnore, (q)uit?")
                    if request == "q":
                        log("Done")
                        return
                    elif request == "i":
                        ignore = True
                        break
                    elif request == "r":
                        delete_request = -2
                        while delete_request == -2 or -1 > delete_request > len(
                            dupes[item]
                        ):
                            delete_request = ask(
                                "Which one? (0-%i or -1 to cancel)"
                                % (len(dupes[item]) - 1),
                                data_type="int",
                            )
                        if delete_request == -1:
                            continue
                        else:
                            log("Deleting candidate #", delete_request)
                            dupes[item][delete_request].delete()
                            break
                    elif request in ("d", "m"):
                        merge_request_a = -2
                        merge_request_b = -2

                        while merge_request_a == -2 or -1 > merge_request_a > len(
                            dupes[item]
                        ):
                            merge_request_a = ask(
                                "Merge from? (0-%i or -1 to cancel)"
                                % (len(dupes[item]) - 1),
                                data_type="int",
                            )
                        if merge_request_a == -1:
                            continue

                        while merge_request_b == -2 or -1 > merge_request_b > len(
                            dupes[item]
                        ):
                            merge_request_b = ask(
                                "Merge into? (0-%i or -1 to cancel)"
                                % (len(dupes[item]) - 1),
                                data_type="int",
                            )
                        if merge_request_b == -1:
                            continue

                        log(
                            deepdiff.DeepDiff(
                                dupes[item][merge_request_a]._fields,
                                dupes[item][merge_request_b]._fields,
                            ),
                            pretty=True,
                        )

                        if request == "m":
                            log(
                                "Merging candidates",
                                merge_request_a,
                                "and",
                                merge_request_b,
                            )

                            _id = dupes[item][merge_request_b]._fields["_id"]
                            if not isinstance(_id, bson.objectid.ObjectId):
                                _id = bson.objectid.ObjectId(_id)

                            dupes[item][merge_request_a]._fields["_id"] = _id
                            merge(
                                dupes[item][merge_request_b]._fields,
                                dupes[item][merge_request_a]._fields,
                            )

                            log(
                                "Candidate after merge:",
                                dupes[item][merge_request_b]._fields,
                                pretty=True,
                            )

                            store = ""
                            while store not in ("n", "y"):
                                store = ask("Store?")
                            if store == "y":
                                dupes[item][merge_request_b].save()
                                dupes[item][merge_request_a].delete()
                                break

    database = ctx.obj["db"]

    if schema is None:
        schemata = database.objectmodels.keys()
    else:
        schemata = [schema]

    for thing in schemata:
        handle_schema(thing)

    finish(ctx)
