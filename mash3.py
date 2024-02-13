#!/usr/bin/env python3
# pylint: disable=too-many-branches
# pylint: disable=too-few-public-methods
# pylint: disable=invalid-name
# pylint: disable=exec-used
# pylint: disable=global-statement

"""

-- mash --

This is a tool that allows text in various languages to be stored together
in a single input file. along with instructions for manipulating, mutating, and
storing that text.

Q. Why?

A1. Allows me to avoid naming things that appear only quickly in passing.

A2. Allows me to divide things into files based on content, rather than language.

A3. Can keep content and build instructions in the same place.

"""

import enum
import errno
import heapq
import itertools
import os
import re
import shutil
import subprocess
import sys
import time

from abc import ABC, abstractmethod

MASH_VERSION='3.0'

original_cwd = None

class RestartRequest (Exception):
    """ A special exception to be raised when some part of the code wants to
    start the entire process over. """


class Token(enum.Enum):
    """A token that represents a bit of mash syntax."""
    OPEN = 2
    SEPARATOR = 3
    CLOSE = 4
    NEWLINE = 5
    EOF = 6
    def __lt__(self, other):
        return self.value < other.value

class Address:
    """A location in some file."""
    def __init__(self, filename, lineno, offset):
        self.filename = filename
        self.lineno = lineno
        self.offset = offset

    def __str__(self):
        return f'({self.filename}, line {self.lineno}, offset {self.offset})'

    def exception(self, message=None, exception=None, type_=ValueError):
        """Something went wrong at this address.  Complain, mentioning the
        address."""
        exception = exception if exception else type_(f'{self}: {message}')
        exception.filename = self.filename
        exception.lineno = self.lineno
        exception.offset = self.offset
        raise exception

class Element:
    """A single string, a token indicating the start or end of a frame, or a
    separator token marking the difference between code and text parts of a
    frame.  Each of is these associated with an address where it started.  Used
    in the process of parsing the frame tree."""

    def __init__(self, address, content):
        self.address = address
        self.content = content

    def __str__(self):
        return f'{self.address} {repr(self.content)}'

class Event:
    """An atomic element of the execution.  Either the start or the finish of a
    node's work."""
    def __init__(self, node, start):
        self.node = node
        self.start = start
        self.the_hash = hash((id(self.node), self.start))

    def __str__(self):
        return f'{"start" if self.start else "finish"} {self.node}'

    def __hash__(self):
        return self.the_hash

    def __eq__(self, other):
        return self.node is other.node and self.start == other.start

    def __call__(self, variables):
        """Make this event actually happen."""
        if self.start:
            return self.node.start(variables)
        return self.node.finish(variables)

def Start(node):
    """Shortcut for creating start events."""
    return Event(node, True)

def Finish(node):
    """Shortcut for creating finish events."""
    return Event(node, False)


class FrameTreeNode(ABC):
    """A node in the frame tree.  Could be a frame (i.e. an internal node), a
    text block (a leaf containing completed text) or a code block (a leaf
    containing code to be executed)."""

    next_node_num = 0

    def __init__(self, address, parent):
        self.address = address
        self.parent = parent
        self.executed = False
        self.num = FrameTreeNode.next_node_num
        FrameTreeNode.next_node_num += 1

    def __str__(self):
        return f'{self.__class__.__name__}:{self.num:03d}'

    @classmethod
    @abstractmethod
    def name(cls, plural):
        """A human-readable name for the type thing represented by this node."""

    @abstractmethod
    def start(self, variables):
        """Do the initial wok represented by this node, if any.  Return True if
        this execution has changed the tree structure, i.e. new nodes, removed
        nodes, etc., or False if not."""

    @abstractmethod
    def finish(self, variables):
        """Same as start, but for things that should happen to wrap things up
        for this node."""

    @abstractmethod
    def as_indented_string(self, indent_level=0):
        """Return a nicely-formatted representation of this node, including
        its descendants, indented two spaces for each level."""

    @abstractmethod
    def all_nodes(self):
        """Return a generator that yields all of the nodes in this tree."""

    @abstractmethod
    def constraints(self, root): #pylint: disable=unused-argument,no-self-use
        """Return an iterable of (event1, event2) pairs indicating that event1
        should happened before event2."""

    def all_constraints(self):
        """Return a list of all of the constraints in this tree."""
        for node in self.all_nodes():
            yield from node.constraints(self)

