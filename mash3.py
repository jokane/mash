#!/usr/bin/env python3

# -- mash --
#
# This is a tool that allows text in various languages to be stored together
# in a single input file. along with instructions for manipulating, mutating,
# and storing that text.
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

"""Tools for parsing mash text by finding opening delimiters ([[[) ,
separators (|||) , and closing delimiters (]]])."""

import enum
import heapq
import os
import re
import shutil
import sys

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

class Element:
    """An element represents either a single string, a token indicating the
    start or end of a frame, or a separator token marking the difference
    between code and text parts of a frame.  Each of these associated with a
    filename and line number from which it came."""

    def __init__(self, source_name, line, content):
        self.source_name = source_name
        self.line = line
        self.content = content

    def __repr__(self):
        return f'Element({self.source_name.__repr__()}, ' + \
            f'{self.line.__repr__()}, {self.content.__repr__()})'

    def __str__(self):
        return f'{self.source_name}:{self.line}: {self.content}'

    def exception(self, message):
        """Something went wrong around this element.  Complain, using the
        location of this element."""
        exception = ValueError(f'{self.source_name}, line {self.line}: {message}')
        exception.filename = self.source_name
        exception.lineno = self.line
        raise exception

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

    # Keep emitting elements until we run out of them.
    while priority_queue:
        # Which token is next?
        start, token_type, regex, match = heapq.heappop(priority_queue)

        # Is there some boring text before this token?  If so, emit it first.
        if start > index:
            yield Element(source_name, line, text[index:start])

        # Is it a newline?  If so, update the line number.
        if token_type == Token.NEWLINE:
            line += 1

        # Emit this token and move forward in the text.  Except if we have a
        # negative start value, which is a special case set by the
        # initialization loop above, indicating that we've not yet even
        # searched for this type of token.  (This special condition keeps us
        # from needed to duplicate the code below that does the searching.)
        if start >= 0:
            if token_type != Token.NEWLINE:
                yield Element(source_name, line, token_type)
            index = match.span()[1]

        # Search for the next instance of this pattern from the current
        # location.  If we find the pattern, add the result to the queue.
        match = regex.search(text, index)
        if match:
            start = match.span()[0] if match else float('inf')
            heapq.heappush(priority_queue, (start, token_type, regex, match))


    # If any text is left at the end, emit that too.
    if index < len(text):
        yield Element(source_name, line, text[index:])

class Frame:
    """A frame represents a block containing some text along with code that
    should operate on that text."""
    def __init__(self, parent):
        self.parent = parent
        self.code_children = []
        self.text_children = []
        self.separated = False

    def begin(self):
        """Start executing the code for this frame.  Return a future holding
        the result."""

def tree_from_element_seq(seq):
    """Given a sequence of elements, use the delimiters and separators to form
    the tree structure."""

    # Start with just an empty frame.
    root = Frame(None)
    frame = root

    # The root frame is special because it cannot have code; it's all
    # considered text.
    root.separated = True


    element = None
    for element in seq:
        if not frame.separated:
            current_list = frame.code_children
        else:
            current_list = frame.text_children

        if isinstance(element.content, str):
            current_list.append(element)
        elif element.content == Token.OPEN:
            frame = Frame(frame)
            current_list.append(frame)
        elif element.content == Token.CLOSE:
            if frame.parent is None:
                element.exception("Closing delimiter (]]]) found at top level.")
            frame = frame.parent
        elif element.content == Token.SEPARATOR:
            if frame.separated:
                element.exception("Multiple separators (|||) in a single frame.")
            frame.separated = True

    if element and frame != root:
        element.exception('Frame was never closed.')

    return frame

def engage(argv):
    """ Actually do things, based on what the command line asked for. """

    if '-c' in argv: # pragma no cover
        if os.path.exists(".mash"):
            shutil.rmtree(".mash")
        if os.path.exists(".mash-archive"):
            shutil.rmtree(".mash-archive")
        argv.remove('-c')
        if len(sys.argv) == 1:
            return

    if len(argv) == 1: # pragma no cover
        print('[reading from stdin]')
        input_filename = '/dev/stdin'
    else:
        input_filename = argv[1]

    original_directory = os.getcwd()

    with open(input_filename, 'r', encoding='utf-8') as input_file:
        text = input_file.read()

    root = tree_from_string(text, input_filename)

    root.begin()

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
