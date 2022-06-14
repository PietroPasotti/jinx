import tempfile
from pathlib import Path
from subprocess import Popen

from pytest_operator.plugin import OpsTest

root = Path(__file__).parent.parent.parent.absolute()
path_to_template_jinx = root / 'resources' / 'template_jinx.py'
path_to_unpack_script = root / 'unpack.py'

script = f"""charmcraft init; 
rm ./*.yaml;
cp {path_to_template_jinx} ./src/charm.py;
{path_to_unpack_script} ./src/charm.py;
charmcraft pack
"""


async def test_template(ops_test: OpsTest):
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        expected_charm_file = tempdir / 'src' / 'charm.py'

        with tempdir:
            Popen(script.split()).wait()
            assert expected_charm_file.exists()
            assert expected_charm_file.read_text() == path_to_template_jinx.read_text()

        await ops_test.model.deploy(expected_charm_file)
        await ops_test.model.wait_for_idle(['my-charm'])
