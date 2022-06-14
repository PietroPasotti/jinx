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
class Platform:
    name: str = 'ubuntu'
    channel: str = '20.04'


@dataclass
class Base:
    run_on: List[Platform]
    build_on: List[Platform]

    def to_dict(self):
        return {'run-on': [asdict(b) for b in self.run_on],
                'build-on': [asdict(b) for b in self.build_on]}


RelationName = ResourceName = StorageName = ContainerName = ActionName = str


def _sanitize(s: str) -> str:
    return s.replace('-', '_')


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
def Param(type: Literal['string'], description: str = '',
          default: Optional[str] = None) -> _Param: ...


@overload
def Param(type: Literal['float'], description: str = '',
          default: Optional[float] = None) -> _Param: ...


@overload
def Param(type: Literal['integer'], description: str = '',
          default: Optional[int] = None) -> _Param: ...


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


class LateBoundNamed:
    def __init__(self, name: Optional[str]):
        self._name = name  # set by .bind() later if None

    @property
    def name(self):
        if not self._name:
            raise RuntimeError(f'unbound {self}')
        return self._name

    def bind(self, name):
        """Defaults name to prop."""
        if not self._name:
            self._name = name


class _Config(LateBoundNamed):
    def __init__(self, name: Optional[str], var: _Param):
        super().__init__(name)
        self.var = var

    def __get__(self, instance, owner: 'Jinx'):
        return instance.config[self.name]


@dataclass
class ActionMeta:
    params: Dict[str, _Param]


@dataclass
class FSStorageSpec:
    type: str
    location: Optional[str] = None


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


class _Storage(LateBoundNamed):
    def __init__(self, name: Optional[ContainerName], type: str,
                 location: str = None):
        super().__init__(name)
        self.meta = FSStorageSpec(type, location)

    def __get__(self, obj, _type=None):
        return _BoundStorage(self.name, self.meta.type, self.meta.location, obj)


class _BoundStorage(_Storage):
    def __init__(self, name: ContainerName, type: str, location: str,
                 obj: CharmBase):
        super().__init__(name, type, location)
        self.attached = obj.on[_sanitize(name)].storage_attached
        self.detaching = obj.on[_sanitize(name)].storage_detaching
        self._obj = obj

    def on_attached(self, callback: Callable[[StorageAttachedEvent], None]):
        self._obj.framework.observe(self.attached, callback)

    def on_detached(self, callback: Callable[[StorageDetachingEvent], None]):
        self._obj.framework.observe(self.detaching, callback)


class _Action(LateBoundNamed):
    def __init__(self, name: Optional[ActionName],
                 params: Dict[str, _Param] = None):
        super().__init__(name)
        self.params = params
        self.meta = ActionMeta(params if params else {})

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


class _Resource(LateBoundNamed):
    def __init__(self, name: Optional[ContainerName] = None,
                 type: str = 'oci-image',
                 description: str = None,
                 upstream_source: str = None):
        super().__init__(name)
        self.meta = ResourceSpec(type, description, upstream_source)


class _Container(LateBoundNamed):
    def __init__(self, name: Optional[ContainerName], resource: str):
        super().__init__(name)
        self.meta = ContainerSpec(resource)

    def __get__(self, obj, _type=None):
        return _BoundContainer(self.name, self.meta.resource, obj)


class _BoundContainer(_Container):
    def __init__(self, name: ContainerName, resource: str,
                 obj: CharmBase):
        super().__init__(name, resource)
        self.pebble_ready = obj.on[_sanitize(name)].pebble_ready
        self._obj = obj

    def on_pebble_ready(self, callback: Callable[[PebbleReadyEvent], None]):
        self._obj.framework.observe(self.pebble_ready, callback)


Role = Literal['require', 'provide', 'peer']


class _Relation(LateBoundNamed):
    def __init__(self, name: Optional[str], interface: str, role: Role):
        super().__init__(name)
        self.meta = InterfaceMeta(interface)
        self.role = role

    def __get__(self, obj, _type=None):
        return _BoundRelation(self.name, self.meta.interface, self.role, obj)


class _BoundRelation(_Relation):
    def __init__(self, name: str,
                 interface: str,
                 role: Role,
                 obj: CharmBase):
        super().__init__(name, interface, role)
        self.created = obj.on[_sanitize(name)].relation_created
        self.broken = obj.on[_sanitize(name)].relation_broken
        self.joined = obj.on[_sanitize(name)].relation_joined
        self.departed = obj.on[_sanitize(name)].relation_departed
        self.changed = obj.on[_sanitize(name)].relation_changed
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


class ExtendedConfigData(ConfigData):
    on_changed: Callable[[Callable[[ConfigChangedEvent], None]], None]
    changed: EventSource


