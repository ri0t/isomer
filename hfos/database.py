#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# HFOS - Hackerfleet Operating System
# ===================================
# Copyright (C) 2011-2018 Heiko 'riot' Weinen <riot@c-base.org> and others.
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


__author__ = "Heiko 'riot' Weinen"
__license__ = "AGPLv3"

"""


Module: Database
================

Contains the underlying object model manager and generates object factories
from Schemata.

Contains
========

Schemastore and Objectstore builder functions.


"""

import sys
import time
import json
from ast import literal_eval
from pprint import pprint

import operator
import pymongo
import warmongo
from circuits import Timer, Event
from os import statvfs, walk
from os.path import join, getsize
from pkg_resources import iter_entry_points, DistributionNotFound
# noinspection PyUnresolvedReferences
from six.moves import \
    input  # noqa - Lazily loaded, may be marked as error, e.g. in IDEs

from hfos.component import ConfigurableComponent, handler
from jsonschema import ValidationError  # NOQA
from hfos.logger import hfoslog, debug, warn, error, critical, verbose

try:  # PY 2/3
    PermissionError
except NameError:
    PermissionError = IOError  # NOQA

schemastore = None
configschemastore = {}
objectmodels = None
collections = None
dbhost = ""
dbport = 0
dbname = ""
instance = ""

# Necessary against import de-optimizations
ValidationError = ValidationError


def clear_all():
    """DANGER!
    *This command is a maintenance tool and clears the complete database.*
    """

    sure = input("Are you sure to drop the complete database content? (Type "
                 "in upppercase YES)")
    if not (sure == 'YES'):
        hfoslog('Not deleting the database.')
        sys.exit(5)

    client = pymongo.MongoClient(host=dbhost, port=dbport)
    db = client[dbname]

    for col in db.collection_names(include_system_collections=False):
        hfoslog("Dropping collection ", col, lvl=warn, emitter='DB')
        db.drop_collection(col)


def _build_schemastore_new():
    available = {}

    for schema_entrypoint in iter_entry_points(group='hfos.schemata',
                                               name=None):
        try:
            hfoslog("Schemata found: ", schema_entrypoint.name, lvl=verbose,
                    emitter='DB')
            schema = schema_entrypoint.load()
            available[schema_entrypoint.name] = schema
        except (ImportError, DistributionNotFound) as e:
            hfoslog("Problematic schema: ", e, type(e),
                    schema_entrypoint.name, exc=True, lvl=warn,
                    emitter='SCHEMATA')

    hfoslog("Found", len(available), "schemata: ", sorted(available.keys()),
            lvl=debug,
            emitter='SCHEMATA')
    # pprint(available)

    return available


def _build_model_factories(store):
    result = {}

    for schemaname in store:

        schema = None

        try:
            schema = store[schemaname]['schema']
        except KeyError:
            hfoslog("No schema found for ", schemaname, lvl=critical,
                    emitter='DB')

        try:
            result[schemaname] = warmongo.model_factory(schema)
        except Exception as e:
            hfoslog("Could not create factory for schema ", e, type(e),
                    schemaname, schema,
                    lvl=critical, emitter='DB')

    return result


def _build_collections(store):
    result = {}

    client = pymongo.MongoClient(host=dbhost, port=dbport)
    db = client[dbname]

    for schemaname in store:

        schema = None

        try:
            schema = store[schemaname]['schema']
        except KeyError:
            hfoslog("No schema found for ", schemaname, lvl=critical,
                    emitter='DB')

        try:
            result[schemaname] = db[schemaname]
        except Exception as e:
            hfoslog("Could not get collection for schema ", schemaname, schema,
                    e, lvl=critical, emitter='DB')

    return result


def initialize(address='127.0.0.1:27017', database_name='hfos', instance_name="default"):
    """Initializes the database connectivity, schemata and finally
    object models"""

    global schemastore
    global objectmodels
    global collections
    global dbhost
    global dbport
    global dbname
    global instance

    dbhost = address.split(':')[0]
    dbport = int(address.split(":")[1]) if ":" in address else 27017
    dbname = database_name

    hfoslog("Using database:", dbname, '@', dbhost, ':', dbport, emitter='DB')

    try:
        client = pymongo.MongoClient(host=dbhost, port=dbport)
        db = client[dbname]
        hfoslog("Database: ", db.command('buildinfo'), lvl=debug, emitter='DB')
    except Exception as e:
        hfoslog("No database available! Check if you have mongodb > 3.0 "
                "installed and running as well as listening on port 27017 "
                "of localhost. (Error: %s) -> EXIT" % e, lvl=critical,
                emitter='DB')
        sys.exit(5)

    warmongo.connect(database_name)

    schemastore = _build_schemastore_new()
    objectmodels = _build_model_factories(schemastore)
    collections = _build_collections(schemastore)
    instance = instance_name


