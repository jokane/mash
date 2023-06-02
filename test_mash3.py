#!/usr/bin/env python3
# pylint: disable=missing-function-docstring
# pylint: disable=wildcard-import
# pylint: disable=unused-wildcard-import
# pylint: disable=protected-access
# pylint: disable=invalid-name


"""Tests for mash and mashlib.  Usually run via the check script, but can be
used from the command line as well to run single tests."""

import contextlib
import subprocess
import sys
import tempfile
import traceback
import os

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

def run_tests_from_pattern(pattern): #pragma nocover
    # Execute all tests whose names containing the pattern.
    pattern = ''
    try:
        pattern = sys.argv[1]
    except IndexError:
        pass

    ok = False
    for name, thing in list(globals().items()):
        if 'test_' in name and pattern in name:
            print('-'*80)
            print(name)
            print('-'*80)
            x = start_in_temp_directory()
            next(x)
            thing()
            try:
                next(x)
            except StopIteration:
                pass
            print()
            ok = True
    if not ok:
        raise ValueError(f'No tests matched pattern {pattern}.')

def engage_string(code):
    filename = 'dummy.mash'
    with open(filename, 'w', encoding='utf-8') as output_file:
        print(code, file=output_file)

    with temporarily_changed_directory('.'):
        engage(['mash3', filename])

@pytest.fixture(autouse=True)
def fixture_start_in_temp_directory():
    yield from start_in_temp_directory()

def start_in_temp_directory():
    """All tests run with a "clean" temporary current directory, containing (a
    symbolic link to) mashlib, and nothing else."""

    test_script_dir = os.path.dirname(os.path.abspath(__file__))
    linked_files = ['mashlib.mash']
    linked_files = map(lambda x: os.path.join(test_script_dir, x), linked_files)

    with temporary_current_directory(linked_files=linked_files):
        yield

################################################################################

def test_unindent():
    code = "    print('hello')\n    print('world')"
    assert len(code) - len(unindent(code)) == 8


# A representative chunk of mash code used in several tests below:
code_to_parse = """
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
        [[[   ]]]
"""

def test_token_seq_from_string():
    # Tokens are extracted from a string correctly.
    tokens = list(token_seq_from_string(code_to_parse))
    for token in tokens:
        print(token.__repr__())

    # Spot check the correctness.
    assert len(tokens) == 29
    assert tokens[0] == Token.NEWLINE
    assert isinstance(tokens[1], str)
    assert tokens[-2] == Token.CLOSE
    assert tokens[-1] == Token.NEWLINE

def test_token_seq_from_string2():
    # When a token is at the very start, nothing breaks.
    list(token_seq_from_string('[[[ a ]]]'))

def test_element_seq_from_token_seq():
    tokens = [
        "abc",
        Token.NEWLINE,
        "de",
        Token.SEPARATOR
    ]

    elements = list(element_seq_from_token_seq(tokens, 'dummy.mash', 5))
    for element in elements:
        print(element)

    # Spot check the correctness.
    assert len(tokens) == len(elements)
    assert elements[0].address.lineno == 5
    assert elements[0].address.offset == 1
    assert elements[1].address.lineno == 5
    assert elements[1].address.offset == 4
    assert elements[3].address.lineno == 6
    assert elements[3].address.offset == 3

def test_compress_element_seq():
    elements = element_seq_from_string(code_to_parse, "dummy.mash")
    elements = compress_element_seq(elements)
    elements = list(elements)
    for element in elements:
        print(element)

    # Correct parsing.
    assert len(elements) == 10

    # Correct tracking line numbers.
    assert elements[0].address.lineno == 1 # a b
    assert elements[1].address.lineno == 4 # OPEN
    assert elements[2].address.lineno == 4 # c d
    assert elements[3].address.lineno == 7 # SEPARATOR
    assert elements[4].address.lineno == 7 # e
    assert elements[5].address.lineno == 9 # CLOSE
    assert elements[6].address.lineno == 9 # f g
    assert elements[7].address.lineno == 12 # OPEN
    assert elements[7].address.lineno == 12 # space
    assert elements[8].address.lineno == 12 # CLOSE

    assert elements[0].address.offset == 1 # a b
    assert elements[1].address.offset == 9 # OPEN
    assert elements[2].address.offset == 12 # c d

    # No exceptions from __str__.
    elements[0].__str__()

def test_element_tree_from_string1():
    # Basic parsing works as expected.
    root = tree_from_string(code_to_parse, 'dummy.mash')
    print(root.as_indented_string())
    assert len(root.children) == 4
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
    exception = exc_info._excinfo[1]
    assert exception.filename == 'dummy.mash'
    assert exception.lineno == 3

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

def test_frame_node_long_contents():
    # Long node contents are trimmed for viewing.
    node = TextLeaf(Address('dummy.mash', 1, 1), None, 1000*'-')
    ais = node.as_indented_string()
    print(ais)
    assert len(ais) < 100

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

