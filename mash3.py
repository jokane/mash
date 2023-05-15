#!/usr/bin/env python3

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

import concurrent.futures
import enum
import heapq
import os
import re
import shutil
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
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented  #pragma nocover

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
    def execute(self, executor):
        """Do the work represented by this node, if any.  Return an object that
        should replace this one in the tree."""

    @abstractmethod
    def as_indented_string(self, indent_level=0):
        """Return a nicely-formatted representation of this node, including
        its descendants, indented two spaces for each level."""

    @abstractmethod
    def stats(self):
        """Return a Stats object for this node and its descendants."""

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

    def execute(self, executor):
        """Do the work for this frame.  Run each of the children, pull their
        results, and then run any code elements here.  Use the given executor
        to manage any parallel tasks."""
        print("Executing this frame:")
        print(self.as_indented_string())

        # A helper for executing things and waiting for them to finish.
        def execute_children(executor, seq):
            """Allow each child in the given list to execute in parallel.  Wait for
            all of them to finish."""
            child_futures = []
            for child in seq:
                future = executor.submit(child.execute, executor)
                child_futures.append(future)
            for child_future in child_futures:
                child_future.result()

        # Execute all of the child frames.
        child_frames = [ child for child in self.children if isinstance(child, Frame)]
        execute_children(executor, child_frames)

        # Child frames are done.  Our child list should now be just leaves.
        # Execute each of them.
        execute_children(executor, self.children)

        # # If any children produced results, insert them into the list.
        # def replace_child_frames_with_elements(lst):
        #     for i, child in enumerate(lst):
        #         if not isinstance(child, Frame): continue
        #         self.text_children[i] = self.text_children[i].to_element()
        # replace_child_frames_with_elements(self.code_children)
        # replace_child_frames_with_elements(self.text_children)


        # print('done')

    def stats(self):
        return sum([child.stats() for child in self.children], start=Stats(1, 0, 0))

class FrameTreeLeaf(FrameTreeNode):
    """A leaf node.  Base class for CodeLeaf and TextLeaf."""
    def __init__(self, address, parent, content):
        super().__init__(address, parent)
        self.content = content

    @abstractmethod
    def line_marker(self):
        """A short string to mark what kind of leaf this is."""

    def as_indented_string(self, indent_level=0):
        return ('  '*indent_level) + f'{self.line_marker()} {self.content.__repr__()}\n'

class CodeLeaf(FrameTreeLeaf):
    """A leaf node representing Python code to be executed."""
    def execute(self, executor):
        """ Execute our text as Python code."""
        print("Executing this code leaf:")
        print(self.as_indented_string())

        # Fix the indentation.
        source = unindent(self.content)

        # Shift so that the line numbers in any exceptions match the actual
        # source address.
        source = ('\n'*(self.address.lineno-1)) + source

        # Run the stuff.
        code_obj = compile(source, self.address.filename, 'exec')
        exec(code_obj, {}, {})

    def line_marker(self):
        return '*'

    def stats(self):
        return Stats(0, 1, 0)

class TextLeaf(FrameTreeLeaf):
    """A leaf node representing just text."""

    def execute(self, executor):
        """ Nothing to do here."""
        return self

    def line_marker(self):
        return '.'

    def stats(self):
        return Stats(0, 0, 1)

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

    if frame != root:
        frame.address.exception('Frame was never closed.')

    return frame

def engage(argv):
    """ Actually do things, based on what the command line asked for. """

    start_time = time.time()

    if '-c' in argv: # pragma no cover
        if os.path.exists(".mash"):
            shutil.rmtree(".mash")
        if os.path.exists(".mash-archive"):
            shutil.rmtree(".mash-archive")
        argv.remove('-c')
        if len(argv) == 1:
            return

    if len(argv) == 1: # pragma no cover
        print('[reading from stdin]')
        input_filename = '/dev/stdin'
    else:
        input_filename = argv[1]

    with open(input_filename, 'r', encoding='utf-8') as input_file:
        text = input_file.read()

    root = tree_from_string(text, input_filename)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
    root.execute(executor)

    end_time = time.time()
    elapsed = f'{end_time-start_time:.02f}'

    stats = root.stats()
    print(f"{stats}; {elapsed} seconds")

def main(): # pragma no cover
    """ Main entry point.  Mostly just logic to respond to restart requests. """
    done = False
    original_cwd = os.getcwd()
    while not done:
        os.chdir(original_cwd)
        try:
            engage(sys.argv)
            done = True
        except RestartRequest:
            pass


if __name__ == '__main__': # pragma no cover
    main()