def test_schemata():
    """Validates all registered schemata"""

    objects = {}

    for schemaname in schemastore.keys():
        objects[schemaname] = warmongo.model_factory(
            schemastore[schemaname]['schema'])
        try:
            testobject = objects[schemaname]()
            testobject.validate()
        except Exception as e:
            hfoslog('Blank schema did not validate:', schemaname, e,
                    type(e), lvl=verbose, emitter='DB')

    pprint(objects)


def profile(schemaname='sensordata', profiletype='pjs'):
    """Profiles object model handling with a very simple benchmarking test"""

    hfoslog("Profiling ", schemaname, emitter='DB')

    schema = schemastore[schemaname]['schema']

    hfoslog("Schema: ", schema, lvl=debug, emitter='DB')

    testclass = None

    if profiletype == 'warmongo':
        hfoslog("Running Warmongo benchmark", emitter='DB')
        testclass = warmongo.model_factory(schema)
    elif profiletype == 'pjs':
        hfoslog("Running PJS benchmark", emitter='DB')
        try:
            import python_jsonschema_objects as pjs
        except ImportError:
            hfoslog("PJS benchmark selected but not available. Install "
                    "python_jsonschema_objects (PJS)", emitter="DB")
            return

        hfoslog()
        builder = pjs.ObjectBuilder(schema)
        ns = builder.build_classes()
        pprint(ns)
        testclass = ns[schemaname]
        hfoslog("ns: ", ns, lvl=warn, emitter='DB')

    if testclass is not None:
        hfoslog("Instantiating elements...", emitter='DB')
        for i in range(100):
            testclass()
    else:
        hfoslog("No Profiletype available!", emitter="DB")

    hfoslog("Profiling done", emitter='DB')


# profile(schemaname='sensordata', profiletype='warmongo')

class Maintenance(ConfigurableComponent):
    """Regularly checks a few basic system maintenance tests like used
    storage space of collections and other data"""

    configprops = {
        'locations': {
            'type': 'object',
            'properties': {
                'cache': {
                    'type': 'object',
                    'properties': {
                        'minimum': {
                            'type': 'integer',
                            'description': 'Minimum cache free space to '
                                           'alert on',
                            'title': 'Minimum cache',
                            'default': 500 * 1024 * 1024
                        },
                        'location': {
                            'type': 'string',
                            'description': 'Location of cache data',
                            'title': 'Cache location',
                            'default': join('/var/cache/hfos', instance)
                        }
                    },
                    'default': {}
                },
                'library': {
                    'type': 'object',
                    'properties': {
                        'minimum': {
                            'type': 'integer',
                            'description': 'Minimum library free space to '
                                           'alert on',
                            'title': 'Minimum library space',
                            'default': 50 * 1024 * 1024
                        },
                        'location': {
                            'type': 'string',
                            'description': 'Location of library data',
                            'title': 'Library location',
                            'default': join('/var/lib/hfos', instance)
                        }
                    },
                    'default': {}
                },
                'backup': {
                    'type': 'object',
                    'properties': {
                        'minimum': {
                            'type': 'integer',
                            'description': 'Minimum backup free space to '
                                           'alert on',
                            'title': 'Minimum backup space',
                            'default': 50 * 1024 * 1024
                        },
                        'location': {
                            'type': 'string',
                            'description': 'Location of backup data',
                            'title': 'Backup location',
                            'default': join('/var/local/hfos/', instance, 'backup')
                        }
                    },
                    'default': {}
                }
            },
            'default': {}
        },
        'interval': {
            'type': 'integer',
            'title': 'Check interval',
            'description': 'Interval in seconds to check maintenance '
                           'conditions',
            'default': 43200
        }
    }

    def __init__(self, *args, **kwargs):
        super(Maintenance, self).__init__("MAINTENANCE", *args, **kwargs)
        self.log("Maintenance started")

        client = pymongo.MongoClient(dbhost, dbport)
        self.db = client[dbname]

        self.collection_sizes = {}
        self.collection_total = 0

        self.disk_allocated = {}
        self.disk_free = {}

        self.maintenance_check()
        self.timer = Timer(
            self.config.interval,
            Event.create('maintenance_check'), persist=True
        ).register(self)

    @handler('maintenance_check')
    def maintenance_check(self, *args):
        """Perform a regular maintenance check"""

        self.log('Performing maintenance check')
        self._check_collections()
        self._check_free_space()

    def _check_collections(self):
        """Checks node local collection storage sizes"""

        self.collection_sizes = {}
        self.collection_total = 0
        for col in self.db.collection_names(include_system_collections=False):
            self.collection_sizes[col] = self.db.command('collstats', col).get(
                'storageSize', 0)
            self.collection_total += self.collection_sizes[col]

        sorted_x = sorted(self.collection_sizes.items(),
                          key=operator.itemgetter(1))

        for item in sorted_x:
            self.log("Collection size (%s): %.2f MB" % (
                item[0], item[1] / 1024.0 / 1024),
                     lvl=verbose)

        self.log("Total collection sizes: %.2f MB" % (self.collection_total /
                                                      1024.0 / 1024))

    def _check_free_space(self):
        """Checks used filesystem storage sizes"""

        def get_folder_size(path):
            """Aggregates used size of a specified path, recursively"""

            total_size = 0
            for item in walk(path):
                for file in item[2]:
                    try:
                        total_size = total_size + getsize(join(item[0], file))
                    except (OSError, PermissionError) as e:
                        self.log("error with file:  " + join(item[0], file), e)
            return total_size

        for name, checkpoint in self.config.locations.items():
            try:
                stats = statvfs(checkpoint['location'])
            except (OSError, PermissionError) as e:
                self.log('Location unavailable:', name, e, type(e),
                         lvl=error, exc=True)
                continue
            free_space = stats.f_frsize * stats.f_bavail
            used_space = get_folder_size(
                checkpoint['location']
            ) / 1024.0 / 1024

            self.log('Location %s uses %.2f MB' % (name, used_space))

            if free_space < checkpoint['minimum']:
                self.log('Short of free space on %s: %.2f MB left' % (
                    name, free_space / 1024.0 / 1024 / 1024),
                         lvl=warn)


