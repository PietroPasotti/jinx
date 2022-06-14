from ops.testing import Harness

from jinx import Serializer, harness
from resources.template_jinx import MyCharm


def test_events():
    serializer = Serializer(MyCharm)
    har = harness(MyCharm)
    har.begin()

    charm = har.charm

    def assert_status_event(status):
        msg = charm.unit.status.message
        # e.g. f"MyCharm/on/{status}[1]"
        assert msg.split('/')[-1].split('[')[0] == status

    charm.on.start.emit()
    assert_status_event('start')

    charm.on.install.emit()
    assert_status_event('install')

