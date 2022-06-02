import functools
import logging
from abc import abstractmethod, ABCMeta
from dataclasses import dataclass, asdict
from typing import Dict, TypeVar, Optional, Callable, Union, List, Generic

try:
    from typing import Literal, overload, TYPE_CHECKING, Type
except (ModuleNotFoundError, ImportError):
    from typing_extensions import Literal, overload, TYPE_CHECKING, Type

import ops
from ops.charm import *
from ops.framework import Framework, EventSource
from ops.model import ConfigData

Arch = Literal['amd64']
logger = logging.getLogger('jinx')


@dataclass
class Base:
    name: str = 'ubuntu'
    channel: str = '20.04'


@dataclass
class Bases:
    run_on: List[Base]
    build_on: List[Base]

    def to_dict(self):
        return {'run-on': [asdict(b) for b in self.run_on],
                'build-on': [asdict(b) for b in self.build_on]}


RelationName = ResourceName = StorageName = ContainerName = ActionName = str


@dataclass
class InterfaceMeta:
    interface: str


@dataclass
class RelationMeta:
    name: str
    interface: InterfaceMeta


@dataclass
class _Param:
    type: Literal['string', 'integer', 'float']
    description: str = ''
    default: Union[str, int, float] = None


# fmt: off
@overload
def Param(type: Literal['string'], description: str = '', default: Optional[str] = None) -> _Param: ...
@overload
def Param(type: Literal['float'], description: str = '', default: Optional[float] = None) -> _Param: ...
@overload
def Param(type: Literal['integer'], description: str = '', default: Optional[int] = None) -> _Param: ...
def Param(type: Literal['string', 'float', 'integer'],
          description: str = '',
          default: Optional[Union[str, float, int]] = None
          ) -> _Param:
    return _Param(type, description, default)
# fmt: on


def string(description: str = '', default: str = None) -> _Param:
    return Param('string', description, default)


def integer(description: str = '', default: int = None) -> _Param:
    return Param('integer', description, default)


def float_(description: str = '', default: float = None) -> _Param:
    return Param('float', description, default)


class config:
    def __init__(self, var: _Param):
        self.var = var
        self._name = None  # set by metaclass

    @property
    def name(self):
        if not self._name:
            raise RuntimeError('config not bound')
        return self._name

    def bind(self, name):
        self._name = name

    def __get__(self, instance, owner: 'Jinx'):
        return instance.config[self.name]


@dataclass
class ActionMeta:
    params: Dict[str, _Param]


@dataclass
class FSStorageSpec:
    type: str
    location: str


StorageSpec = Union[FSStorageSpec]


@dataclass
class ContainerSpec:
    resource: ResourceName


@dataclass
class ResourceSpec:
    type: str = 'oci-image'
    description: str = ''
    upstream_source: str = ''

    def to_dict(self):
        dct = {'type': self.type}
        if self.description:
            dct['description'] = self.description
        if self.upstream_source:
            dct['upstream-source'] = self.upstream_source
        return dct


T = TypeVar("T")


class JinxMeta(ops.framework._Metaclass, ABCMeta):
    @staticmethod
    def _framework_meta_init(k):
        for n, v in vars(k).items():
            if isinstance(v, EventSource):
                v._set_name(k, n)
        return k

    def __new__(mcs: Type['Jinx'], name, bases, dct):
        inst = super().__new__(mcs, name, bases, dct)
        # do what ops.framework._Metaclass does:
        JinxMeta._framework_meta_init(inst)
        return inst


class storage:
    def __init__(self, name: ContainerName, type: str, location: str):
        self.name = name
        self.meta = FSStorageSpec(type, location)

    def __get__(self, obj, _type=None):
        return _storage(self.name, self.meta, obj)


class _storage(storage):
    def __init__(self, name: ContainerName, meta: StorageSpec,
                 obj: CharmBase):
        super().__init__(name, meta)
        self.attached = obj.on[name].storage_attached
        self.detaching = obj.on[name].storage_detached
        self._obj = obj

    def on_attached(self, callback: Callable[[StorageAttachedEvent], None]):
        self._obj.framework.observe(self.attached, callback)

    def on_detached(self, callback: Callable[[StorageDetachingEvent], None]):
        self._obj.framework.observe(self.detaching, callback)


