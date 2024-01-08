#!/usr/bin/env python3
# pylint: disable=missing-function-docstring
# pylint: disable=wildcard-import
# pylint: disable=unused-wildcard-import
# pylint: disable=protected-access
# pylint: disable=invalid-name
# pylint: disable=too-many-lines


"""Tests for mash and mashlib.  Usually run via the check script, but can be
used from the command line as well to run single tests."""

import contextlib
import subprocess
import sys
import tempfile
import traceback
import os

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

def run_tests_from_pattern(pattern): #pragma nocover
    # Execute all tests whose names contain the pattern.
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
        stats = engage(['mash3', filename])

    return stats

@pytest.fixture(autouse=True)
def fixture_start_in_temp_directory():
    yield from start_in_temp_directory()

@pytest.fixture(autouse=True)
def fixture_reset_node_number():
    FrameTreeNode.next_node_num = 0
    yield

def start_in_temp_directory():
    """All tests run with a "clean" temporary current directory, containing
    (symbolic links to) the standard library, and nothing else."""

    test_script_dir = os.path.dirname(os.path.abspath(__file__))
    linked_files = ['mashlib.mash', 'latex.mash']
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
    assert len(ais) < 500

def test_all_nodes():
    # all_nodes() traverses the whole tree.
    root = tree_from_string(code_to_parse, 'dummy.mash')
    print(root.as_indented_string())
    for i, node in enumerate(root.all_nodes()):
        print(i, node.as_indented_string())
    assert len(list(root.all_nodes())) == 8, len(list(root.all_nodes()))

def test_all_constraints():
    # Correctly collect all constraints from the whole tree.
    root = tree_from_string(code_to_parse, 'dummy.mash')
    constraints = list(root.all_constraints())
    assert len(constraints) == 26



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


def test_codeleaf_execute1():
    # Simple code executes.
    node = CodeLeaf(Address('dummy.mash', 1, 1), None, "print('hello')")
    node.start({})
    node.finish({})

def test_codeleaf_execute2():
    # Broken code raises a syntax error.
    with pytest.raises(SyntaxError):
        node = CodeLeaf(Address('dummy.mash', 1, 1), None, "print 'hello'")
        node.start({})

def test_codeleaf_execute3():
    # Correct line number.
    with pytest.raises(Exception) as exc_info:
        CodeLeaf(Address('dummy.mash', 5, 1),
                 None,
                 "  \n\n\n  raise ValueError('sadness')").start({})

    formatted_tb = '\n'.join(traceback.format_tb(exc_info._excinfo[2]))
    print(formatted_tb)
    assert '"dummy.mash", line 8' in formatted_tb

def test_textleaf_start1():
    # Text leaves execute without complaining.
    TextLeaf(Address('dummy.mash', 1, 1), None, "print('hello')").start({})

def test_textleaf_start2():
    # Text leaves don't execute their content as code -- no exception here.
    TextLeaf(Address('dummy.mash', 1, 1), None, "print 'hello'").start({})

def test_run_tree1():
    # Code nested frames is executed without a problem.
    root = tree_from_string('[[[ print("B") ||| [[[ print("C") ||| D ]]] ]]]', 'dummy.mash')
    run_tree(root)

def test_run_tree2():
    # Bad Python raises a syntax error.
    root = tree_from_string('[[[ print("B") ||| [[[ print C ||| D ]]] ]]]', 'dummy.mash')
    with pytest.raises(SyntaxError):
        run_tree(root)

def test_vars1():
    # Variables from child frames are visible to parents.
    code = r"""
        [[[
            print(x)
            [[[ x = 3 ]]]
        ]]]
    """
    engage_string(code)

def test_vars2():
    # Vars from later children replace vars from earlier children.
    code = r"""
        [[[
            [[[
                x = 3
            ]]]
            [[[
                x = 4
            ]]]
            [[[
                assert x == 4
            ]]]
        ]]]
    """
    engage_string(code)

def test_restart_request1():
    # RestartRequest is visible from mash code.
    code = r"""
        [[[
            raise RestartRequest
        ]]]
    """
    root = tree_from_string(code, '')
    with pytest.raises(RestartRequest):
        run_tree(root)