class Jinx(CharmBase, metaclass=JinxMeta):
    __actions__: List['_Action']
    __config__: Dict[str, '_Config']
    __provides__: List['_Relation']
    __requires__: List['_Relation']
    __peers__: List['_Relation']
    __storage__: List['_Storage']
    __containers__: List['_Container']
    __resources__: List['_Resource']

    if TYPE_CHECKING:
        framework: Framework

    @property
    @abstractmethod
    def name(self):
        ...

    summary: Optional[str] = None
    maintainer: Optional[str] = None
    description: Optional[str] = None
    bases: List[Base] = [Base(build_on=[Platform('ubuntu', '20.04')],
                              run_on=[Platform('ubuntu', '20.04')])]
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
        # dedup
        cls.__actions__: List['_Action'] = []
        cls.__config__: Dict[str, '_Config'] = {}
        cls.__provides__: List['_Relation'] = []
        cls.__requires__: List['_Relation'] = []
        cls.__peers__: List['_Relation'] = []
        cls.__storage__: List['_Storage'] = []
        cls.__containers__: List['_Container'] = []
        cls.__resources__: List['_Resource'] = []

        for parent in cls.mro():
            for name, obj in vars(parent).items():
                if isinstance(obj, LateBoundNamed):
                    # allow defaulting name to the attr they are assigned
                    # to in this class
                    obj.bind(name)

                if isinstance(obj, _Action):
                    handlers = [obj for obj in vars(cls) if
                                getattr(obj, '__action__', None) is obj]
                    for handler in handlers:
                        logger.debug(
                            f'registered action handler for {name}: {handler}')
                        cls.framework.observe(cls.on[obj.name].action, handler)

                    cls.__actions__.append(obj)

                elif isinstance(obj, _Storage):
                    cls.__storage__.append(obj)

                elif isinstance(obj, _Container):
                    cls.__containers__.append(obj)

                # elif isinstance(obj, resource):
                #     cls.__resources__.append(obj)

                elif isinstance(obj, _Config):
                    cls.__config__[name] = obj
                    logger.debug(f'registered config handle for {name}: {obj}')

                elif isinstance(obj, _Relation):
                    if obj.role == 'provide':
                        cls.__provides__.append(obj)
                        logger.debug(f'registered provides({name})')
                    if obj.role == 'require':
                        cls.__requires__.append(obj)
                        logger.debug(f'registered requires({name})')
                    if obj.role == 'peer':
                        cls.__peers__.append(obj)
                        logger.debug(f'registered peer({name})')


# utility constructors
def config(param: _Param, name: str = None) -> _Config:
    return _Config(name, param)


def relation(interface: str, role: Role, name: str = None) -> _Relation:
    return _Relation(name, interface=interface, role=role)


def require(interface: str = None, name: str = None) -> _Relation:
    return _Relation(name, interface=interface, role='require')


def provide(interface: str = None, name: str = None) -> _Relation:
    return _Relation(name, interface=interface, role='provide')


def peer(interface: str = None, name: str = None) -> _Relation:
    return _Relation(name, interface=interface, role='peer')


def container(resource: str, name: str = None) -> _Container:
    return _Container(name, resource)


def resource(type: str = 'oci-image',
             description: str = None,
             upstream_source: str = None,
             name: str = None) -> _Resource:
    return _Resource(name=name, type=type, description=description,
                     upstream_source=upstream_source)


def action(params: Dict[str, _Param] = None, name: str = None) -> _Action:
    return _Action(name, params)


def storage(type: str, location: str = None, name: str = None) -> _Storage:
    return _Storage(name, type=type, location=location)


# fmt: on


class Serializer:
    def __init__(self, jinx: Type[Jinx]):
        self.jinx = jinx

    @property
    def config(self):
        jinx = self.jinx
        data = {'options': {
            key: asdict(conf.var) for key, conf in
            jinx.__config__.items()}}
        return data

    @property
    def charmcraft(self):
        jinx = self.jinx
        data = {'type': 'charm',
                'bases': [base.to_dict() for base in jinx.bases]}
        return data

    @property
    def actions(self):
        jinx = self.jinx
        data = {}
        for a in jinx.__actions__:
            data.update(a.as_dict())
        return data

    @property
    def metadata(self):
        jinx = self.jinx
        data = {'name': jinx.name}

        if jinx.subordinate:
            data['subordinate'] = jinx.subordinate

        if jinx.description:
            data['description'] = jinx.description
        if jinx.summary:
            data['summary'] = jinx.summary

        if jinx.__provides__:
            data['provides'] = {r.name: asdict(r.meta) for r in
                                jinx.__provides__}
        if jinx.__requires__:
            data['requires'] = {r.name: asdict(r.meta) for r in
                                jinx.__requires__}
        if jinx.__peers__:
            data['peers'] = {r.name: asdict(r.meta) for r in jinx.__peers__}

        if jinx.__containers__:
            data['containers'] = {c.name: asdict(c.meta) for c in
                                  jinx.__containers__}
        if jinx.__resources__:
            data['resources'] = {c.name: asdict(c.meta) for c in
                                 jinx.__resources__}
        if jinx.__storage__:
            data['storage'] = {c.name: asdict(c.meta) for c in
                               jinx.__storage__}
        return data


def harness(jinx: Type[Jinx]):
    from ops.testing import Harness
    serializer = Serializer(jinx)
    return Harness(jinx,
                   meta=yaml.safe_dump(serializer.metadata),
                   actions=yaml.safe_dump(serializer.actions),
                   config=yaml.safe_dump(serializer.config))
