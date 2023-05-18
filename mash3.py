#!/usr/bin/env python3
# pylint: disable=too-many-branches
# pylint: disable=too-few-public-methods
# pylint: disable=invalid-name
# pylint: disable=exec-used

"""This is a tool that allows text in various languages to be stored together
in a single input file. along with instructions for manipulating, mutating, and
storing that text."""

# -- mash --
#
#
# Q. Why?
#
# A1. Allows me to avoid naming things that appear only quickly in passing.
# A2. Allows me to divide things into files based on content, rather than
#     language.
# A3. Can keep content and build instructions in the same place.
#
# History:
#   2016-11-17: Started as a revision of some older, presentation-specific scripts.
#   2016-12-12: First working version.
#   2017-02-20: Various language additions, mostly for build commands.
#   2017-04-20: More language expansions.  Better error handling.
#   2017-07-11: Betting handling of semicolons in commands.
#   2017-12-05: Better error messages.
#   2018-04-06: @@ syntax for quick importing
#   2018-07-26: Better handling of commas in commands.
#   2018-08-17: & syntax for inserting chunks.
#   2019-04-02: Starting major rewrite, replacing custom language with Python.
#   2022-11-17: Starting second major overall, to allow parallel execution.

import enum
import heapq
import os
import re
import shutil
import subprocess
import sys
import time

from abc import ABC, abstractmethod

class RestartRequest (Exception):
    """ A special exception to be raised when some part of the code wants to
    start the entire process over. """


class Token(enum.Enum):
    """A token that represents a bit of mash syntax."""
    OPEN = 2
    SEPARATOR = 3
    CLOSE = 4
    NEWLINE = 5
    def __lt__(self, other):
        return self.value < other.value

class Address:
    """A location in some file."""
    def __init__(self, filename, lineno, offset):
        self.filename = filename
        self.lineno = lineno
        self.offset = offset

    def __str__(self):
        return f'({self.filename}, line {self.lineno}, pos {self.offset})'

    def exception(self, message):
        """Something went wrong at this address.  Complain, mentioning the
        address."""
        exception = ValueError(f'{self}: {message}')
        exception.filename = self.filename
        exception.lineno = self.lineno
        exception.offset = self.offset
        raise exception

class Element:
    """A single string, a token indicating the start or end of a frame, or a
    separator token marking the difference between code and text parts of a
    frame.  Each of these associated with an address where it started.  Used in
    the process of parsing the frame tree."""

    def __init__(self, address, content):
        self.address = address
        self.content = content

    def __str__(self):
        return f'{self.address} {repr(self.content)}'

class Stats:
    """Statistics for the complexity of a frame tree."""
    def __init__(self, frames, code, text):
        self.frames = frames
        self.code = code
        self.text = text

    def __add__(self, other):
        return Stats(self.frames + other.frames,
                     self.code + other.code,
                     self.text + other.text)

    def __eq__(self, other):
        return (self.frames == other.frames
                and self.code == other.code
                and self.text == other.text)

    def __str__(self):
        return f'{self.frames} frames; {self.code}+{self.text} leaves'

class FrameTreeNode(ABC):
    """A node in the frame tree.  Could be a frame (i.e. an internal node), a
    text block (a leaf containing completed text) or a code block (a leaf
    containing code to be executed)."""

    def __init__(self, address, parent):
        self.address = address
        self.parent = parent

    @abstractmethod
    def execute(self, variables):
        """Do the work represented by this node, if any.  Return a list of
        objects that should replace this one in the tree."""

    @abstractmethod
    def as_indented_string(self, indent_level=0):
        """Return a nicely-formatted representation of this node, including
        its descendants, indented two spaces for each level."""

    @abstractmethod
    def stats(self):
        """Return a Stats object for this node and its descendants."""

    def announce(self, variables):
        """Print some details about this node, to be called just before executing."""
        # if variables is None:
        #     variables = self.default_variables()
        # print(f"Executing {type(self)} with variables ({variables.keys()}):")

        # print(self.as_indented_string(indent_level=1), end='')
        # print()

def default_variables():
    """Return a dictionary to use as the variables in cases where no
    variables dict has been established yet."""
    return {'RestartRequest': RestartRequest,}