def test_restart_request2():
    # RestartRequests are correctly handled.
    code = r"""
        [[[
            # This code should run twice.
            # - The first time, it creates a file called 1 and requests a restart.
            # - This triggers the restart mechanism, to re-run the thing.
            # - The second time, it creates a file called 2.
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
    # Included files are found and imported if they exist, or complained about
    # if they don't.
    included = """
        [[[
            def foo():
                return "bar"
        ]]]
    """

    code = r"""
        [[[
            [[[ include included-dummy.mash ]]]
            foo()
        ]]]
    """

    with pytest.raises(FileNotFoundError):
        engage_string(code)

    with open('included-dummy.mash', 'w', encoding='utf-8') as output:
        print(included, file=output)

    engage_string(code)

def test_mashlib_require_versions1():
    # Mash version is passed in correctly.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            require_versions(mash='2.0')
        ]]]
    """
    engage_string(code)

def test_mashlib_require_versions2():
    # Complain about versions that are too old.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            require_versions(mash='2.0', mashlib='3.1')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_mashlib_require_versions3():
    # Don't complain about versions that are not too old.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            require_versions(mash='2.0', mashlib='3.0')
        ]]]
    """
    engage_string(code)

def test_mashlib_require_versions4():
    # Complain when the thing is missing entirely.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            require_versions(foo='3.0')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_mashlib_shell1():
    # Shell commands run correctly.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            x = shell('ls /dev')
            assert isinstance(x, subprocess.CompletedProcess)
        ]]]
    """
    engage_string(code)

def test_mashlib_shell2():
    # Broken commands raise exceptions.
    code = r"""
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
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            shell('ls foobar')
        ]]]
    """
    engage_string(code)

def test_mashlib_shell5():
    # ExceptionGroups are caught and reported gracefully.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            result = shell('ls foobar')
            result = shell('ls baz')
        ]]]
    """
    engage_string(code)

def test_mashlib_shell6():
    # Missing executables are noticed.
    code = r"""
        [[[
            [[[ include mashlib.mash ]]]
            shell('foobar')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)





def test_at_end():
    # Call to at_end() after full tree is executed.
    code = r"""
        [[[
            def at_end():
                raise ValueError
        ]]]
    """
    root = tree_from_string(code, 'dummy.mash')
    with pytest.raises(ValueError):
        run_tree(root)

def test_build_dir_created():
    code = r"""
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
    code = r"""
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
    assert os.stat('.mash/hello.txt').st_size > 0
    os.system('cat .mash/hello.txt')

    # Whole thing again for coverage purposes.  This second time through, the
    # file should be found in the archive instead.
    engage_string(code)

def test_save2():
    # Binary mode and explicitly specified contents.
    code = r"""
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
    code = r"""
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
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch {archive_directory}/test.txt')
            assert recall('test.txt')
        ]]]
    """
    engage_string(code)

def test_recall2():
    # Recalled files that do not exist are not copied in.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            recall('test.txt')
        ]]]
    """
    engage_string(code)
    assert not os.path.exists('test.txt')

def test_recall3():
    # Missing dependencies are noticed and complained about.
    code = r"""
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
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch -d 1960-10-13 {archive_directory}/test.txt')
            os.system(f'touch -d 1960-10-14 dep.txt')
            assert not recall('test.txt', 'dep.txt')
        ]]]
    """
    engage_string(code)

def test_recall5():
    # Target newer than dependencies.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.system(f'touch -d 1960-10-14 {archive_directory}/test.txt')
            os.system(f'touch -d 1960-10-13 dep.txt')
            assert recall('test.txt', 'dep.txt')
        ]]]
    """
    engage_string(code)

def test_recall6():
    # Target is a directory.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.mkdir(archive_directory + '/test')
            os.system(f'touch -d 1960-10-13 {archive_directory}/test')
            os.system(f'touch -d 1960-10-14 dep.txt')
            assert recall('test')
        ]]]
    """
    engage_string(code)

