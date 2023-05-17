#!/usr/bin/env python3
# pylint: disable=missing-function-docstring
# pylint: disable=wildcard-import
# pylint: disable=unused-wildcard-import
# pylint: disable=protected-access

"""Tests for mash and mashlib.  Usually run via the check script, but can be
used from the command line as well to run single tests."""

import contextlib
import subprocess
import sys
import tempfile
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
def temporary_current_directory(linked_files=None):
    """Create a context in which the current directory is a new temporary
    directory.  In this temporary directory, create symlinks to the given
    files.  When the context ends, the current directory is restored and the
    temporary directory is vaporized."""

    linked_files = linked_files if linked_files else []
    linked_files = [os.path.abspath(x) for x in linked_files]
    with tempfile.TemporaryDirectory() as temporary_dir:
        with temporarily_changed_directory(temporary_dir):
            for linked_file in linked_files:
                os.symlink(linked_file, os.path.join(temporary_dir, os.path.basename(linked_file)))
            try:
                yield
            finally:
                pass

def run_tests_from_pattern(): #pragma nocover
    # If we're run as a script, just execute all of the tests.  Or, if a
    # command line argument is given, execute only the tests containing that
    # pattern.
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
################################################################################

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

def test_stdin_input():
    engage(['mash3'])

def test_frame_stats1():
    root = tree_from_string('a\nb[[[c|||d]]]e\nf', '')
    stats = root.stats()
    assert stats == Stats(2, 1, 3)

def test_frame_stats2():
    root = tree_from_string('[[[ include abc ]]]', '')
    print(root.as_indented_string())
    stats = root.stats()
    print(stats)
    assert stats == Stats(2, 0, 1)

def test_codeleaf_execute1():
    # Somthing simple.
    CodeLeaf(Address('xyz.mash', 1, 1), None, "print('hello')").execute({})

def test_codeleaf_execute2():
    # Syntax error.
    with pytest.raises(SyntaxError):
        CodeLeaf(Address('xyz.mash', 1, 1), None, "print 'hello'").execute({})

def test_codeleaf_execute3():
    # Correct line number.
    with pytest.raises(Exception) as exc_info:
        CodeLeaf(Address('xyz.mash', 5, 1),
                 None,
                 "  \n\n\n  raise ValueError('sadness')").execute({})

    formatted_tb = '\n'.join(traceback.format_tb(exc_info._excinfo[2]))
    assert '"xyz.mash", line 8' in formatted_tb

def test_textleaf_execute1():
    # Simple.
    TextLeaf(Address('xyz.mash', 1, 1), None, "print('hello')").execute({})

def test_textleaf_execute2():
    # Text leaves don't execute their content as code -- no exception here.
    TextLeaf(Address('xyz.mash', 1, 1), None, "print 'hello'").execute({})

def test_frame_execute():
    # Something simple.
    root = tree_from_string('A [[[ print("B") ]]] C', 'xyz.mash')
    root.execute({})

def test_frame_execute2():
    # Check recursive execution, normal case.
    root = tree_from_string('[[[ print("B") ||| [[[ print("C") ||| D ]]] ]]]', 'xyz.mash')
    root.execute({})


def test_frame_execute3():
    # Check recursive execution, failing.
    root = tree_from_string('[[[ print("B") ||| [[[ print C ||| D ]]] ]]]', 'xyz.mash')
    with pytest.raises(SyntaxError):
        root.execute({})

def test_vars1():
    # Variables from child frames are visible to parents.
    code = """
        [[[
            print(x)
            [[[ x = 3 ]]]
        ]]]
    """
    root = tree_from_string(code, 'xyz.mash')
    root.execute({})

def test_vars2():
    # Vars from later children replace vars from earlier children.
    code = """
        [[[
            [[[
                import time
                time.sleep(0.5)
                x = 3
            ]]]
            [[[
                x = 4
            ]]]
        ]]]
    """
    variables = {}
    root = tree_from_string(code, 'xyz.mash')
    root.execute(variables)

    assert 'x' in variables
    assert variables['x'] == 4

def test_restart_request1():
    # RestartRequest is visible from mash code.
    code = """
        [[[
            raise RestartRequest
        ]]]
    """
    with pytest.raises(RestartRequest):
        tree_from_string(code, '').execute(default_variables())

def test_restart_request2():
    # RestartRequests are correctly handled in main()
    with temporary_current_directory():
        code = """
            [[[
                import os
                if not os.path.exists('1'):
                    os.system('touch 1')
                    raise RestartRequest
                else:
                    os.system('touch 2')
            ]]]
        """
        with open('test.mash', 'w', encoding='utf-8') as output_file:
            print(code, file=output_file)
        main(['mash3', 'test.mash'])
        assert os.path.exists('1')
        assert os.path.exists('2')


def test_include():
    # Included files are found and imported.
    with temporary_current_directory():
        with open('included.mash', 'w', encoding='utf-8') as output_file:
            print('[[[ def foo():\n    return "bar"]]]',
                  file=output_file)
        code = """
            [[[
                [[[ include included.mash ]]]
                foo()
            ]]]
        """
        root = tree_from_string(code, 'xyz.mash')
        root.execute({})

def test_mashlib_shell1():
    # Shell commands run correctly.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            shell('ls /dev')
        ]]]
    """
    root = tree_from_string(code, 'xyz.mash')
    variables = {}
    root.execute(variables)
    variables['at_end']()

def test_mashlib_shell2():
    # Broken commands raise exceptions.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            result = shell('ls /foobar')
        ]]]
    """
    root = tree_from_string(code, 'xyz.mash')
    variables = {}
    root.execute(variables)
    with pytest.raises(subprocess.CalledProcessError):
        variables['at_end']()

def test_subprocess_error_report1():
    # Exceptions from broken commands are caught and reported gracefully.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            result = shell('ls /foobar')
        ]]]
    """

    with temporary_current_directory(['mashlib.mash']):
        with open('test.mash', 'w', encoding='utf-8') as output_file:
            print(code, file=output_file)

        engage(['mash3', 'test.mash'])

def test_subprocess_max_jobs():
    # The max_jobs setting actually limits the number of parallel shell jobs
    # running at a time.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            max_jobs = 2
            shell('echo 10 >> nums; sleep 0.1; echo 11 >> nums; sleep 0.1')
            shell('echo 20 >> nums; sleep 0.1; echo 21 >> nums; sleep 0.1')
            shell('echo 30 >> nums; sleep 0.1; echo 31 >> nums; sleep 0.1')
        ]]]
    """
    root = tree_from_string(code, "xyz.mash")

    with temporary_current_directory(['mashlib.mash']):
        variables = default_variables()
        root.execute(variables)
        variables['at_end']()
        with open('nums', encoding='utf-8') as numbers_file:
            numbers = numbers_file.read()

    numbers = list(map(int, numbers.strip().split('\n')))
    print(numbers)

    # 20 before 11, to show that the second job runs in parallel with the
    # first one.
    assert numbers.index(20) < numbers.index(11)

    # (30 after 11) or (30 after 21), to show that the third job waits
    # until either of the first two are done.
    assert (numbers.index(30) > numbers.index(11)) or \
        (numbers.index(30) > numbers.index(21))

def test_at_end():
    # Call to at_end() after full tree is executed.
    with temporary_current_directory():
        code = """
            [[[
                def at_end():
                    raise ValueError
            ]]]
        """
        with open('test.mash', 'w', encoding='utf-8') as output_file:
            print(code, file=output_file)

        with pytest.raises(ValueError):
            engage(['mash3', 'test.mash'])

if __name__ == '__main__':  #pragma: nocover
    run_tests_from_pattern()