class params:
    def __init__(self, **params: _Param):
        self._params = params


class action:
    def __init__(self, name: ActionName, params: 'params' = None):
        self.name = name
        self.params = params
        self.meta = ActionMeta(params._params if params else {})

    def as_dict(self):
        return {self.name: asdict(self.meta)}

    def handler(self, method: Callable[['Jinx', ActionEvent], None]):
        method.__action__ = self

        @functools.wraps(method)
        def action_wrapper(_obj, _event: ActionEvent):
            # Allow returning data from the action handler as a pattern.
            ret_val = method(_obj, _event)
            if isinstance(ret_val, dict):
                _event.set_results(ret_val)

        return action_wrapper


class resource:
    def __init__(self, name: ContainerName,
                 type: str = 'oci-image',
                 description: str = None,
                 upstream_source: str = None):
        self.name = name
        self.meta = ResourceSpec(type, description, upstream_source)


class container:
    def __init__(self, name: ContainerName, resource: str):
        self.name = name
        self.meta = ContainerSpec(resource)

    def __get__(self, obj, _type=None):
        return _container(self.name, self.meta, obj)


class _container(container):
    def __init__(self, name: ContainerName, meta: ContainerSpec,
                 obj: CharmBase):
        super().__init__(name, meta)
        self.pebble_ready = obj.on[name].pebble_ready
        self._obj = obj

    def on_pebble_ready(self, callback: Callable[[PebbleReadyEvent], None]):
        self._obj.framework.observe(self.pebble_ready, callback)


Role = Literal['require', 'provide', 'peer']


class relation:
    def __init__(self, name: str, interface: str, role: Role):
        self.name = name
        self.meta = InterfaceMeta(interface)
        self.role = role

    def __get__(self, obj, _type=None):
        return _relation(self.name, self.meta, self.role, obj)


class _relation(relation):
    def __init__(self, name: str, meta: InterfaceMeta,
                 role: Role,
                 obj: CharmBase):
        super(_relation, self).__init__(name, meta, role)
        self.created = obj.on[name].relation_created
        self.broken = obj.on[name].relation_broken
        self.joined = obj.on[name].relation_joined
        self.departed = obj.on[name].relation_departed
        self.changed = obj.on[name].relation_changed
        self._obj = obj

    def on_created(self, callback: Callable[[RelationCreatedEvent], None]):
        self._obj.framework.observe(self.created, callback)

    def on_broken(self, callback: Callable[[RelationBrokenEvent], None]):
        self._obj.framework.observe(self.broken, callback)

    def on_joined(self, callback: Callable[[RelationJoinedEvent], None]):
        self._obj.framework.observe(self.joined, callback)

    def on_departed(self, callback: Callable[[RelationDepartedEvent], None]):
        self._obj.framework.observe(self.departed, callback)

    def on_changed(self, callback: Callable[[RelationChangedEvent], None]):
        self._obj.framework.observe(self.changed, callback)


def require(name: str, interface: str) -> _relation:
    return relation(name, interface, 'require')  # type: ignore


def provide(name: str, interface: str) -> _relation:
    return relation(name, interface, 'provide')  # type: ignore


def peer(name: str, interface: str) -> _relation:
    return relation(name, interface, 'peer')  # type: ignore


class ExtendedConfigData(ConfigData):
    on_changed: Callable[[Callable[[ConfigChangedEvent], None]], None]
    changed: EventSource


