# Jinx

This repository contains an experimental wrapper on top of ops/charmcraft
providing a novel API to write charms.

## Rationale

As a 'code project' (repo), a charm contains a number of YAML metadata files. 
The code depends on this metadata, in that the metadata is (at runtime) parsed
and used to generate dynamically certain namespaces which (at deploy time) are
used to interact with the juju API.

For example, if you define a 'proxy' config option in `config.yaml`, but your 
code says `self.config['proxA']`, only the runtime environment (e.g. a unittest) 
will spot the error, because the runtime will parse the yaml and determine that
'proxA' is an unknown option.

A way to solve this issue is to specify all that metadata **in code**, so that 
the linter will know (and lint-time is code-writing-time), that, for example, 
'proxA' is not a valid config option.

The metadata required by charmcraft can then be derived from the code.
This has two additional advantages:

- All information is in one place. It's easier to see what resources, actions, 
  metadata your charm has. You don't need to go search for the yaml file in 
  which to add this or that piece of information; instead, you do it there next 
  to the charm code.
- When developing, you get autocompletion and type-check errors if you make mistakes.

## Requirements

- python3.8 (earlier versions might be supported with typing_extensions)
- typer (to use unpack.py as a CLI tool)

## basic usage

Instead of importing `CharmBase` from `ops`, import `Jinx` from `jinx`.
You write jinxes like so:

```python
from jinx import *


class ExampleJinx(Jinx):
    name = 'my-charm'  # the only mandatory attribute; the rest is optional

    def __init__(self, framework, key=None):
        super().__init__(framework, key)
```

Save the file and run
`unpack /path/to/jinx_file.py`

And this will create for you:
- charmcraft.yaml
- actions.yaml
- config.yaml
- metadata.yaml

All except metadata and charmcraft will be empty, because we didn't define any 
relations, actions, storage, containers or config options. Next we'll see how
to do just that.

## relations

Let's add a couple of relations:

```python
from jinx import *


class ExampleJinx(Jinx):
    name = 'my-charm'

    # you declare the endpoints
    db_relation = require('db', InterfaceMeta('interface'))
    ingress_relation = provide('ingress', InterfaceMeta('ingress-per-cookie'))

    def __init__(self, framework, key=None):
        super().__init__(framework, key)
        # you use them
        self.db_relation.on_changed(self._on_db_changed)
        # is the new self.framework.observe(self.on.db_relation_changed, self._on_db_changed)

        # and then ...
        self.ingress_relation.on_departed(...)

    def _on_db_changed(self, event: RelationChangedEvent):
        pass
```

## config

Let's add a couple of config options:

```python
from jinx import *


class ExampleJinx(Jinx):
    name = 'my-charm'

    # you declare the config options
    thing = config(string('my description', default='foo'))
    other_thing = config(float_('my description', default=1.2))

    def __init__(self, framework, key=None):
        super().__init__(framework, key)

        self.config.on_changed(self._on_config_changed)
        # is the new self.framework.observe ... 

    def _on_config_changed(self, event: ConfigChangedEvent):
        # you get the config directly, by name:
        thing_value = self.thing  # the type checker knows this is a str
        # is the new self.config['thing']
```

## actions

Let's talk actions:

```python
from jinx import *


class ExampleJinx(Jinx):
    name = 'my-charm'

    # you declare an action like so:
    get_data = action(
        'get-data', params(
            foo=string(default='2'),
            bar=integer(default=2),
            baz=float_(default=2.2))
    )

    def __init__(self, framework, key=None):
        super().__init__(framework, key)
        # you don't observe actions here, instead...
        
    # ...you do this:
    @get_data.handler
    def _on_config_changed(self, event: ActionEvent):
        # the rest is (for now) as usual...
        foo = event.params['foo']
```

## storage

[todo]
