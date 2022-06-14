#!/bin/python3

import typing

from ops.model import ActiveStatus

try:
    from jinx import *
except ModuleNotFoundError:
    from charms.jinx import *


class MyCharm(Jinx):
    name = 'my-charm'
    summary = 'jinx template charm'
    description = 'nothing special'
    maintainer = 'your.name@foo.bar'

    workload = container(name='workload-container', resource='workload')
    workload_resource = resource(name='workload', type='oci-image')
    disk = storage('filesystem', '/data/db', 'disk')
    log_me = action(name='log-me')

    db = provide('database-relation', 'db-interface')
    peers = peer('db-peers', 'db-replicas')

    def __init__(self, framework: Framework, key: typing.Optional = None):
        super().__init__(framework, key)
        self.on_start(self._log_event)
        self.on_install(self._log_event)
        self.on_start(self._log_event)
        self.on_stop(self._log_event)
        self.on_remove(self._log_event)
        self.on_update_status(self._log_event)
        self.on_config_changed(self._log_event)
        self.on_upgrade_charm(self._log_event)
        self.on_pre_series_upgrade(self._log_event)
        self.on_post_series_upgrade(self._log_event)
        self.on_leader_elected(self._log_event)
        self.on_leader_settings_changed(self._log_event)
        self.on_collect_metrics(self._log_event)

        self.workload.on_pebble_ready(self._log_event)

        self.disk.on_attached(self._log_event)
        self.disk.on_detached(self._log_event)

        self.db.on_created(self._log_event)
        self.db.on_changed(self._log_event)
        self.db.on_departed(self._log_event)
        self.db.on_broken(self._log_event)
        self.db.on_joined(self._log_event)

        self.peers.on_created(self._log_event)
        self.peers.on_changed(self._log_event)
        self.peers.on_departed(self._log_event)
        self.peers.on_broken(self._log_event)
        self.peers.on_joined(self._log_event)

    @log_me.handler
    def _log_event(self, event):
        evt_name = event.handle.path
        print(evt_name)
        self.unit.status = ActiveStatus(evt_name)