def test_recall7():
    # Target is a directory that already exists.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            os.mkdir(archive_directory)
            os.mkdir(archive_directory + '/test')
            os.mkdir('test')
            os.system(f'touch -d 1960-10-13 {archive_directory}/test')
            os.system(f'touch -d 1960-10-13 dep.txt')
            assert recall('test')
        ]]]
    """
    engage_string(code)

def test_push():
    # Pushing frame contents.
    code = """
        [[[ include mashlib.mash ]]]
        [[[
            print(f'-->{self.content}<--')
            print(f'-->{type(self)}<--')
            print(f'-->{id(self)}<--')
            assert 'abc' in self.content
        |||
            [[[ push() ||| abc ]]]
        ]]]
    """
    engage_string(code)


def test_keep1():
    # Keeping a file.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            os.system('touch 1.txt')
            keep('1.txt')
        ]]]
    """
    engage_string(code)


def test_keep2():
    # Error from relative path for keep_directory.
    code = r"""
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
    code = r"""
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
    code = r"""
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
    code = r"""
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
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            keep('/dev/null')
        ]]]
    """
    with pytest.raises(NotImplementedError):
        engage_string(code)

def test_read():
    code = r"""
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
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[ imprt('hello.txt') ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/hello.txt')

def test_imprt2():
    # Fail if we try to rename-on-import more than one file.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[ imprt('1', '2', target='3') ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_imprt3():
    # Importing something that doesn't exist might fail or might be ignored.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[ imprt('1', conditional=%s) ]]]
    """
    engage_string(code % 'True') # pylint:disable=consider-using-f-string

    with pytest.raises(FileNotFoundError):
        engage_string(code % 'False') # pylint:disable=consider-using-f-string

def test_imprt4():
    # Rename-on-import happens correctly.
    os.system('echo hello > 1')
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[ imprt('1', target='2') ]]]
    """
    engage_string(code)
    assert os.path.exists('.mash/2')
    assert not os.path.exists('.mash/1')

def test_imprt5():
    # Return None if there's nothing to import.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            x = imprt()
            assert x is None
        ]]]
    """
    engage_string(code)

def test_anonymous_name():
    # Different content gets a different anonymous name.
    code = r"""
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

def test_shell_filter():
    # Shell filter runs the command and grabs the result.
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            shell_filter('rev')
            print(self.content)
            assert 'olleh' in self.content
        |||
            hello world
        ]]]
    """
    engage_string(code)

def test_mashlib_root_node():
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            [[[
            ]]]
            [[[
                root = root_node()
                assert root.parent is None
                assert root is not self
            ]]]
        ]]]
    """
    engage_string(code)


def test_mashlib_root_name():
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            [[[
                assert root_name() == 'dummy'
            ]]]
        ]]]
    """
    engage_string(code)

def test_before_code_hook():
    # @@ imports work in both code and text.
    os.system('touch 1')
    os.system('touch 2')

    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            x = '@@1'
            assert '@' not in x, x
            assert '@' not in self.content, self.content
        |||
            @@2
        ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/1')
    assert os.path.isfile('.mash/2')

def test_after_code_hook():
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            def after_code_hook(leaf):
                global x
                x = 2
        ]]]

        [[[
            assert x == 2
        ]]]
    """
    engage_string(code)

def test_backdoor_comment():
    code = r"""
        [[[
          assert 'ignore' not in self.content
          |||
          [[[ ||| ignore me ]]]
        ]]]
    """
    engage_string(code)

def test_spell_check1():
    """Spell check with no changes."""
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[ spell_check(command='echo') ]]]
    """
    engage_string(code)

def test_spell_check2():
    """Spell check that changes a file."""
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[ spell_check(command=f'echo xxx > {original_directory}/dummy.mash; echo') ]]]
    """
    engage_string(code)

def test_ext():
    code = r"""
        [[[ include mashlib.mash ]]]
        [[[
            assert ext('paper.tex', 'pdf') == 'paper.pdf'
        ]]]
    """
    engage_string(code)


def test_latex1():
    # Complain if a compiler is specified.
    code = r"""
        [[[ include latex.mash ]]]
        [[[
            latex(name='paper', compiler='latex')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_latex2():
    # LaTeX documents with various features compile.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ save('main.bib') |||
            @article{xyz,
                author = {A},
                title = {B},
                journal = {C},
                year = {1960}
            }
        ]]]
        [[[ latex(name='paper') |||
            \documentclass{article}
            \usepackage{graphicx}
            \begin{document}
                hello, world!
                \cite{xyz}
                [[[ dot() |||
                    graph{
                        A -- B
                    }
                ]]]
                \bibliographystyle{plain}
                \bibliography{main}
            \end{document}
        ]]]
    """
    engage_string(code)
    assert os.path.isfile('paper.pdf')

