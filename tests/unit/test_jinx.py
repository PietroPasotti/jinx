import inspect

import pytest
import yaml
from jinx import *
from ops.testing import Harness

class OldSchoolCharm(CharmBase):
    def __init__(self, framework, key=None):
        super().__init__(framework, key)
        self.framework.observe(self.on.db_relation_changed, self._on_db_changed)
        self.thing = self.config['thing']
        self.other_thing = self.config['other_thing']

    def _on_db_changed(self, foo: RelationChangedEvent):
        pass

    def _handle_get_data(self, evt: ActionEvent):
        evt.set_results({'a response': 'this is'})


class ExampleJinx(Jinx):
    name = 'my-charm'

    db_relation = require(name='db', interface='interface')
    ingress_relation = provide(name='ingress', interface='ingress-per-cookie')

    thing = config(string('my description', default='foo'))
    other_thing = config(float_('my description', default=1.2))

    get_data = action(name='get_data', params=dict(
            foo=string(default='2'),
            bar=integer(default=2),
            baz=float_(default=2.2)
    ))

    def __init__(self, framework):
        super(ExampleJinx, self).__init__(framework)
        self.db_relation.on_changed(self._on_db_changed)
        # is the new self.framework.observe(self.on.db_relation_changed, self._on_db_changed)
        self.thing
        # is the new self.config['thing']

    def _on_db_changed(self, foo: RelationChangedEvent):
        pass

    @get_data.handler
    def _handle_get_data(self, evt: ActionEvent):
        return {'a response': 'this is'}


META = yaml.safe_dump(
    {'requires': {'db': {'interface': 'interface'}},
    'provides': {'ingress': {'interface': 'ingress-per-cookie'}}}
)
ACTIONS = yaml.safe_dump(
    {'get_data': {}}
)
CONFIG = yaml.safe_dump(
    {'options':
        {
            'thing': {'type': 'string', 'default': 'foo'},
            'other_thing': {'type': 'float', 'default': 1.2}
        }
    }
)


def test_meta_loading():
    h: Harness[ExampleJinx] = Harness(ExampleJinx, meta=META, config=CONFIG, actions=ACTIONS)
    h.begin_with_initial_hooks()

    assert h.charm.thing == 'foo'
    assert h.charm.other_thing == 1.2
    observers = h.charm.framework._observers


def test_consistency():
    hjinx: Harness[ExampleJinx] = Harness(ExampleJinx, meta=META, config=CONFIG, actions=ACTIONS)
    hcharm: Harness[OldSchoolCharm] = Harness(OldSchoolCharm, meta=META, config=CONFIG, actions=ACTIONS)
    hjinx.begin()
    hcharm.begin()

    assert hjinx.charm.config == hcharm.charm.config
    assert len(hjinx.framework._observers) == len(hcharm.framework._observers)


def test_binding():
    hjinx: Harness[ExampleJinx] = Harness(ExampleJinx, meta=META, config=CONFIG, actions=ACTIONS)
    hjinx.begin()
    charm = hjinx.charm
    all_meta = charm.__actions__ + list(charm.__config__.values()) + charm.__storage__ + charm.__containers__ + charm.__resources__ + charm.__requires__ + charm.__provides__ + charm.__peers__

    for obj in all_meta:
        assert obj.name


def test_constructors():
    bound = (config(string(), name='foo'), action(name='foo'), storage(name='foo', type='type'),
             peer(name='foo'), require(name='foo'), provide(name='foo'), resource(name='foo'))
    unbound = (config(string()), action(), storage('type'),
               peer(), require(), provide(), resource())

    for cns in bound:
        assert cns.name

    for cns in unbound:
        with pytest.raises(RuntimeError):
            _ = cns.name


@pytest.mark.parametrize('constructor, kw_args, obj_name, metas', (
        (peer, ((), {'interface': 'interface'}), 'peer-name', {'meta': {'peers': {
            'peer-name': {'interface': 'interface'},
            'default_name_obj': {'interface': 'interface'}
        }}}),
        (require, ((), {'interface': 'interface'}), 'requirer-name', {'meta': {'requires': {
            'requirer-name': {'interface': 'interface'},
            'default_name_obj': {'interface': 'interface'}
        }}}),
        (provide, ((), {'interface': 'interface'}), 'provider-name', {'meta': {'provides': {
            'provider-name': {'interface': 'interface'},
            'default_name_obj': {'interface': 'interface'}
        }}}),
        (action, ((), {}), 'action-name', {'actions': {'action-name': {},
                                                       'default_name_obj': {}}}),
        (config, ((string(), ), {}), 'config-key', {'config': {
            'config-key': {'type': 'string'},
            'default_name_obj': {'type': 'string'},
        }}),
        (storage, (('filesystem', ), {}), 'storage-name', {'meta': {'storage': {
            'storage-name': {'type': 'filesystem'},
            'default_name_obj': {'type': 'filesystem'},
        }}}),
        (container, (('dummy_resource',), {}), 'container-name', {'meta': {'containers': {
            'container-name': {'resource': 'dummy_resource'},
            'default_name_obj': {'resource': 'dummy_resource'},
        }}})
), ids=["peer", "require", "provide", "action", "config", "storage", "container"])
def test_name_late_binding(constructor, kw_args, obj_name, metas):
    args, kwargs = kw_args

    class NamedMetaJinx(Jinx):
        name = 'my-charm'
        default_name_obj = constructor(*args, **kwargs)
        custom_name_obj = constructor(*args, name=obj_name, **kwargs)

    yamlified = {k: yaml.safe_dump(v) for k, v in metas.items()}
    hjinx: Harness[NamedMetaJinx] = Harness(NamedMetaJinx, **yamlified)
    hjinx.begin()

    charm = hjinx.charm
    if constructor is config:
        # becomes a getter: we need some extra care
        default_obj = charm.__config__['default_name_obj']
        custom_obj = charm.__config__['custom_name_obj']

    else:
        default_obj = charm.default_name_obj
        custom_obj = charm.custom_name_obj

    assert default_obj.name == 'default_name_obj'
    assert custom_obj.name == obj_name
