# robot-brains-builtins

This provides the builtin library for the FTC
[robot-brains](https://github.com/dangyogi/robot-brains)
programming language.

This code is written in the robot-brains language.  It is installed on your
PC, is automatically copied into all robot-brain compiled files, and runs on
the robot.

The suggested source directory structure on your PC is:

- robot_root/ (call this what you will)
  - robot/    (git clone of your robot code for this year's robot)
  - libs/     (place for all libraries that are used season to season) 
    - robot-brains-builtins/  (git clone of this project)
    - lib_15006/              (git clone of your team's library) 
    - lib_XXXX/               (git clone of some other team's library)

In addition, you may want to create a python venv directory under robot_root
and install robot-brains into it.  To do this:

1. Install [python3](https://python.org) on your PC.
1. Create your robot_root directory, and cd to it.
1. Create the python virtualenv directory:
   - python -m venv venv
1. Activate the virtualenv (this will change your prompt):
   - on Linux (note the dot (.)):
     - . venv/bin/activate
   - on Windows:
     - venv/bin/activate

At this point, you have two options:

1. Install the latest version of robot-brains from the
   [Python Package Index](https://pypi.org/).

   - This won't give you access to the latest developer version.

   - Once you have activated the virtualenv (as shown above):

     - pip install robot-brains

1. Run robot-brains from the sources:

   - This gives you access to the latest developer version (for better or for
     worse).

   - If you haven't already done so, install [git](https://git-scm.com/) on
     your PC.

   - Clone the robot-brains project from github:

     - cd robot_root
     - git clone git@github.com:dangyogi/robot-brains.git

   - Once you have activated the virtualenv (as shown above):

     - cd robot-brains
     - python setup.py develop

