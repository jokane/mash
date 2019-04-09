# This is a library of "standard" functions that provide many of the basic
# operations that one might want to do on a mash frame.  It it should be
# imported automatically at the start of a mash run.

import difflib
import hashlib
import os
import shutil

# This is the directory where started.
original_directory = os.getcwd()

# This is the directory where we will do all of our work, execute commands,
# etc.  This will be the current directory most of the time.
build_directory = os.path.join(original_directory, ".mash")

# This is the build directory from the previous time through.  If nothing has
# changed, then we can just copy things over from there instead of re-building
# them.
prev_directory = os.path.join(original_directory, ".mash-prev")

# This is the directory that should contain the completed output files.
keep_directory = original_directory


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
  """Ensure that the current contents of this frame exist in the build
  directory as a file with the given name.  Use an old copy from the previous
  directory if possible."""
  global _
  # Does this file already exist?  If so, something is probably wrong.
  if(os.path.isfile(target)):
    raise Exception("File %s already exists.", target)

  # Check for an identically-named, identical-contents file in the previous
  # directory.
  prev_name = os.path.join(prev_directory, target)
  try:
    existing_contents = open(prev_name, 'r').read()
    exists_already = (existing_contents == _.text)
  except IOError as e:
    exists_already = False

  if exists_already:
    # We have this exact file in the previous directory.  Copy it instead of
    # saving directly.  This keeps the timestamp intact, which can help us
    # tell elsewhere if things need to be rebuilt.
    print("Using %s from previous build." % target)
    shutil.copy2(prev_name, target)

  else:
    # We don't have a file like this anywhere.  Actually save it.
    print("Writing %d bytes to %s." % (len(_.text), target))
    print(_.text, file=open(target, 'w'), end='')

def retrieve(target, *sources):
  """Check whether the given target file exists in the previous directory,
  and if so, if it's newer than all of the given sources.  If so, copy it
  over and return True.  If not, do nothing and return False."""
  prev_target = os.path.join(prev_directory, target)
  if not os.path.isfile(prev_target):
    print(target,"is not available.")
    return False

  target_time = os.path.getmtime(prev_target)

  for source in sources:
    source_time = os.path.getmtime(source)
    if source_time > target_time:
      print(source, source_time, "is newer than", target, target_time)
      return False

  print(target,"is available from previous build.")
  shutil.copy2(prev_target, build_directory)


  return True

def anon():
  """Return an anonymous name constructed by hashing the contents of the
  current frame."""
  global _
  return hashlib.sha1(_.text.encode('UTF-8')).hexdigest()[:7]

def exec(command):
  """Execute the given command in a shell.  If it fails, complain."""
  return_code = os.system(command)
  print("(exec)", command)
  if return_code != 0:
    raise Exception("Shell command '%s' failed with return code %d." % (shell_command, return_code))

def keep(file_to_keep):
  """Copy a file or directory from the working directory to the keep
  directory."""
  if os.path.isfile(file_to_keep):
    shutil.copy2(file_to_keep, keep_directory)
  elif os.path.isdir(file_to_keep):
    target = os.path.join(keep_directory, file_to_keep)
    if os.path.exists(target):
      shutil.rmtree(target)
    shutil.copytree2(file_to_keep, target)
  else:
    raise Exception("Don't know how to keep %s, which is neither file nor directory." % file_to_keep)
  