class BackupManager(ConfigurableComponent):
    """Regularly creates backups of collections"""

    configprops = {
        'location': {
            'type': 'string',
            'description': 'Location of library data',
            'title': 'Library location',
            'default': join('/var/local/hfos', instance, 'backup')
        },
        'interval': {
            'type': 'integer',
            'title': 'Backup interval',
            'description': 'Interval in seconds to create Backup',
            'default': 86400
        }
    }

    def __init__(self, *args, **kwargs):
        super(BackupManager, self).__init__("BACKUP", *args, **kwargs)
        self.log("Backup manager started")

        self.timer = Timer(
            self.config.interval,
            Event.create('backup'), persist=True
        ).register(self)

    @handler('backup')
    def backup(self, *args):
        """Perform a regular backup"""

        self.log('Performing backup')
        self._create_backup()

    def _create_backup(self):
        self.log('Backing up all data')

        filename = time.strftime("%Y-%m-%d_%H%M%S.json")
        filename = join(self.config.location, filename)

        backup(None, None, None, 'json', filename, False, True, [])


def backup(schema, uuid, export_filter, export_format, filename, pretty, export_all, omit):
    """Exports all collections to (JSON-) files."""

    export_format = export_format.upper()

    if pretty:
        indent = 4
    else:
        indent = 0

    f = None

    if filename:
        try:
            f = open(filename, 'w')
        except (IOError, PermissionError) as e:
            hfoslog('Could not open output file for writing:', e, type(e), lvl=error, emitter='BACKUP')
            return

    def output(what, convert=False):
        """Output the backup in a specified format."""

        if convert:
            if export_format == 'JSON':
                data = json.dumps(what, indent=indent)
            else:
                data = ""
        else:
            data = what

        if not filename:
            print(data)
        else:
            f.write(data)

    if schema is None:
        if export_all is False:
            hfoslog('No schema given.', lvl=warn, emitter='BACKUP')
            return
        else:
            schemata = objectmodels.keys()
    else:
        schemata = [schema]

    all_items = {}

    for schema_item in schemata:
        model = objectmodels[schema_item]

        if uuid:
            obj = model.find({'uuid': uuid})
        elif export_filter:
            obj = model.find(literal_eval(export_filter))
        else:
            obj = model.find()

        items = []
        for item in obj:
            fields = item.serializablefields()
            for field in omit:
                try:
                    fields.pop(field)
                except KeyError:
                    pass
            items.append(fields)

        all_items[schema_item] = items

        # if pretty is True:
        #    output('\n// Objectmodel: ' + schema_item + '\n\n')
        # output(schema_item + ' = [\n')

    output(all_items, convert=True)

    if f is not None:
        f.flush()
        f.close()