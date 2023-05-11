#!/usr/bin/env python3
# pylint: disable=missing-module-docstring
# pylint: disable=missing-function-docstring
# pylint: disable=wildcard-import
# pylint: disable=too-many-lines
# pylint: disable=unused-wildcard-import

import contextlib
import sys
import tempfile

import pytest

from mash3 import *

@contextlib.contextmanager
def temporarily_changed_directory(directory):
    """Create a context in which the current directory has been changed to the
    given one, which should exist already.  When the context ends, change the
    current directory back."""
    previous_current_directory = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous_current_directory)


@contextlib.contextmanager
def temporary_current_directory():
    """Create a context in which the current directory is a new temporary
    directory.  When the context ends, the current directory is restored and
    the temporary directory is vaporized."""
    with tempfile.TemporaryDirectory() as temporary_dir:
        with temporarily_changed_directory(temporary_dir):
            try:
                yield
            finally:
                pass

def test_element_seq_from_string():
    elements = list(element_seq_from_string('a\nb[[[ c ||| d ]]] e\n f', 'x'))

    # Basics.
    assert len(elements) == 7

    # No exceptions from __str__.
    elements[0].__str__()

    # Deal correctly when a token is at the very start.
    tree_from_string('[[[ a ]]]', 'x')

def test_element_tree_from_string():
    # Basics
    root = tree_from_string('a\nb[[[c|||d]]]e\nf', 'x')
    assert len(root.code_children) == 0
    assert len(root.text_children) == 3
    assert isinstance(root.text_children[0], Element)
    assert isinstance(root.text_children[1], Frame)
    assert len(root.text_children[1].code_children) == 1
    assert len(root.text_children[1].text_children) == 1

    # Extra separator, with file name and line in error message.
    with pytest.raises(ValueError) as exception:
        tree_from_string('[[[ a \n ||| b \n ||| c ]]]', 'xyz')

    assert 'xyz:3' in str(exception)

    # Missing closing delimiter.  Error should show where the frame started.
    with pytest.raises(ValueError) as exception:
        tree_from_string('1  \n 2 \n 3 [[[ a \n b \n c \n d', 'abc')
    assert 'abc:3' in str(exception)

    # Extra closing delimiter.
    with pytest.raises(ValueError):
        tree_from_string('[[[ \n a \n ||| \n b \n ]]] \n c \n ]]]', 'x')

def test_dash_c():
    with temporary_current_directory():
        os.mkdir('.mash')
        os.mkdir('.mash-archive')
        engage(['mash3', '-c'])
        assert not os.path.exists('.mash')
        assert not os.path.exists('.mash-archive')

def test_file_input():
    with temporary_current_directory():
        with open('test.mash', 'w', encoding='utf-8') as output_file:
            print('[[[ a ||| b ]]]', file=output_file)
        engage(['mash3', 'test.mash'])

def test_frame_stats():
    root = tree_from_string('a\nb[[[c|||d]]]e\nf', '')
    stats = root.stats()
    assert stats == (2, 1, 3)



# If we're run as a script, just execute all of the tests.  Or, if a
# command line argument is given, execute only the tests containing
# that pattern.

def test_from_pattern(): #pragma nocover
    pattern = ''
    try:
        pattern = sys.argv[1]
    except IndexError:
        pass

    for name, thing in list(globals().items()):
        if 'test_' in name and pattern in name:
            print('-'*80)
            print(name)
            print('-'*80)
            thing()
            print()

if __name__ == '__main__':  #pragma: nocover
    test_from_pattern()
