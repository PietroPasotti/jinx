import pytest
import yaml

from jinx import *
from pathlib import Path
from tempfile import mkdtemp

from unpack import unpack

META = {'name': 'my-charm',
        'requires': {'db': {'interface': 'interface'}},
        'provides': {'ingress': {'interface': 'ingress-per-cookie'}},
        'subordinate': False}
ACTIONS = {
    'get_data': {
        'params': {
            'bar': {'default': 2,
                    'description': '',
                    'type': 'integer'},
            'baz': {'default': 2.2,
                    'description': '',
                    'type': 'float'},
            'foo': {'default': '2',
                    'description': '',
                    'type': 'string'
                    }
        }
    }
}
CONFIG = {'options':
    {
        'thing': {'type': 'string', 'description': 'my description',
                  'default': 'foo'},
        'other_thing': {'type': 'float', 'description': 'my description',
                        'default': 1.2}
    }
}
CHARMCRAFT = {'type': 'charm',
              'bases': [{
                  'build-on': [{'name': 'ubuntu', 'channel': 'focal'}],
                  'run-on': [{'name': 'ubuntu', 'channel': 'focal'}]
              }]
              }


class ExampleJinx(Jinx):
    name = 'my-charm'

    db_relation = require(name='db', interface='interface')
    ingress = provide(interface='ingress-per-cookie')

    thing = config(string('my description', default='foo'))
    other_thing = config(float_('my description', default=1.2))

    get_data = action(dict(
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


@pytest.mark.parametrize("name, expected_contents", (
        ('metadata', META),
        ('charmcraft', CHARMCRAFT),
        ('config', CONFIG),
        ('actions', ACTIONS)))
def test_unpack(name, expected_contents):
    tempdir = Path(mkdtemp())
    path_to_jinx_file = Path(__file__).absolute()

    unpack(path_to_jinx_file, root=tempdir)
    file = tempdir / (name + '.yaml')
    contents = yaml.safe_load(file.read_text())
    assert contents == expected_contents


def test_unpack_src():
    tempdir = Path(mkdtemp())
    path_to_jinx_file = Path(__file__).absolute()

    unpack(path_to_jinx_file, root=tempdir)
    charm_file = tempdir / 'src' / 'charm.py'
    assert charm_file.exists()
    assert charm_file.read_text() == Path(__file__).read_text()


def test_unpack_include():
    tempdir = Path(mkdtemp())
    path_to_jinx_file = Path(__file__).absolute()
    jinxtest = path_to_jinx_file.parent / 'test_jinx.py'
    unpack(path_to_jinx_file, root=tempdir, include=[jinxtest])
    assert (tempdir / 'src' / 'test_jinx.py').exists()