def test_frame_stats():
    root = tree_from_string('[[[ include mashlib.mash ]]] a\nb[[[print()|||d]]]e\nf', 'dummy.mash')
    print(root.as_indented_string())
    _, stats = run_tree(root)
    print(stats)

    # 5 frames:
    # - top level of main document
    # - frame with include directive
    # - top frame of mashlib
    # - big frame spanning most of mashlib
    # - short one in the main document
    assert stats == Stats(5, 2, 1)

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
    engage_string(code)

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
    engage_string(code)
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
    with open('included-dummy.mash', 'w', encoding='utf-8') as output:
        print(included, file=output)

    engage_string(code)

def test_mashlib_shell1():
    # Shell commands run correctly.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            shell('ls /dev')
        ]]]
    """
    engage_string(code)

def test_mashlib_shell2():
    # Broken commands raise exceptions.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            shell('ls foobar')
        ]]]
    """
    root = tree_from_string(code, 'dummy.mash')
    with pytest.raises(subprocess.CalledProcessError):
        run_tree(root)

def test_mashlib_shell3():
    # Those exceptions are caught and handled gracefully.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            shell('ls foobar')
        ]]]
    """
    engage_string(code)

def test_mashlib_shell4():
    # Multiple broken commands raise an ExecptionGroup.
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

def test_mashlib_shell5():
    # ExceptionGroups are caught and reported gracefully.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            result = shell('ls foobar')
            result = shell('ls baz')
        ]]]
    """
    engage_string(code)

def test_mashlib_shell6():
    # Missing executables are noticed.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            shell('foobar')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_mashlib_shell_wait():
    # Events are set.  Using a string for provides is handled as a single
    # thing, instead of iterating over characters.  Calling wait_for allows
    # the process to complete.
    code = """
        [[[
            [[[ include mashlib.mash ]]]
            import os
            shell('sleep 1; ls > files.txt', provides='files.txt')
            assert not os.path.isfile('files.txt')
            wait_for('files.txt')
            assert os.path.isfile('files.txt')
        ]]]
    """
    variables = {}
    root = tree_from_string(code, 'dummy.mash')
    root.execute(variables)
    assert len(list(variables['job_resource_events'])) == 1
    assert 'files.txt' in variables['job_resource_events']

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
    engage_string(code)

    with open('.mash/nums', encoding='utf-8') as numbers_file:
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

def test_build_dir_created():
    code = """
        [[[ include mashlib.mash ]]]
        [[[ shell('touch hello') ]]] 
        [[[ shell('mkdir world') ]]] 
    """

    # The first run creates the build directory but not the archive.
    engage_string(code)
    assert os.path.isdir('.mash')
    assert os.path.exists('.mash/hello')
    assert os.path.isdir('.mash/world')
    assert not os.path.exists('.mash-archive')

    # A second run creates the archive and moves things into it.
    engage_string(code)
    assert os.path.isdir('.mash-archive')
    assert os.path.exists('.mash-archive/hello')
    assert os.path.isdir('.mash-archive/world')

    # A third run will need to rmtree in the archive.
    engage_string(code)

def test_save1():
    # File is created.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            self.content = self.content.strip()
            save('hello.txt')
        |||
            hello, world!
        ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/hello.txt')
    os.system('cat .mash/hello.txt')

    # Second time through, the file should be found in the archive instead.
    engage_string(code)

def test_save2():
    # Binary mode and explicitly specified contents.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            save('hello.png', contents=b'abcdefg\x45')
        ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/hello.png')
    os.system('cat .mash/hello.png')

def test_save3():
    # Same file errors are caught and ignored.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            self.content = self.content.strip()
            os.mkdir(archive_directory)
            save(archive_directory + '/hello.txt')
            save(archive_directory + '/hello.txt')
        |||
            hello, world!
        ]]]
    """
    engage_string(code)

def test_recall1():
    # Recalled files that exist are copied in.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch {archive_directory}/test.txt')
            assert recall('test.txt') is None
        ]]]
    """
    engage_string(code)

def test_recall2():
    # Recalled files that do not exist are not copied in.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            assert recall('test.txt') == 'test.txt'
        ]]]
    """
    engage_string(code)

def test_recall3():
    # Missing dependencies are noticed and complained about.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch {archive_directory}/test.txt')
            recall('test.txt', 'dep.txt')
        ]]]
    """
    with pytest.raises(FileNotFoundError):
        engage_string(code)

def test_recall4():
    # Target older than dependencies.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch -d 1960-10-13 {archive_directory}/test.txt')
            os.system(f'touch -d 1960-10-14 dep.txt')
            assert recall('test.txt', 'dep.txt') == 'test.txt'
        ]]]
    """
    engage_string(code)

def test_recall5():
    # Target newer than dependencies.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch -d 1960-10-14 {archive_directory}/test.txt')
            os.system(f'touch -d 1960-10-13 dep.txt')
            assert recall('test.txt', 'dep.txt') is None
        ]]]
    """
    engage_string(code)