class Frame(FrameTreeNode):
    """A frame represents a block containing some text along with code that
    should operate on that text."""
    def __init__(self, address, parent):
        super().__init__(address, parent)
        self.children = []
        self.separated = False

    def as_indented_string(self, indent_level=0):
        r = ''
        r += ('  '*indent_level) + '[[[\n'
        for child in self.children:
            r += child.as_indented_string(indent_level+1)
        r += ('  '*indent_level) + ']]]\n'
        return r

    def execute(self, variables):
        """Do the work for this frame.  Run each of the children, pull their
        results, and then run any code elements here."""
        self.announce(variables)

        # Execute all of the child frames.
        self.execute_children(variables, True)

        # Child frames are done.  Our child list should now be just leaves.
        # Execute each of them.
        self.execute_children(variables, False)

        # All done.
        return self.children

    def execute_children(self, variables, frames_only):
        """Allow each child to execute in parallel.  Wait for all of them to
        finish.  Replace each child with the replacements that it returns."""
        new_children = []
        for child in self.children:
            if frames_only and not isinstance(child, Frame):
                new_children.append(child)
            else:
                child_result = child.execute(variables)
                new_children += child_result

        self.children = new_children

    def stats(self):
        return sum([child.stats() for child in self.children], start=Stats(1, 0, 0))

class FrameTreeLeaf(FrameTreeNode):
    """A leaf node.  Base class for CodeLeaf, TextLeaf, and IncludeLeaf."""
    def __init__(self, address, parent, content):
        super().__init__(address, parent)
        self.content = content

    @abstractmethod
    def line_marker(self):
        """A short string to mark what kind of leaf this is."""

    def as_indented_string(self, indent_level=0):
        return ('  '*indent_level) + f'{self.line_marker()} {self.content.strip().__repr__()}\n'

class CodeLeaf(FrameTreeLeaf):
    """A leaf node representing Python code to be executed."""
    def execute(self, variables):
        """ Execute our text as Python code."""
        self.announce(variables)

        # Fix the indentation.
        source = unindent(self.content)

        # Shift so that the line numbers in any exceptions match the actual
        # source address.
        source = ('\n'*(self.address.lineno-1)) + source

        # Run the stuff.
        code_obj = compile(source, self.address.filename, 'exec')
        exec(code_obj, variables, variables)

        return [ TextLeaf(self.address, self.parent, '') ]

    def line_marker(self):
        return '*'

    def stats(self):
        return Stats(0, 1, 0)

class TextLeaf(FrameTreeLeaf):
    """A leaf node representing just text."""

    def execute(self, variables):
        """ Nothing to do here."""
        return [ self ]

    def line_marker(self):
        return '.'

    def stats(self):
        return Stats(0, 0, 1)

class IncludeLeaf(FrameTreeLeaf):
    """A leaf node representing the inclusion of another mash file."""
    def execute(self, variables):
        """Load the file and execute it."""
        self.announce(variables)

        with open(self.content, 'r', encoding='utf-8') as input_file:
            text = input_file.read()

        root = tree_from_string(text, self.content)

        if root is None:
            print(f'[{self.content}: nothing there]')
            return []

        result = root.execute(variables)

        return result

    def line_marker(self):
        return '#'

    def stats(self):
        return Stats(0, 0, 0)

def unindent(s):
    """Given a string, modify each line by removing the whitespace that appears
    at the start of the first line."""
    # Find the prefix that we want to remove.  It is the sequence
    # of tabs or spaces that preceeds the first real character.
    match = re.search(r'([ \t]*)[^ \t\n]', s, re.M)

    # If we found a prefix, remove it from the start of every line.
    if match:
        prefix = match.group(1)
        s = re.sub('\n' + prefix, '\n', s)
        s = re.sub('^' + prefix, '', s)
    return s

def tree_from_string(text, source_name, start_line=1):
    """Given a string, parse the string as a mash document.  Return the root frame."""
    seq = element_seq_from_string(text, source_name, start_line)
    root = tree_from_element_seq(seq)
    return root