def test_latex():
    # LaTeX errors are complained about.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex(name='paper') |||
            \notactuallylatexcode
        ]]]
    """
    with pytest.raises(subprocess.CalledProcessError):
        root = tree_from_string(code, 'dummy.mash')
        run_tree(root)

def test_latex4():
    # LaTeX callbacks are called.
    code = r"""
        [[[ include latex.mash ]]]
        [[[
            called = False
            def cb():
                global called
                called = True
        ]]]
        [[[ latex(name='paper', callback=cb) |||
            \documentclass{article}
            \begin{document}
                hi
            \end{document}
        ]]]
        [[[
            assert called
        ]]]
    """
    engage_string(code)

def test_latex5():
    # LaTeX document with an index is compiled correctly.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex(name='paper') |||
            \documentclass{article}
            \usepackage{makeidx}
            \makeindex
            \begin{document}
                hi
                \index{hi}
                \printindex
            \end{document}
        ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/paper.idx')
    assert os.path.isfile('.mash/paper.ind')
    assert os.path.isfile('.mash/paper.ilg')

def test_latex6():
    # LaTeX respects max_compiles argument.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex(name='paper', max_compiles=1) |||
            \documentclass{article}
            \begin{document}
                hi
            \end{document}
        ]]]
    """
    engage_string(code)

def test_latex7():
    # LaTeX via dvi gives a PDF.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex_mode = 'latex' ]]]
        [[[ latex(name='paper') |||
            \documentclass{article}
            \begin{document}
                hi
            \end{document}
        ]]]
    """
    engage_string(code)
    assert os.path.isfile('.mash/paper.dvi')
    assert os.path.isfile('.mash/paper.pdf')

def test_latex8():
    # Strict checking finds reference problems.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex(name='paper', strict=True) |||
            \documentclass{article}
            \begin{document}
                \ref{missing}
            \end{document}
        ]]]
    """
    with pytest.raises(Exception):
        root = tree_from_string(code, 'dummy.mash')
        run_tree(root)

def test_latex9():
    # Strict checking with no problems does not complain.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex(name='paper', strict=True) |||
            \documentclass{article}
            \begin{document}
                hi
            \end{document}
        ]]]
    """
    engage_string(code)


def test_dot1():
    # Complain about dot on an empty frame.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ dot() ]]]
    """
    with pytest.raises(ValueError):
        root = tree_from_string(code, 'dummy.mash')
        run_tree(root)

def test_dot2():
    # Compile dot with latex_mode="latex".
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex_mode = 'latex' ]]]
        [[[ latex(name='paper') |||
            \documentclass{article}
            \usepackage{graphicx}
            \begin{document}
                [[[ dot() |||
                    graph{
                        A -- B
                    }
                ]]]
            \end{document}
        ]]]
    """
    engage_string(code)

def test_dot3():
    # Compile dot via xfig.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex(name='paper') |||
            \documentclass{article}
            \usepackage{graphicx}
            \usepackage{color}
            \begin{document}
                [[[ dot(via_xfig=True) |||
                    graph{
                        A -- B
                    }
                ]]]
            \end{document}
        ]]]
    """
    engage_string(code)

def test_xfig1():
    # Complain about both including and excluding depths.
    code = r"""
        [[[ include latex.mash ]]]
        [[[
            xfig('irrelevant.fig', include_depths=[1,2,3], exclude_depths=[4,5,6])
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_xfig2():
    # Locate dependendies in xfig.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ unindent(); self.content=self.content.strip(); save('picture.fig') |||
            #FIG 3.2  Produced by xfig version 3.2.5b
            Landscape
            Center
            Inches
            Letter
            100.00
            Single
            -2
            1200 2
            2 5 0 1 0 -1 45 -1 20 0.000 0 0 -1 0 0 5
              0 image.png
               780 -1071 920 -1071 920 -931 780 -931 780 -1071
        ]]]
        [[[
            xfig('picture.fig')
        ]]]
    """
    os.system('touch image.png')
    engage_string(code)

