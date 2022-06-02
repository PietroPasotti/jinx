#! /bin/python3

import os
import shutil
from dataclasses import asdict
from typing import Union, Type, Sequence, Optional
from pathlib import Path

import yaml

from jinx import Jinx

import importlib.util
import sys


def get_jinx_class(path_to_jinx) -> Type[Jinx]:
    path_to_jinx = Path(path_to_jinx)
    source = path_to_jinx.read_text()
    spec = importlib.util.spec_from_file_location("jinx", path_to_jinx)
    module = importlib.util.module_from_spec(spec)
    sys.modules["module.name"] = module
    spec.loader.exec_module(module)

    Jinx_Type = module.__dict__.get('Jinx')
    if not Jinx_Type:
        raise RuntimeError('expecting a Charm inheriting directly from Jinx, '
                           'but Jinx is not even imported in the source.')

    jinx = None
    for name, obj in module.__dict__.items():
        if isinstance(obj, type) and issubclass(obj, Jinx_Type) and (
                obj is not Jinx_Type):
            if jinx:
                raise RuntimeError(
                    f'multiple jinxes found in {path_to_jinx}: {jinx} and {name}:{obj}')
            jinx = obj

    if not jinx:
        raise RuntimeError(f'No Jinx subclass found in {path_to_jinx}.')
    return jinx


LIC_HEADER = """# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.\n\n"""


def dump_metadata(jinx: Type[Jinx], root: Path, license: str):
    data = {'name': jinx.name,
            'subordinate': jinx.subordinate}

    if jinx.description:
        data['description'] = jinx.description
    if jinx.summary:
        data['summary'] = jinx.summary

    if jinx.__provides__:
        data['provides'] = {r.name: asdict(r.meta) for r in jinx.__provides__}
    if jinx.__requires__:
        data['requires'] = {r.name: asdict(r.meta) for r in jinx.__requires__}
    if jinx.__peers__:
        data['peer'] = {r.name: asdict(r.meta) for r in jinx.__peers__}

    if jinx.__containers__:
        data['containers'] = {c.name: asdict(c.meta) for c in
                              jinx.__containers__}
    if jinx.__resources__:
        data['resources'] = {c.name: asdict(c.meta) for c in
                              jinx.__resources__}
    if jinx.__storage__:
        data['storage'] = {c.name: asdict(c.meta) for c in
                              jinx.__storage__}

    (root / 'metadata.yaml').write_text(license + yaml.safe_dump(data))


def dump_actions(jinx: Type[Jinx], root: Path, license: str):
    data = {}
    for a in jinx.__actions__:
        data.update(a.as_dict())
    (root / 'actions.yaml').write_text(license + yaml.safe_dump(data))


def dump_charmcraft(jinx: Type[Jinx], root: Path, license: str):
    data = {'type': 'charm',
            'bases': jinx.bases.to_dict()}
    (root / 'charmcraft.yaml').write_text(license + yaml.safe_dump(data))


def dump_config(jinx: Type[Jinx], root: Path, license: str):
    data = {'options': {key: asdict(var) for key, var in
                        jinx.__config__.items()}}
    (root / 'config.yaml').write_text(license + yaml.safe_dump(data))


def unpack(path_to_jinx: Union[str, Path], root: Union[str, Path] = None,
           license: str = LIC_HEADER, overwrite=False,
           include: Optional[Union[str, Sequence[Union[str, Path]]]] = None):
    if include is None:
        include = ()
    if isinstance(include, str):
        include = include.split(';')

    root = (root or Path()).absolute()

    jinx = get_jinx_class(path_to_jinx)
    dump_metadata(jinx, root, license)
    dump_actions(jinx, root, license)
    dump_config(jinx, root, license)
    dump_charmcraft(jinx, root, license)

    if root:
        src = root / 'src'
        charmfile = src / 'charm.py'
        if src.exists() and src.is_dir():
            if charmfile.exists():
                if not overwrite:
                    print(
                        'found existing /src/charm.py. pass --overwrite to overwrite')
                    return
        elif not src.exists():
            os.mkdir(src)
        else:
            # src is a file
            print('expected /src directory; found a "src" file!')
            return

        shutil.copy2(path_to_jinx, charmfile)
        for name in include:
            pth = Path(name)
            if pth.is_dir():
                shutil.copytree(pth, src)
            else:
                shutil.copy2(pth, src)
            print(f'included {name}')


if __name__ == '__main__':
    from typer import run, Argument, Option
    def _unpack(
            path_to_jinx: str = Argument(
                ...,
                help='path to a file containing a Jinx.'),
            root: str = Option(
                None, help="path to charm root folder. "
                           "If left blank, we'll take it to be ./."),
            license: str = Option(
                LIC_HEADER, help='license text to prepend to all '
                                 'created yaml files. Defaults to '
                                 'Canonical 2022'),
            overwrite: bool = Option(
                False, help='whether to overwrite an '
                            'existing charm file if present.'),
            include: Optional[str] = Option(
                None, help='semicolon-separated list of files and '
                           'directories to copy along with the '
                           'jinx to the root/src.')):
        unpack(path_to_jinx, root, license, overwrite, include)

    run(_unpack)
