#!/usr/bin/env python3
# pylint: disable=missing-module-docstring
# pylint: disable=missing-function-docstring
# pylint: disable=wildcard-import
# pylint: disable=too-many-lines
# pylint: disable=unused-wildcard-import
# pylint: disable=protected-access

import contextlib
import sys
import tempfile
import concurrent.futures
import traceback

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

def get_executor():
    return concurrent.futures.ThreadPoolExecutor(max_workers=4)

def test_unindent():
    code = "    print('hello')\n    print('world')"
    assert len(code) - len(unindent(code)) == 8

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
    root = tree_from_string('a\nb[[[c|||d]]]e\nf', 'x.mash')
    print(root.as_indented_string())
    assert len(root.children) == 3
    assert isinstance(root.children[0], TextLeaf)
    assert isinstance(root.children[1], Frame)
    assert len(root.children[1].children) == 2
    assert isinstance(root.children[1].children[0], CodeLeaf)
    assert isinstance(root.children[1].children[1], TextLeaf)


    # Extra separator, with file name and line in error message.
    with pytest.raises(ValueError) as exc_info:
        tree_from_string('[[[ a \n ||| b \n ||| c ]]]', 'xyz.mash')

    assert 'xyz.mash, line 3' in str(exc_info)

    # Missing closing delimiter.  Error should show where the frame started.
    with pytest.raises(ValueError) as exc_info:
        tree_from_string('1  \n 2 \n 3 [[[ a \n b \n c \n d', 'abc.mash')
    assert 'abc.mash, line 3' in str(exc_info)

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
            print('[[[ print() ||| b ]]]', file=output_file)
        engage(['mash3', 'test.mash'])

def test_frame_stats():
    root = tree_from_string('a\nb[[[c|||d]]]e\nf', '')
    stats = root.stats()
    assert stats == Stats(2, 1, 3)

def test_codeleaf_execute1():
    # Somthing simple.
    CodeLeaf(Address('xyz.mash', 1, 1), None, "print('hello')").execute(get_executor())

def test_codeleaf_execute2():
    # Syntax error.
    with pytest.raises(SyntaxError):
        CodeLeaf(Address('xyz.mash', 1, 1), None, "print 'hello'").execute(get_executor())

def test_codeleaf_execute3():
    # Correct line number.
    with pytest.raises(Exception) as exc_info:
        CodeLeaf(Address('xyz.mash', 5, 1),
                 None,
                 "  \n\n\n  raise ValueError('sadness')").execute(get_executor())

    formatted_tb = '\n'.join(traceback.format_tb(exc_info._excinfo[2]))
    assert '"xyz.mash", line 8' in formatted_tb

def test_textleaf_execute1():
    # Simple.
    TextLeaf(Address('xyz.mash', 1, 1), None, "print('hello')").execute(get_executor())

def test_textleaf_execute2():
    # Text leaves don't execute their content as code -- no exception here.
    TextLeaf(Address('xyz.mash', 1, 1), None, "print 'hello'").execute(get_executor())

def test_frame_execute():
    root = tree_from_string('A [[[ print("B") ]]] C', 'xyz.mash')
    root.execute(get_executor())

def test_frame_execute2():
    # Check recursive execution, normal case.
    root = tree_from_string('[[[ print("B") ||| [[[ print("C") ||| D ]]] ]]]', 'xyz.mash')
    root.execute(get_executor())


def test_frame_execute3():
    # Check recursive execution, failing.
    root = tree_from_string('[[[ print("B") ||| [[[ print C ||| D ]]] ]]]', 'xyz.mash')
    with pytest.raises(SyntaxError):
        root.execute(get_executor())




# If we're run as a script, just execute all of the tests.  Or, if a
# command line argument is given, execute only the tests containing
# that pattern.

def run_tests_from_pattern(): #pragma nocover
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
    run_tests_from_pattern()
