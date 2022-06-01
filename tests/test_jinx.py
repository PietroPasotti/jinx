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

    db_relation = require('db', InterfaceMeta('interface'))
    ingress_relation = provide('ingress', InterfaceMeta('ingress-per-cookie'))

    thing = config(string('my description', default='foo'))
    other_thing = config(float_('my description', default=1.2))

    get_data = action('get_data', ActionMeta(
        {
            'foo': string(default='2'),
            'bar': integer(default=2),
            'baz': float_(default=2.2)
        }
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