def test_xfig3():
    # No complaints from xfig with include or exclude lists
    # nor with latex_mode='latex'
    code = r"""
        [[[ include latex.mash ]]]
        [[[ unindent(); self.content=self.content.strip(); save('box.fig') |||
            #FIG 3.2  Produced by xfig version 3.2.5b
            Landscape
            Center
            Inches
            Letter
            100.00
            Single
            -2
            1200 2
            2 2 0 1 0 7 50 -1 -1 0.000 0 0 -1 0 0 5
               4590 765 8685 765 8685 3285 4590 3285 4590 765
        ]]]
        [[[
            latex_mode = 'latex'
            xfig('box.fig', include_depths=50)
            xfig('box.fig', include_depths=[50])
            xfig('box.fig', exclude_depths=[50])
        ]]]
    """
    engage_string(code)

def test_xfig4():
    # Complain about includegraphics args in direct mode.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ unindent(); self.content=self.content.strip(); save('box.fig') |||
            #FIG 3.2  Produced by xfig version 3.2.5b
            Landscape
            Center
            Inches
            Letter
            100.00
            Single
            -2
            1200 2
            2 2 0 1 0 7 50 -1 -1 0.000 0 0 -1 0 0 5
               4590 765 8685 765 8685 3285 4590 3285 4590 765
        ]]]
        [[[
            xfig('box.fig', direct=True, args='width=2in')
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_xfig5():
    # No complaints from xfig in indirect mode.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ unindent(); self.content=self.content.strip(); save('box.fig') |||
            #FIG 3.2  Produced by xfig version 3.2.5b
            Landscape
            Center
            Inches
            Letter
            100.00
            Single
            -2
            1200 2
            2 2 0 1 0 7 50 -1 -1 0.000 0 0 -1 0 0 5
               4590 765 8685 765 8685 3285 4590 3285 4590 765
        ]]]
        [[[
            xfig('box.fig', direct=False, args='width=2in')
        ]]]
    """
    engage_string(code)

def test_asy1():
    # Complain about calling asy() with no input.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ asy() ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_asy2():
    # No complaints from normal asy().
    code = r"""
        [[[ include latex.mash ]]]
        [[[ save('test.asy') |||
            draw((3,5)--(7,5));
        ]]]
        [[[ asy('test.asy') ]]]
    """
    engage_string(code)

def test_asy3():
    # Complain about asy() with inconsistent inputs.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ asy('test.asy') |||
            draw((3,5)--(7,5));
        ]]]
    """
    with pytest.raises(ValueError):
        engage_string(code)

def test_asy4():
    # No complaints from asy() with latex_mode == 'latex'.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex_mode = 'latex' ]]]
        [[[ asy() |||
            draw((3,5)--(7,5));
        ]]]
    """
    engage_string(code)

def test_asy5():
    # Find asymptote imports correctly.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex_mode = 'latex' ]]]
        [[[ asy() |||
            import graph;
            draw((3,5)--(7,5));
        ]]]
    """
    engage_string(code)

def test_image1():
    # Insert an image normally, with no conversion.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ image('irrelevant.pdf') ]]]
    """
    engage_string(code)

def test_image2():
    # Insert an image with latex_mode='latex' and normal conversion.
    code = r"""
        [[[ include latex.mash ]]]
        [[[ latex_mode = 'latex' ]]]
        [[[ save('box.svg') |||
            <?xml version="1.0" encoding="UTF-8" standalone="no"?>
            <svg width="210mm" height="297mm">
              <g>
                <rect width="30.170412" height="30" x="42" y="42" />
              </g>
            </svg>
        ]]]
        [[[ image('box.svg') ]]]
    """
    engage_string(code)

def test_image3():
    # Insert an image with conversion from SVG to PDF.  (This pair is a special
    # case that goes via inkscape.)
    code = r"""
        [[[ include latex.mash ]]]
        [[[ save('box.svg') |||
            <?xml version="1.0" encoding="UTF-8" standalone="no"?>
            <svg width="210mm" height="297mm">
              <g>
                <rect width="30.170412" height="30" x="42" y="42" />
              </g>
            </svg>
        ]]]
        [[[ image('box.svg') ]]]
    """
    engage_string(code)



if __name__ == '__main__':  #pragma: nocover
    run_tests_from_pattern(sys.argv[1])