def default_variables():
    """Return a dictionary to use as the variables in cases where no
    variables dict has been established yet."""
    return {
        'RestartRequest': RestartRequest,
        'tree_from_string': tree_from_string,
        'versions': { 'mash': MASH_VERSION }
    }

class Frame(FrameTreeNode):
    """A frame represents a block containing some (optional) text along with
    (optional) code that should operate on that text."""
    def __init__(self, address, parent):
        super().__init__(address, parent)
        self.children = []
        self.separated = False
        self.content = ''

    @classmethod
    def name(cls, plural):
        return 'frames' if plural else 'frame'

    def constraints(self, root):
        # Start before we finish.
        yield (Start(self), Finish(self))

        # Start before our children start. Finish after our children finish.
        for child in self.children:
            yield (Start(self), Start(child))
            yield (Finish(child), Finish(self))

        # Non-code children, followed by code children.
        ordered_kids = ([ x for x in self.children if not isinstance(x, CodeLeaf)]
                        + [ x for x in self.children if isinstance(x, CodeLeaf)])
        for child1, child2 in itertools.pairwise(ordered_kids):
            yield (Finish(child1), Start(child2))

    def as_indented_string(self, indent_level=0):
        r = ''
        r += ('  '*indent_level) + f'[[[ {self.address} {self}\n'
        for child in self.children:
            r += child.as_indented_string(indent_level+1)
        r += ('  '*indent_level) + ']]]\n'
        return r

    def start(self, variables):
        return False

    def finish(self, variables):
        # Nothing to do.  Note this means the content of a frame is discarded
        # unless something is done with it.  This often involves functions like
        # save() or push() from mashlib.
        return False

    def all_nodes(self):
        yield self
        for child in self.children:
            yield from child.all_nodes()


class FrameTreeLeaf(FrameTreeNode):
    """A leaf node.  Base class for CodeLeaf and TextLeaf."""
    def __init__(self, address, parent, content):
        super().__init__(address, parent)
        self.content = content

    @abstractmethod
    def line_marker(self):
        """A short string to mark what kind of leaf this is."""

    def as_indented_string(self, indent_level=0):
        x = self.content.__repr__()
        if len(x) > 60:
            x = x[:60] + '...'
        return (('  '*indent_level)
          + f'{self.line_marker()} {x} {self.address} {self}\n')

    def all_nodes(self):
        yield self

class CodeLeaf(FrameTreeLeaf):
    """A leaf node representing Python code to be executed."""
    @classmethod
    def name(cls, plural):
        return 'code segments' if plural else 'code segment'

    def constraints(self, root):
        yield (Start(self), Finish(self))

    def start(self, variables):
        """ Execute our text as Python code."""
        # Give the code access to the frame we are executing in (self) and to
        # this actual object (leaf).
        variables['self'] = self.parent
        variables['leaf'] = self

        # Run the stuff that's supposed to run before the stuff.
        if "before_code_hook" in variables:
            code_obj = compile("before_code_hook()", self.address.filename, 'exec')
            exec(code_obj, variables, variables)

        # Fix the indentation.
        source = unindent(self.content)

        # Shift so that the line numbers in any stack traces match the actual
        # source address.
        source = ('\n'*(self.address.lineno-1)) + source

        # Run the stuff.
        code_obj = compile(source, self.address.filename, 'exec')
        exec(code_obj, variables, variables)

        # Run the stuff that's supposed to run after the stuff.
        if "after_code_hook" in variables:
            code_obj = compile("after_code_hook(leaf)", self.address.filename, 'exec')
            exec(code_obj, variables, variables)

        # Done!
        return False

    def finish(self, variables):
        return False

    def line_marker(self):
        return '*'

class TextLeaf(FrameTreeLeaf):
    """A leaf node representing just text."""
    @classmethod
    def name(cls, plural):
        return 'text segments' if plural else 'text segment'

    def constraints(self, root):
        yield (Start(self), Finish(self))

    def start(self, variables):
        return False

    def finish(self, variables):
        if self.parent is not None:
            self.parent.content += self.content
        return False

    def line_marker(self):
        return '.'

