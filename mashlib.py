# This is a library of "standard" functions that provide many of the basic
# operations that one might want to do on a mash frame.  It it should be
# imported automatically at the start of a mash run.

import os
import shutil

# This is the directory where started.
original_directory = os.getcwd()

# This is the directory where we will do all of our work, execute commands,
# etc.  This will be the current directory most of the time.
build_directory = ".mash"

# This is the build directory from the previous time through.  If nothing has
# changed, then we can just copy things over from there instead of re-building
# them.
prev_directory = ".mash-prev"


# Move any existing build directory to be the previous directory.  Delete any
# existing previous directory.
if os.path.exists(prev_directory):
  print("Removing", prev_directory)
  shutil.rmtree(prev_directory)

if os.path.exists(build_directory):
  print("Moving", build_directory, "to", prev_directory)
  shutil.move(build_directory, prev_directory)

# Make sure we have a build directory and that it's the current/working
# directory.
if not os.path.exists(build_directory):
  print("Creating", build_directory)
  os.makedirs(build_directory)
os.chdir(build_directory)

def save(target):
  global _
  # Does this file already exist?  If so, something is probably wrong.
  if(os.path.isfile(target)):
    raise Exception("File %s already exists.", target)

  # Check for an identically-named, identical-contents file in the previous
  # directory.
  existing_contents = ''
  prev_name = os.path.join(prev_directory, target)
  try:
    existing_contents = open(prev_name, 'r').read()
    exists_already = (existing_contents == _.text)
  except IOError:
    exists_already = False

  if exists_already:
    # We have this exact file in the previous directory.  Copy it instead of
    # saving directly.  This keeps the timestamp intact, which can help us
    # tell elsewhere if things need to be rebuilt.
    print("Using %s from previous build." % target)
    shuitl.copy(prev_name, target)

  else:
    # We don't have a file like this anywhere.  Actually save it.
    print("Writing %d bytes to %s." % (len(_.text), target))
    print(_.text, file=open(target, 'w'))