def test_recall6():
    # Target is a directory.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.mkdir(archive_directory + '/test')
            os.system(f'touch -d 1960-10-13 {archive_directory}/test')
            os.system(f'touch -d 1960-10-13 dep.txt')
            assert recall('test') is None
        ]]]
    """
    engage_string(code)

def test_recall7():
    # Target is a directory that already exists.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.mkdir(archive_directory + '/test')
            os.mkdir('test')
            os.system(f'touch -d 1960-10-13 {archive_directory}/test')
            os.system(f'touch -d 1960-10-13 dep.txt')
            assert recall('test') is None
        ]]]
    """
    engage_string(code)

def test_recall8():
    # In-progress dependencies are waited for.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            shell('sleep 0.3; echo hello > 1.txt', provides='1.txt')
            shell('sleep 0.1; echo world > 2.txt', provides='2.txt')

            if x := recall('3.txt', '1.txt', '2.txt'):
                shell('cat 1.txt 2.txt > 3.txt', provides=x)

            wait_for('3.txt')
            os.system('cat 3.txt')
        ]]]
    """
    engage_string(code)

def test_keep1():
    # Keeping a file.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.system('touch 1.txt')
            keep('1.txt')
        ]]]
    """
    engage_string(code)


def test_keep2():
    # Error from relative path for keep_directory.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            keep_directory = 'keep'
            os.system('touch 1.txt')
            keep('1.txt')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_keep3():
    # Create keep directory if needed.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            keep_directory = os.path.join(original_directory, 'keep')
            os.system('touch 1.txt')
            keep('1.txt')
        ]]]
    """
    engage_string(code)
    assert os.path.exists('keep/1.txt')

def test_keep4():
    # Keep a directory, replacing an existing version if needed.
    os.mkdir('stuff')
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir('stuff')
            os.system('touch stuff/1.txt')
            keep('stuff')
        ]]]
    """
    engage_string(code)
    assert os.path.isdir('stuff')
    assert os.path.isfile('stuff/1.txt')

def test_keep5():
    # Try and fail to keep something that does not exist.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            keep('stuff')
        ]]]
    """
    with pytest.raises(FileNotFoundError):
        engage_string(code)

def test_keep6():
    # If we somehow manage to get something that's neither file nor directory,
    # fail.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            keep('/dev/null')
        ]]]
    """
    with pytest.raises(NotImplementedError):
        engage_string(code)

def test_read():
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            save('hello.txt')
        |||
            hello world
        ]]]

        [[[
            read('hello.txt')
            save('hello_again.txt')
            keep('hello_again.txt')
        ]]]
    """
    engage_string(code)
    with open('hello_again.txt', encoding='utf-8') as it:
        assert it.read().strip() == 'hello world'

def test_imprt1():
    # Imported files are actually imported to the build directory.
    os.system('echo hello > hello.txt')
    code = """
        [[[ include mashlib.mash ]]]
        [[[ imprt('hello.txt') ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/hello.txt')

def test_imprt2():
    # Fail if we try to rename-on-import more than one file.
    code = """
        [[[ include mashlib.mash ]]]
        [[[ imprt('1', '2', target='3') ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_imprt3():
    # Importing something that doesn't exist might fail or might be ignored.
    code = """
        [[[ include mashlib.mash ]]]
        [[[ imprt('1', conditional=%s) ]]]
    """
    engage_string(code % 'True') # pylint:disable=consider-using-f-string

    with pytest.raises(FileNotFoundError):
        engage_string(code % 'False') # pylint:disable=consider-using-f-string

def test_imprt4():
    # Rename-on-import happens correctly.
    os.system('echo hello > 1')
    code = """
        [[[ include mashlib.mash ]]]
        [[[ imprt('1', target='2') ]]]
    """
    engage_string(code)
    assert os.path.exists('.mash/2')
    assert not os.path.exists('.mash/1')

def test_imprt5():
    # Return None if there's nothing to import.
    code = """
        [[[ include mashlib.mash ]]]
        [[[ 
            x = imprt()
            assert x is None
        ]]]
    """
    engage_string(code)

def test_anonymous_name():
    # Different content gets a different anonymous name.
    code = """
        [[[ include mashlib.mash ]]]
        [[[ 
            x = anonymous_name()
        |||
            a b c
        ]]] 
        [[[ 
            y = anonymous_name()
        |||
            d e f
        ]]]
        [[[ 
            z = anonymous_name()
        |||
            d e f
        ]]]

        [[[
            print(x)
            print(y)
            print(z)
            assert x != y
            assert y == z
        ]]]
    """
    engage_string(code)

if __name__ == '__main__':  #pragma: nocover
    run_tests_from_pattern(sys.argv[1])