class IncludeNode(FrameTreeNode):
    """A node representing the inclusion of another mash file.  Starts as a
    leaf.  When this node is started, we locate, load, and parse the
    requested file.  That tree becomes as child of this node."""
    def __init__(self, address, parent, content):
        super().__init__(address, parent)
        self.tree = None
        self.content = content

    @classmethod
    def name(cls, plural):
        return 'includes' if plural else 'include'

    def constraints(self, root):
        if self.tree is not None:
            yield (Start(self), Start(self.tree))
            yield (Finish(self.tree), Finish(self))
        else:
            yield (Start(self), Finish(self))

    def start(self, variables):
        """Load the file, parse it, and keep track of the tree it generates."""
        ok = False

        look_in = [ original_cwd ] + sys.path
        for directory in look_in:
            x = os.path.join(directory, self.content)
            if os.path.exists(x):
                ok = True
                break

        if not ok:
            message = (f"\nTrying to include {self.content}, "
                      + "but could not find it in any of these places:\n  "
                      + '\n  '.join(look_in)
                      + f'\nInclude initiated from {self.address}')
            exc = FileNotFoundError(errno.ENOENT, message, self.content)
            raise exc

        with open(x, 'r', encoding='utf-8') as input_file:
            text = input_file.read()

        self.tree = tree_from_string(text, self.content)

        if self.tree is None:
            print(f'[{self.content}: nothing there]')
            return False

        return True

    def finish(self, variables):
        return False

    def all_nodes(self):
        yield self
        if self.tree is not None:
            yield from self.tree.all_nodes()

    def as_indented_string(self, indent_level=0):
        r = ('  '*indent_level) + f'# include {self.content} {self}\n'
        if self.tree is not None:
            r += self.tree.as_indented_string(indent_level+1)
        return r

def unindent(s):
    """Given a string, modify each line by removing the whitespace that appears
    at the start of the first line."""
    # Find the prefix that we want to remove.  It is the sequence
    # of tabs or spaces that precedes the first real character.
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
    compressed_seq = compress_element_seq(seq)
    root = tree_from_element_seq(compressed_seq)
    return root

def token_seq_from_string(text):
    """Given a string, return a sequence of strings and tokens present in that
    string."""
    # Regex patterns of things we are looking for.
    patterns = [(Token.OPEN, r'\[\[\['),
                (Token.SEPARATOR,  r'\|\|\|'),
                (Token.CLOSE,  r'\]\]\]'),
                (Token.NEWLINE, '\n'),
                ]

    # Pointer to the current location in the text.
    index = 0

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

        # If there's any text before this token, keep track of it.
        if start > index:
            yield text[index:start]

        # Emit this token and move forward in the text.  Except if we have a
        # negative start value, which is a special case set by the
        # initialization loop above, indicating that we've not yet even
        # searched for this type of token.  (This special condition keeps us
        # from needed to duplicate the code below that does the searching.)
        if start >= 0:
            yield token_type
            index = match.span()[1]

        # Search for the next instance of this pattern from the current
        # location.  If we find the pattern, add the result to the queue to be
        # processed in the future.
        match = regex.search(text, index)
        if match:
            start = match.span()[0] if match else float('inf')
            heapq.heappush(priority_queue, (start, token_type, regex, match))

def element_seq_from_string(text, source_name, start_line=1):
    """Given a string, return a sequence of elements present in that string."""
    tokens = token_seq_from_string(text)
    return element_seq_from_token_seq(tokens, source_name, start_line)

def element_seq_from_token_seq(tokens, source_name, start_line):
    """Given a sequence of tokens and strings, return a sequence of elements
    present in that string by attaching addresses to each of them.  Assumes
    that the strings don't contain newlines."""

    lineno = start_line
    offset = 1

    for token in tokens:
        # Ship token token, at the current address.
        yield Element(Address(source_name, lineno, offset), token)

        # Update lineno and offset based on the content of this token.
        if isinstance(token, str):
            offset += len(token)
        elif token == Token.NEWLINE:
            offset = 1
            lineno += 1
        else:
            offset += 3

def compress_element_seq(elements):
    """Given a sequence of elements, collapse adjacent strings and newlines
    into single elements.  Assumes that the given elements have sequential
    addresses.  Modifies some of the existing Element objects, so be careful
    about using them again."""

    # The current text element that we are building.
    text_element = None

    for element in elements:
        if element.content == Token.NEWLINE:
            element.content = '\n'

        if isinstance(element.content, str):
            if text_element is None:
                text_element = element
            else:
                text_element.content += element.content
        else:
            if text_element is not None:
                yield text_element
                text_element = None
            yield element

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
                    leaf = IncludeNode(element.address, frame, match.group(1))
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


