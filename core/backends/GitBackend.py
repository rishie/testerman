# -*- coding: utf-8 -*-
##
# This file is part of Testerman, a test automation system.
# Copyright (c) 2011 Sebastien Lefevre and other contributors
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
##

##
# A FileSystemBackend implementation that use a GIT repository
# to store versioned files.
#
# Relies on dulwich GIT python implementation.
#
# Files are locally managed into a working dir.
# Write operations trigger GIT actions.
##

import FileSystemBackend
import FileSystemBackendManager

import dulwich

import glob
import logging
import os
import shutil
import time

################################################################################
# Logging
################################################################################

def getLogger():
	return logging.getLogger('TS.FSB.Git')


def fileExists(path):
	try:
		os.stat(path)
		return True
	except:
		return False

class GitBackend(FileSystemBackend.FileSystemBackend):
	"""
	Properties:
	- working_dir: the working directory the GIT repo is initially cloned.
	- repository: 
	"""
	def logged(fn, *args, **kw):
		"""
		Decorator function to log function calls easily.
		"""
		def _decorator(self, *args, **kw):
			arglist = ', '.join([repr(x) for x in args])
			if kw:
				arglist += ', '.join([u'%s=%s' % x for x in kw.items()])
			desc = "%s(%s)" % (fn.__name__, arglist)
			getLogger().debug(":: %s" % desc)
			return fn(self, *args, **kw)
		return _decorator

	def __init__(self):
		FileSystemBackend.FileSystemBackend.__init__(self)
		# Some default properties
		self.setProperty('excluded', '.git')
		self.setProperty('default_committer', 'Testerman GIT Backend <testerman@localhost>')

		# Mandatory properties (defined here to serve as documentation)
		self.setProperty('repository', None)

	
	def initialize(self):
		# Exclusion list.
		# Something based on a glob pattern should be better,
		# so that the user can configure in the backends.ini file something like
		# excluded = *.pyc .svn CVS
		# that generated an _excluded_files to [ '*.pyc', '.svn', 'CVS' ], ...
		self._excludedPatterns = filter(lambda x: x, self['excluded'].split(' '))

		self._repo = dulwich.repo.Repo(self['repository'])
		self._defaultCommitter = self['default_committer']
			
		return True
	
	def _realpath(self, path):
		"""
		Compute the local path of a filename.
		filename is relative to the mountpoint.
		
		Returns None if we compute a filename/path which is outside
		the basepath.
		"""
		path = os.path.realpath("%s/%s" % (self['repository'], path))
		if not path.startswith(self['repository']):
			getLogger().warning("Attempted to handle a path that is not under repository (%s). Ignoring." % path)
			return None
		else:
			return path
	
	def read(self, filename, revision = None):
		filename = self._realpath(filename)
		if not filename: 
			return None
		
		try:
			f = open(filename)
			content = f.read()
			f.close()
			return content
		except Exception, e:
			getLogger().warning("Unable to read file %s: %s" % (filename, str(e)))
			return None

	def write(self, filename, content, baseRevision = None, reason = None):
		"""
		Write the file in the working tree, then autocommit it.
		"""
		if filename.startswith('/'):
			filename = filename[1:]
		
		localpath = filename

		filename = self._realpath(filename)
		if not filename: 
			raise Exception('Invalid file: not in base path')

		backupFile = None
		try:
			if fileExists(filename):
				b = '%s.backup' % filename
				os.rename(filename, b)
				backupFile = b
			f = open(filename, 'w')
			f.write(content)
			f.close()
			if backupFile:
				try:
					os.remove(backupFile)
				except:
					pass
		except Exception, e:
			if backupFile:
				os.rename(backupFile, filename)
			getLogger().warning("Unable to write content to %s: %s" % (filename, str(e)))
			raise(e)

		self._repo.stage([localpath])

		ret = self._repo.do_commit(message = "%s %s (reason: %s)" % (backupFile and "Updated" or "Added", localpath, reason), committer = self._defaultCommitter)
		getLogger().info("New revision created: %s" % ret)
		return ret

	@logged
	def rename(self, filename, newname, reason = None):
		"""
		Rename the file locally, then autocommit one deletion / one insertion for the main file,
		and one deletion/insertion per associated profile.
		"""
		# Remove the heading / for the local name
		if filename.startswith('/'):
			filename = filename[1:]
		localname = filename

		# The new local name relative to the file's cwd
		if newname.startswith('/'):
			newname = newname[1:]
		newlocalname = newname
		# The new local name relative to the working tree
		newlocalname = os.path.join(os.path.split(filename)[0], newlocalname)

		# local filesystem: absolute filenames
		filename = self._realpath(localname)
		if not filename: 
			return False
		newfilename = self._realpath(newlocalname)
		if not newfilename: 
			getLogger().warning("Unable to rename %s to %s: the target name is not in base path" % (filename, newname, str(e)))
			return False
		
		profilesdir = "%s.profiles" % filename
		newprofilesdir = "%s.profiles" % newfilename
		try:
			os.rename(filename, newfilename)
		except Exception, e:
			getLogger().warning("Unable to rename %s to %s: %s" % (filename, newname, str(e)))
			return False

		try:
			# rename profiles dir, too
			os.rename(profilesdir, newprofilesdir)
		except Exception, e:
			pass

		# Identify the profiles that were renamed/moved
		staged = [newlocalname, localname]
		
		for profile in glob.glob(newprofilesdir + '/*'):
			# The old profile name
			staged.append("%s.profiles/%s" % (localname, os.path.split(profile)[1]))
			# The new profile name
			staged.append("%s.profiles/%s" % (newlocalname, os.path.split(profile)[1]))
		
		self._repo.stage(staged)
		ret = self._repo.do_commit(message = "Renamed %s to %s (reason: %s)" % (localname, newname, reason), committer = self._defaultCommitter)
		getLogger().info("New revision created: %s" % ret)
		return ret

	@logged
	def unlink(self, filename, reason = None):
		"""
		Remove the file from the working tree, then autocommit the change.
		
		TODO: manage associated profiles.
		"""
		# Remove the heading / for the local name
		if filename.startswith('/'):
			filename = filename[1:]
		localname = filename

		# local filesystem: absolute filenames
		filename = self._realpath(filename)
		if not filename: 
			return False
		
		staged = [localname]
		# Reference profiles to remove
		profilesdir = "%s.profiles" % filename
		for profile in glob.glob(newprofilesdir + '/*'):
			staged.append("%s.profiles/%s" % (localname, os.path.split(profile)[1]))

		# Now actually remove associated profiles, if any
		try:
			shutil.rmtree(profilesdir, ignore_errors = True)
		except:
			getLogger().warning("Unable to remove profiles associated to %s: %s" % (filename, str(e)))

		try:
			os.remove(filename)
		except Exception, e:
			getLogger().warning("Unable to unlink %s: %s" % (filename, str(e)))
			return False
		
		self._repo.stage(staged)
		ret = self._repo.do_commit(message = "Deleted %s (reason: %s)" % (localpath, reason), committer = self._defaultCommitter)
		getLogger().info("New revision created: %s" % ret)
		return True

	@logged
	def getdir(self, path):
		"""
		Read the working tree. No VCS interaction here.
		"""
		path = self._realpath(path)
		if not path: 
			return None

		try:
			entries = os.listdir(path)
			ret = []
			for entry in entries:
				if os.path.isfile("%s/%s" % (path, entry)):
					ret.append({'name': entry, 'type': 'file'})
				elif os.path.isdir("%s/%s" % (path, entry)) and not entry in self._excludedPatterns and not entry.endswith('.profiles'):
					ret.append({'name': entry, 'type': 'directory'})
			return ret
		except Exception, e:
			getLogger().warning("Unable to list directory %s: %s" % (path, str(e)))
		return None

	@logged
	def mkdir(self, path):
		"""
		Create a directory in the working tree.
		No autocommit here - empty directories do not seem to be versioned by GIT.
		"""
		if path.startswith('/'):
			path = path[1:]
		localpath = path

		path = self._realpath(path)
		if not path: 
			return False

		if fileExists(path):
			return False

		try:
			os.makedirs(path, 0755)
		except:
			# already exists only ?...
			pass
			
		return True
	
	@logged
	def rmdir(self, path):
		"""
		Remove an empty directory. No VCS interaction here.
		(Not trackable by git ?)
		"""
		path = self._realpath(path)
		if not path: 
			return False

		try:
			if not os.path.isdir(path):
				return False
			else:
				os.rmdir(path)
				return True
		except Exception, e:
			getLogger().warning("Unable to rmdir %s: %s" % (path, str(e)))
		return False

	@logged
	def renamedir(self, path, newname):
		"""
		Rename a directory, then autocommit removes/adds.
		
		# TODO: recursive staging.
		"""
		# Remove the heading / for the local name
		if path.startswith('/'):
			path = path[1:]
		localname = path

		# The new local name relative to the dir's cwd
		if newname.startswith('/'):
			newname = newname[1:]
		newlocalname = newname
		# The new local name relative to the working tree
		newlocalname = os.path.join(os.path.split(path)[0], newlocalname)

		path = self._realpath(path)
		if not path: 
			return False
		
		try:
			os.rename(path, newname)
			return True
		except Exception, e:
			getLogger().warning("Unable to rename dir %s to %s: %s" % (path, newname, str(e)))
			return False
		
		self._repo.stage([localname, newname])
		ret = self._repo.do_commit(message = "Renamed dir %s to %s (reason: %s)" % (localname, newname, reason), committer = self._defaultCommitter)
		getLogger().info("New revision created: %s" % ret)
		
		return False

	@logged
	def attributes(self, filename, revision = None):
		filename = self._realpath(filename)
		if not filename: 
			return None

		try:
			s = os.stat(filename)
			a = FileSystemBackend.Attributes()
			a.mtime = s.st_ctime
			a.size = s.st_size
			return a
		except Exception, e:
			getLogger().warning("Unable to get file attributes for %s: %s" % (filename, str(e)))			
		return None

	@logged
	def revisions(self, filename, baseRevision, scope):
		"""
		Returns the revisions for a given file.
		"""
		if filename.startswith('/'):
			filename = filename[1:]
		
		localname = filename
		
		filename = self._realpath(filename)
		if not filename: 
			return None
		
		# Not yet implemented
		return None
	
	def isdir(self, path):
		path = self._realpath(path)
		if not path: 
			return False
		return os.path.isdir(path)

	def isfile(self, path):
		path = self._realpath(path)
		if not path:
			return False
		return os.path.isfile(path)

	# Profiles Management			

	def getprofiles(self, filename):
		filename = self._realpath(filename)
		if not filename:
			return None
		
		profilesdir = "%s.profiles" % filename
		
		try:
			entries = os.listdir(profilesdir)
			ret = []
			for entry in entries:
				if os.path.isfile("%s/%s" % (profilesdir, entry)):
					ret.append({'name': entry, 'type': 'file'})
				elif os.path.isdir("%s/%s" % (profilesdir, entry)) and not entry in self._excludedPatterns:
					ret.append({'name': entry, 'type': 'directory'})
			return ret
		except Exception, e:
			getLogger().warning("Unable to list profiles directory %s: %s" % (profilesdir, str(e)))
		return None

	def readprofile(self, filename, profilename):
		filename = self._realpath(filename)
		if not filename:
			return None
		
		profilefilename = "%s.profiles/%s" % (filename, profilename)
		try:
			f = open(profilefilename)
			content = f.read()
			f.close()
			return content
		except Exception, e:
			getLogger().warning("Unable to read file %s: %s" % (filename, str(e)))
			return None
		
	def writeprofile(self, filename, profilename, content):
		"""
		Create or update a profile, then autocommit.
		"""
		if filename.startswith('/'):
			filename = filename[1:]
		localname = filename

		profilelocalname = "%s.profiles/%s" % (localname, profilename)
		filename = self._realpath(filename)
		if not filename: 
			raise Exception('Invalid file: not in base path')

		# Automatically creates this backend-specific dir
		profilesdir = "%s.profiles" % filename

		try:
			os.makedirs(profilesdir, 0755)
		except:
			pass

		profilefilename = "%s.profiles/%s" % (filename, profilename)
		backupFile = None
		try:
			if fileExists(profilefilename):
				b = '%s.backup' % profilefilename
				os.rename(profilefilename, b)
				backupFile = b
			f = open(profilefilename, 'w')
			f.write(content)
			f.close()
			if backupFile:
				try:
					os.remove(backupFile)
				except:
					pass
		except Exception, e:
			if backupFile:
				os.rename(backupFile, profilefilename)
			getLogger().warning("Unable to write content to %s: %s" % (profilefilename, str(e)))
			raise(e)

		self._repo.stage([profilelocalname])
		ret = self._repo.do_commit(message = "%s profile %s for %s" % (backupFile and "Updated" or "Added", profilename, localname), committer = self._defaultCommitter)
		getLogger().info("New revision created: %s" % ret)
		return ret

	def unlinkprofile(self, filename, profilename):
		"""
		Removes a profile, then autocommit the change. 
		"""
		if filename.startswith('/'):
			filename = filename[1:]
		localname = filename

		profilelocalname = "%s.profiles/%s" % (localname, profilename)

		filename = self._realpath(filename)
		if not filename:
			return None
		
		profilefilename = "%s.profiles/%s" % (filename, profilename)
		try:
			os.remove(profilefilename)
		except Exception, e:
			getLogger().warning("Unable to unlink %s: %s" % (profilefilename, str(e)))
			return False

		self._repo.stage([profilelocalname])
		ret = self._repo.do_commit(message = "Removed profile %s for %s" % (profilename, localname), committer = self._defaultCommitter)
		getLogger().info("New revision created: %s" % ret)
		return True
		
	def profileattributes(self, filename, profilename):
		filename = self._realpath(filename)
		if not filename: 
			return None

		profilefilename = "%s.profiles/%s" % (filename, profilename)

		try:
			s = os.stat(profilefilename)
			a = FileSystemBackend.Attributes()
			a.mtime = s.st_ctime
			a.size = s.st_size
			return a
		except Exception, e:
			getLogger().warning("Unable to get file attributes for %s: %s" % (profilefilename, str(e)))			
		return None
	

FileSystemBackendManager.registerFileSystemBackendClass("git", GitBackend)