def element_seq_from_string(text, source_name, start_line=1):
    """Given a string, return a sequence of elements present in that string."""
    # Regex patterns of things we are looking for.
    patterns = [(Token.OPEN, r'\[\[\['),
                (Token.SEPARATOR,  r'\|\|\|'),
                (Token.CLOSE,  r'\]\]\]'),
                (Token.NEWLINE, '\n')]

    # Pointer to the current location in the text.
    index = 0

    # Which line are we on?  Minus one because the loop below has a dummy
    # iteration to search for the first newline.
    line = start_line - 1

    # Form a priority queue of tokens that we've found in the text.  Each one
    # refers to the next instance of each type of token that appears.  Start
    # with dummy instances of each token, which will actually be searched in
    # the first iterations of the main loop below.
    priority_queue = []
    for token_type, pattern in patterns:
        start = -1
        regex = re.compile(pattern, re.DOTALL)
        match = None
        priority_queue.append((start, token_type, regex, match))
    heapq.heapify(priority_queue)

    text_so_far = ''

    # Keep emitting elements until we run out of them.
    while priority_queue:
        # Which token is next?
        start, token_type, regex, match = heapq.heappop(priority_queue)

        # If there's any text before this token, keep track of it.
        if start > index:
            text_so_far += text[index:start]

        # Is it a newline?
        # - If so, update the line number, but also incude it in the actual
        # text.
        # - If not, then the text element we (may) have been assembling is
        # complete.
        if token_type == Token.NEWLINE:
            line += 1
            text_so_far += '\n'
        elif len(text_so_far) > 0:
            yield Element(Address(source_name, line, 0), text_so_far)
            text_so_far = ''

        # Emit this token and move forward in the text.  Except if we have a
        # negative start value, which is a special case set by the
        # initialization loop above, indicating that we've not yet even
        # searched for this type of token.  (This special condition keeps us
        # from needed to duplicate the code below that does the searching.)
        if start >= 0:
            if token_type != Token.NEWLINE:
                yield Element(Address(source_name, line, 0), token_type)
            index = match.span()[1]

        # Search for the next instance of this pattern from the current
        # location.  If we find the pattern, add the result to the queue.
        match = regex.search(text, index)
        if match:
            start = match.span()[0] if match else float('inf')
            heapq.heappush(priority_queue, (start, token_type, regex, match))


    # If any text is left at the end, emit that too.
    if index < len(text):
        yield Element(Address(source_name, line, 0), text[index:])

def tree_from_element_seq(seq):
    """Given a sequence of elements, use the delimiters and separators to form
    the tree structure."""

    frame = None
    root = None

    # Put each element into a frame.
    for element in seq:
        if frame is None:
            # At the first element, create the root frame.
            root = Frame(element.address, None)
            frame = root

            # The root frame is special because it cannot have code; it's all
            # considered text.
            root.separated = True

        if isinstance(element.content, str):
            if frame.separated:
                leaf = TextLeaf(element.address, frame, element.content)
            else:
                match = re.match(r'\s*include\s+(\S+)\s*', element.content)
                if match:
                    leaf = IncludeLeaf(element.address, frame, match.group(1))
                else:
                    leaf = CodeLeaf(element.address, frame, element.content)
            frame.children.append(leaf)
        elif element.content == Token.OPEN:
            frame = Frame(element.address, frame)
            frame.parent.children.append(frame)
        elif element.content == Token.CLOSE:
            if frame.parent is None:
                element.address.exception("Closing delimiter (]]]) found at top level.")
            frame = frame.parent
        elif element.content == Token.SEPARATOR:
            if frame.separated:
                element.address.exception("Multiple separators (|||) in a single frame.")
            frame.separated = True

    if root is not None and frame != root:
        frame.address.exception('Frame was never closed.')

    return frame


def run_tree(root):
    """Execute the given tree."""
    variables = default_variables()
    result = root.execute(variables)
    if 'at_end' in variables:
        variables['at_end']()
    return result

def run_from_args(argv):
    """Actually do things, based on what the command line asked for."""
    start_time = time.time()

    if '-c' in argv:
        if os.path.exists(".mash"):
            shutil.rmtree(".mash")
        if os.path.exists(".mash-archive"):
            shutil.rmtree(".mash-archive")
        argv.remove('-c')
        if len(argv) == 1:
            return 0

    if len(argv) == 1:
        print('[reading from stdin]')
        input_filename = '/dev/stdin'
    else:
        input_filename = argv[1]

    node = IncludeLeaf(Address(input_filename, 1, 1), None, input_filename)

    try:
        result = run_tree(node)
    except subprocess.CalledProcessError as e:
        print(e)
        print(e.stdout.decode("utf-8", errors='ignore'))
        print(e.stderr.decode("utf-8", errors='ignore'))
        return e.returncode

    end_time = time.time()
    elapsed = f'{end_time-start_time:.02f}'

    if len(result) > 0:
        stats = result[0].stats()
        print(f"{stats}; {elapsed} seconds")

    print(f"{elapsed} seconds")

    return 0

def engage(argv):
    """ Main entry point."""
    done = False
    original_cwd = os.getcwd()
    while not done:
        os.chdir(original_cwd)
        try:
            run_from_args(argv)
            done = True
        except RestartRequest:
            pass


if __name__ == '__main__': # pragma no cover
    engage(sys.argv)
