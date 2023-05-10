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
import time

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
        return f'{self.filename}:{self.lineno}({self.offset}):'

    def exception(self, message):
        """Something went wrong at this address.  Complain, mentioning the
        address."""
        exception = ValueError(f'{self}: {message}')
        exception.filename = self.filename
        exception.lineno = self.lineno
        exception.offset = self.offset
        raise exception

class Element:
    """An element represents either a single string, a token indicating the
    start or end of a frame, or a separator token marking the difference
    between code and text parts of a frame.  Each of these associated with an
    address where it started."""

    def __init__(self, address, content):
        self.address = address
        self.content = content

    def __str__(self):
        return f'{self.address}: {self.content}'


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
            yield Element(Address(source_name, line, 0), text[index:start])

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

class Frame:
    """A frame represents a block containing some text along with code that
    should operate on that text."""
    def __init__(self, address, parent):
        self.parent = parent
        self.address = address
        self.code_children = []
        self.text_children = []
        self.separated = False

    def begin(self):
        """Start executing the code for this frame.  Return a future holding
        the result."""

    def stats(self):
        """Return a tuple (number of frames, number of code elements, number of
        text elements) in the entire tree."""

        num_frames = 1
        num_code = 0
        num_text = 0

        for mode, children in enumerate([self.code_children, self.text_children]):
            for child in children:
                if isinstance(child, Element):
                    if mode == 0:
                        num_code += 1
                    else:
                        num_text += 1
                else:
                    child_frames, child_code, child_text = child.stats()
                    num_frames += child_frames
                    num_code += child_code
                    num_text += child_text
        return (num_frames, num_code, num_text)

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

        if not frame.separated:
            current_list = frame.code_children
        else:
            current_list = frame.text_children

        if isinstance(element.content, str):
            current_list.append(element)
        elif element.content == Token.OPEN:
            frame = Frame(element.address, frame)
            current_list.append(frame)
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

    original_directory = os.getcwd()

    with open(input_filename, 'r', encoding='utf-8') as input_file:
        text = input_file.read()

    root = tree_from_string(text, input_filename)

    root.begin()

    end_time = time.time()
    elapsed = f'{end_time-start_time:.02f}'

    stat = root.stats()
    print(f"{stat[0]} frames; {stat[1]}+{stat[2]} elements; {elapsed} seconds")

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
