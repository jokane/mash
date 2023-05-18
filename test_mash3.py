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
from exceptiongroup import ExceptionGroup

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

@contextlib.contextmanager
def engage_string(code, files=None):
    with temporary_current_directory(linked_files=['mashlib.mash']):
        filename = 'dummy.mash'
        with open(filename, 'w', encoding='utf-8') as output_file:
            print(code, file=output_file)

        if files is None:
            files = {}

        for filename2, contents in files.items():
            with open(filename2, 'w', encoding='utf-8') as output_file:
                print(contents, file=output_file)

        engage(['mash3', filename])
        try:
            yield
        finally:
            pass


################################################################################

def test_unindent():
    code = "    print('hello')\n    print('world')"
    assert len(code) - len(unindent(code)) == 8

def test_element_seq_from_string1():
    code = """
      a
      b
      [[[
          c
          d
      |||
          e
      ]]]
      f
      g
    """
    elements = list(element_seq_from_string(code, "dummy.mash"))
    for element in elements:
        print(element)

    # Correct parsing.
    assert len(elements) == 7
    assert elements[0].address.lineno == 1
    assert elements[1].address.lineno == 4
    assert elements[2].address.lineno == 4
    assert elements[3].address.lineno == 7
    assert elements[4].address.lineno == 7
    assert elements[5].address.lineno == 9
    assert elements[6].address.lineno == 9

    # No exceptions from __str__.
    elements[0].__str__()

def test_element_seq_from_string2():
    # When a token is at the very start, nothing breaks.
    element_seq_from_string('[[[ a ]]]', 'dummy.mash')

def test_element_tree_from_string1():
    # Basic parsing works as expected.
    code = """
      a
      b
      [[[
          c
          d
      |||
          e
      ]]]
      f
      g
    """
    root = tree_from_string(code, 'dummy.mash')
    print(root.as_indented_string())
    assert len(root.children) == 3
    assert isinstance(root.children[0], TextLeaf)
    assert isinstance(root.children[1], Frame)
    assert len(root.children[1].children) == 2
    assert isinstance(root.children[1].children[0], CodeLeaf)
    assert root.children[1].children[0].address.lineno == 4
    assert isinstance(root.children[1].children[1], TextLeaf)

def test_element_tree_from_string2():
    # Extra separators generate an error, with with file name and line in error
    # message.
    with pytest.raises(ValueError) as exc_info:
        tree_from_string('[[[ a \n ||| b \n ||| c ]]]', 'dummy.mash')
    assert 'dummy.mash, line 3' in str(exc_info)

def test_element_tree_from_string3():
    # Missing closing delimiters given an error where the frame started.
    with pytest.raises(ValueError) as exc_info:
        tree_from_string('1  \n 2 \n 3 [[[ a \n b \n c \n d', 'dummy.mash')
    exception = exc_info._excinfo[1]
    assert exception.filename == 'dummy.mash'
    assert exception.lineno == 3

def test_element_tree_from_string4():
    # Extra closing delimiters give an error at the end.
    with pytest.raises(ValueError):
        tree_from_string('[[[ \n a \n ||| \n b \n ]]] \n c \n ]]]', 'dummy.mash')

def test_dash_c():
    # Running with -c removes the archives.
    with temporary_current_directory():
        os.mkdir('.mash')
        os.mkdir('.mash-archive')
        engage(['mash3', '-c'])
        assert not os.path.exists('.mash')
        assert not os.path.exists('.mash-archive')

def test_stdin_input():
    # Nothing explodes when we give (empty) stdin as the input.
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
    assert stats == Stats(2, 0, 0)

def test_codeleaf_execute1():
    # Simple code executes.
    CodeLeaf(Address('dummy.mash', 1, 1), None, "print('hello')").execute({})

def test_codeleaf_execute2():
    # Broken code raises a syntax error.
    with pytest.raises(SyntaxError):
        CodeLeaf(Address('dummy.mash', 1, 1), None, "print 'hello'").execute({})

def test_codeleaf_execute3():
    # Correct line number.
    with pytest.raises(Exception) as exc_info:
        CodeLeaf(Address('dummy.mash', 5, 1),
                 None,
                 "  \n\n\n  raise ValueError('sadness')").execute({})

    formatted_tb = '\n'.join(traceback.format_tb(exc_info._excinfo[2]))
    print(formatted_tb)
    assert '"dummy.mash", line 8' in formatted_tb

def test_textleaf_execute1():
    # Simple.
    TextLeaf(Address('dummy.mash', 1, 1), None, "print('hello')").execute({})

def test_textleaf_execute2():
    # Text leaves don't execute their content as code -- no exception here.
    TextLeaf(Address('dummy.mash', 1, 1), None, "print 'hello'").execute({})

def test_frame_execute():
    # Something simple.
    root = tree_from_string('A [[[ print("B") ]]] C', 'dummy.mash')
    root.execute({})

def test_frame_execute2():
    # Check recursive execution, normal case.
    root = tree_from_string('[[[ print("B") ||| [[[ print("C") ||| D ]]] ]]]', 'dummy.mash')
    root.execute({})


def test_frame_execute3():
    # Check recursive execution, failing.
    root = tree_from_string('[[[ print("B") ||| [[[ print C ||| D ]]] ]]]', 'dummy.mash')
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
    with engage_string(code):
        pass

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
    root = tree_from_string(code, 'dummy.mash')
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
    root = tree_from_string(code, '')
    with pytest.raises(RestartRequest):
        root.execute(default_variables())

def test_restart_request2():
    # RestartRequests are correctly handled.
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
    with engage_string(code):
        assert os.path.exists('1')
        assert os.path.exists('2')

def test_include():
    # Included files are found and imported.
    included = """
        [[[
            def foo():
                return "bar"
        ]]]
    """

    code = """
        [[[
            [[[ include included-dummy.mash ]]]
            foo()
        ]]]
    """

    with engage_string(code, files={ 'included-dummy.mash': included }):
        pass

def test_mashlib_shell1():
    # Shell commands run correctly.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            shell('ls /dev')
        ]]]
    """
    with engage_string(code):
        pass

def test_mashlib_shell2():
    # Broken commands raise exceptions.  Those exceptions are caught and
    # handled gracefully.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            result = shell('ls foobar')
        ]]]
    """
    root = tree_from_string(code, 'dummy.mash')

    with pytest.raises(subprocess.CalledProcessError):
        run_tree(root)

    with engage_string(code):
        pass

def test_mashlib_shell3():
    # Multiple broken commands raise an ExecptionGroup, which is caught and
    # reported gracefully.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            result = shell('ls foobar')
            result = shell('ls baz')
        ]]]
    """
    root = tree_from_string(code, 'dummy.mash')

    with pytest.raises(ExceptionGroup):
        run_tree(root)

    with engage_string(code):
        pass

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
    with engage_string(code):
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
    code = """
        [[[
            def at_end():
                raise ValueError
        ]]]
    """
    root = tree_from_string(code, 'dummy.mash')
    with pytest.raises(ValueError):
        run_tree(root)

def test_exception_address():
    # Exceptions in included files refer correctly to their source.
    code = """
        [[[ include mashlib.mash ]]]
        [[[ check_for_executable('foobar') ]]]
    """
    root = tree_from_string(code, 'dummy.mash')
    print(root.as_indented_string())
    with pytest.raises(Exception) as exc_info:
        run_tree(root)
    raise exc_info._excinfo[1]

if __name__ == '__main__':  #pragma: nocover
    run_tests_from_pattern()