def run_tree(root, verbose=False):
    """Execute the given tree."""
    variables = default_variables()
    stats = {}
    executed_events = set()

    passes = 0

    def do_one_pass():
        # Build a dictionary of the as-yet-unsatisfied ordering constraints.
        # Keys are not-yet-executed events, and values are other sets of other
        # events that must be completed first.
        constraints_by_event = {}
        for node in root.all_nodes():
            e = Start(node)
            if e not in executed_events:
                constraints_by_event[e] = set()
            e = Finish(node)
            if e not in executed_events:
                constraints_by_event[e] = set()

        all_constraints = list(root.all_constraints())
        for before, after in all_constraints:
            if before not in executed_events and after not in executed_events:
                constraints_by_event[after].add(before)
            #     print(f'Adding {before} before {after}.')
            #     for event in executed_events:
            #         print('  ', event)
            # else:
            #     print(f'Skipping {before} before {after} because {before} is already done.')

        # Keep working until we've finished.  One iteration of this loop will
        # execute one event.
        while len(constraints_by_event.keys()) > 0:
            if verbose:
                print('\n\n')
                print(f'Pass {passes}: {len(constraints_by_event.keys())} events remaining, {len(executed_events)} events executed and {len(all_constraints)} constraints')
                print(root.as_indented_string())
                print('With executed events:')
                for event in executed_events:
                    print('  ', event)
                print('With these constraints:')
                for event, befores in constraints_by_event.items():
                    print(f'Befores for {event}:')
                    for before in befores:
                        print(f'  {before}')
                    if len(befores) == 0:
                        print(f'  (none)')


            # Look for an event that is ready to execute.
            ready_event = None
            for event, befores in constraints_by_event.items():
                if len(befores) == 0:
                    ready_event = event
                    break

            assert ready_event is not None

            # Found one.  Record the statistics, but only on the start so we don't
            # double count.
            if verbose:
                print(f'Ready to execute {ready_event}.')

            if ready_event.start:
                t = type(ready_event.node)
                try:
                    stats[t] += 1
                except KeyError:
                    stats[t] = 1
            
            # Actually execute it.
            if verbose:
                print('Running:', ready_event)
            changed = event(variables)

            # Bookkeeping: Remove the event we just compelted from the list of
            # things to do.  Add it to the list of things we've done.  Remove
            # it from any lists of unsatisfied constraints.
            del constraints_by_event[ready_event]
            executed_events.add(ready_event)
            for event, befores in constraints_by_event.items():
                befores.discard(ready_event)

            # Did the tree structure change when we executed?  If so, we need
            # to start over to catch possible new nodes and new constraints.
            if changed:
                if verbose:
                    print('Tree has changed.  Ending this pass')
                return True

            # End of the main while loop.


        # Done!
        return False

    while do_one_pass():
        passes += 1

    if 'at_end' in variables:
        variables['at_end']()

    return stats

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

    if '-v' in argv:
        verbose = True
        argv.remove('-v')
    else:
        verbose = False

    if len(argv) == 1:
        print('[reading from stdin]')
        input_filename = '/dev/stdin'
    else:
        input_filename = argv[1]

    node = IncludeNode(Address(input_filename, 1, 1), None, input_filename)

    def report_exception(e):
        print(e)
        def decode_and_print_if_not_empty(x):
            x = x.decode("utf-8", errors='ignore') if isinstance(x, bytes) else x
            if len(x.strip()) > 0:
                print(x)
        decode_and_print_if_not_empty(e.stdout)
        decode_and_print_if_not_empty(e.stderr)

    try:
        stats = run_tree(node, verbose)
    except subprocess.CalledProcessError as e:
        report_exception(e)
        return e.returncode


    end_time = time.time()
    elapsed = f'{end_time-start_time:.02f}'

    stats_text = '; '.join([f'{y} {x.name(y!=1)}' for x,y in stats.items() ])
    print(f"{stats_text}; {elapsed} seconds")

    return stats

def engage(argv):
    """ Main entry point."""
    global original_cwd
    done = False
    original_cwd = os.getcwd()
    while not done:
        os.chdir(original_cwd)
        try:
            stats = run_from_args(argv)
            done = True
        except RestartRequest:
            pass

    return stats


if __name__ == '__main__': # pragma no cover
    engage(sys.argv)