class Jinx(CharmBase, metaclass=JinxMeta):
    __actions__: List['action'] = []
    __config__: Dict[str, '_Param'] = {}
    __provides__: List['relation'] = []
    __requires__: List['relation'] = []
    __peers__: List['relation'] = []

    # TODO: implement
    __storage__: List['storage'] = None
    __containers__: List['container'] = None
    __resources__: List = None

    if TYPE_CHECKING:
        framework: Framework

    @property
    @abstractmethod
    def name(self):
        ...

    summary: Optional[str] = None
    maintainer: Optional[str] = None
    description: Optional[str] = None
    bases: Bases = Bases([Base('ubuntu', 'focal')],
                         [Base('ubuntu', 'focal')])
    subordinate: bool = False

    def on_install(self, callback: Callable[[InstallEvent], None]) -> None:
        """Register a callback for install."""
        self.framework.observe(self.on.install, callback)

    def on_start(self, callback: Callable[[StartEvent], None]) -> None:
        """Register a callback for start."""
        self.framework.observe(self.on.start, callback)

    def on_stop(self, callback: Callable[[StopEvent], None]) -> None:
        """Register a callback for stop."""
        self.framework.observe(self.on.stop, callback)

    def on_remove(self, callback: Callable[[RemoveEvent], None]) -> None:
        """Register a callback for remove."""
        self.framework.observe(self.on.remove, callback)

    def on_update_status(self,
                         callback: Callable[[UpdateStatusEvent], None]) -> None:
        """Register a callback for update_status."""
        self.framework.observe(self.on.update_status, callback)

    def on_config_changed(self, callback: Callable[
        [ConfigChangedEvent], None]) -> None:
        """Register a callback for config_changed."""
        self.framework.observe(self.on.config_changed, callback)

    def on_upgrade_charm(self,
                         callback: Callable[[UpgradeCharmEvent], None]) -> None:
        """Register a callback for upgrade_charm."""
        self.framework.observe(self.on.upgrade_charm, callback)

    def on_pre_series_upgrade(self, callback: Callable[
        [PreSeriesUpgradeEvent], None]) -> None:
        """Register a callback for pre_series_upgrade."""
        self.framework.observe(self.on.pre_series_upgrade, callback)

    def on_post_series_upgrade(self, callback: Callable[
        [PostSeriesUpgradeEvent], None]) -> None:
        """Register a callback for post_series_upgrade."""
        self.framework.observe(self.on.post_series_upgrade, callback)

    def on_leader_elected(self, callback: Callable[
        [LeaderElectedEvent], None]) -> None:
        """Register a callback for leader_elected."""
        self.framework.observe(self.on.leader_elected, callback)

    def on_leader_settings_changed(self, callback: Callable[
        [LeaderSettingsChangedEvent], None]) -> None:
        """Register a callback for leader_settings_changed."""
        self.framework.observe(self.on.leader_settings_changed, callback)

    def on_collect_metrics(self, callback: Callable[
        [CollectMetricsEvent], None]) -> None:
        """Register a callback for collect_metrics."""
        self.framework.observe(self.on.collect_metrics, callback)

    @property
    def config(self) -> ExtendedConfigData:
        config_ = super().config
        changed = self.on.config_changed

        def on_changed(_, callback: Callable[[ConfigChangedEvent], None]):
            self.framework.observe(changed, callback)

        # we patch in a couple of attributes
        config_.on_changed = on_changed
        config_.changed = changed
        return config_

    def __init_subclass__(cls, **kwargs):
        for name, obj in vars(cls).items():
            if isinstance(obj, action):
                handlers = [obj for obj in vars(cls) if
                            getattr(obj, '__action__', None) is obj]
                for handler in handlers:
                    logger.debug(
                        f'registered action handler for {name}: {handler}')
                    cls.framework.observe(cls.on[obj.name].action, handler)
                cls.__actions__.append(obj)

            elif isinstance(obj, storage):
                cls.__storage__.append(obj)

            elif isinstance(obj, container):
                cls.__containers__.append(obj)

            # elif isinstance(obj, resource):
            #     cls.__resources__.append(obj)

            elif isinstance(obj, config):
                obj.bind(name)
                cls.__config__[name] = obj.var
                logger.debug(f'registered config handle for {name}: {obj}')

            elif isinstance(obj, relation):
                if obj.role == 'provide':
                    cls.__provides__.append(obj)
                    logger.debug(f'registered provides({name})')
                if obj.role == 'require':
                    cls.__requires__.append(obj)
                    logger.debug(f'registered requires({name})')
                if obj.role == 'peer':
                    cls.__peers__.append(obj)
                    logger.debug(f'registered peer({name})')
