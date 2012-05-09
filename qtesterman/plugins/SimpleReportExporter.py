# -*- coding: utf-8 -*-
##
# This file is part of Testerman, a test automation system.
# Copyright (c) 2012 QTesterman contributors
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
# A plugin to display logs as a simple text summary.
#
##

from PyQt4.Qt import *
from PyQt4.QtXml import *

from Base import *
from CommonWidgets import *

import Plugin
import PluginManager
import Documentation
import TemplateManagement
import airspeed

import os
import os.path
import time


##############################################################################
# Plugin Constants
##############################################################################

# Plugin ID, as generated by uuidgen
PLUGIN_ID = "acfec987-f85d-46f4-baf5-f81c840adb38"
VERSION = "1.0.0"
DESCRIPTION = """
A template-based exporter that creates text-based reports.<br />
<br />
Templates are Velocity-compliant. The following objects/variables
are made available to them:
<pre>
record of Ats atses, // hierarchical model: atses that contain testcases
record of Testcase testcases, // flat model: all testcases are available directly

// global stats (all atses included)
// do not contains preamble/postamble stats
integer ats_count,
integer testcase_count,
integer pass_count,
integer fail_count,
integer inconc_count,
integer none_count,
integer error_count,

charstring pass_ratio, // percentage
charstring fail_ratio, // percentage
charstring inconc_ratio, // percentage
charstring none_ratio, // percentage
charstring error_ratio, // percentage
</pre>
With the following types definitions:
<pre>
type record Ats {
	charstring id
	charstring duration,
	charstring start_time,
	charstring stop_time,
	record of Testcase testcases // references to children Testcases
}

type record Testcase {
	Ats ats, // reference to the parent ATS
	charstring id,
	universal charstring title,
	charstring verdict,
	charstring role, // testcase, preamble, postamble
	universal charstring doc, // the full testcase docstring
	universal charstring description, // the non-tagged docstring part
	TaggedDescription tag, // a record of @tag names available in the docstring
	record of Log userlogs,
	record of LogEntry logentries,
	charstring duration,
	charstring start_time,
	charstring stop_time,
	charstring as_jpg_image, // rendered visual view as a Base64 JPG image
	charstring as_gif_image, // rendered visual view as a Base64 GIF image
	charstring as_png_image, // rendered visual view as a Base64 PNG image
}

type record Log {
	charstring timestamp, // format HH:MM:SS.zzz, relative to start time
	universal charstring message,
}

type record LogEntry {
	charstring timestamp, // format HH:MM:SS.zzz, relative to start time
	charstring fromPort optional,
	charstring toPort optional,
	charstring fromPort optional,
	universal charstring message optional
}
</pre>

In addition, the following exporter parameters are available (use them on command line):
<ul>
<li>template: the path to the Velocity template to apply</li>
<li>output: the path to the file to create once the template has been applied</li>
<li>html: (0/1 or true/false) indicates whether the output is HTML or not, implying additional HTML entities escaping or not (false by default)</li>
</ul>

"""

DEFAULT_TEMPLATE_FILENAME = "templates/default-simple-report.vm"



def formatTimestamp(timestamp):
	return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))  + ".%3.3d" % int((timestamp * 1000) % 1000)

##############################################################################
# Variables wrappers
##############################################################################

class AtsVariables:
	"""
	Behaves as a dict to access ats-related properties.
	
	Note: incomplete ATS models may be passed to this wrapper.
	As a consequence, some ats-related events may be missing
	when instanciating the object.
	
	That's why, in particular, stopTimestamp may not be 
	computed in some cases. 
	
	Allowing passing incomplete ATS models enables partial
	reporting of killed or running ATSes.
	"""
	def __init__(self, model):
		self._model = model
		# extract starttime/stoptime
		element = self._model.getDomElements("ats-started")[0]
		self._startTimestamp = float(element.attribute('timestamp'))
		
		try:
			element = self._model.getDomElements("ats-stopped")[0]
			self._stopTimestamp = float(element.attribute('timestamp'))
		except:
			self._stopTimestamp = None

	def __getitem__(self, name):
		if name == "id":
			return self._model.getId()
		elif name == "result":
			return self._model.getResult()
		elif name == "start_time":
			return formatTimestamp(self._startTimestamp)
		elif name == "stop_time":
			return formatTimestamp(self._stopTimestamp)
		elif name == "duration":
			if self._stopTimestamp is not None:
				return "%.3f" % (self._stopTimestamp - self._startTimestamp)
			else:
				return "N/A"
		elif name == "testcases":
			ret = []
			for testcase in self._model.getTestCases():
				if testcase.isComplete():
					ret.append(TestCaseVariables(testcase))
			return ret
		else:
			raise KeyError(name)

class TestCaseVariables:
	"""
	Behaves as a dict to access testcase-related properties.
	
	Note: only complete testcases models are passed to
	this wrapper.
	As a consequence, it can safely assume that all mandatory
	events for a testcase are present (in particular start/stop events).
	"""
	def __init__(self, model):
		self._model = model
		self._atsVariables = AtsVariables(self._model.getAts())

		self._taggedDescription = Documentation.TaggedDocstring()
		self._taggedDescription.parse(self._model.getDescription())
		self._tags = Documentation.DictWrapper(self._taggedDescription)
		self._role = self._model.getRole()

		# extract starttime/stoptime
		element = self._model.getDomElements("testcase-started")[0]
		self._startTimestamp = float(element.attribute('timestamp'))
		
		element = self._model.getDomElements("testcase-stopped")[0]
		self._stopTimestamp = float(element.attribute('timestamp'))
		

	def __getitem__(self, name):
		if name == "ats":
			return self._atsVariables
		elif name == "id":
			return self._model.getId()
		elif name == "title":
			return self._model.getTitle()
		elif name == "verdict":
			return self._model.getVerdict()
		elif name == "doc":
			# Complete, raw description
			return self._taggedDescription.getString()
		elif name == "description":
			# The untagged part of the docstring
			return self._taggedDescription[''].value()
		elif name == "duration":
			return "%.3f" % (self._stopTimestamp - self._startTimestamp)
		elif name == "start_time":
			return formatTimestamp(self._startTimestamp)
		elif name == "stop_time":
			return formatTimestamp(self._stopTimestamp)
		elif name == "role":
			return self._role
		elif name == "tag":
			return self._tags
		elif name == "userlogs":
			# Generated on the fly, as they may not be requested in all templates,
			# costly to compute, and requested only once per testcase if requested
			# (i.e. no cache required)
			ret = []
			for element in self._model.getDomElements("user"):
				timestamp = float(element.attribute('timestamp'))
				delta = timestamp - self._startTimestamp
				t = QTime().addMSecs(int(delta * 1000)).toString('hh:mm:ss.zzz')
				ret.append({'timestamp': t, 'message': element.text()})
			return ret
		elif name == "logs":
			# Generated on the fly, as they may not be requested in all templates,
			# costly to compute, and requested only once per testcase if requested
			# (i.e. no cache required)
			ret = []
			for element in self._model.getDomElements():
				timestamp = float(element.attribute('timestamp'))
				delta = timestamp - self._startTimestamp
				t = QTime().addMSecs(int(delta * 1000)).toString('hh:mm:ss.zzz')
				tagname = unicode(element.tagName())
				entry = {'timestamp': t, 'tagname': tagname}
				
				for attr in [ 'tsi-port', 'id', 'tc', 'duration', 'behaviour', 'verdict', 'result', 'timeout', 'from-tc', 'from-port', 'to-tc', 'to-port' ]:
					e = element.attribute(attr)
					if e and not e.isNull():
						entry[attr.replace('-', '')] = e

				for subelement in [ 'label', 'sut-address', 'message', 'template', 'payload' ]:
					e = element.firstChildElement(subelement)
					if e and not e.isNull():
						entry[subelement.replace('-', '')] = e.text()

				# Specific attributes per tag type
				if tagname == "user":
					entry['message'] = element.text()

				ret.append(entry)
				
			return ret
		elif name == "as_jpg_image":
			return self._model.getVisualRender(format = "JPG")
		elif name == "as_gif_image":
			return self._model.getVisualRender(format = "GIF")
		elif name == "as_png_image":
			return self._model.getVisualRender(format = "PNG")
		else:
			raise KeyError(name)


##############################################################################
# Exporter Plugin
##############################################################################

class ReportExporter(Plugin.ReportExporter):
	def __init__(self):
		Plugin.ReportExporter.__init__(self)
		self.setDefaultProperty("html", False)
		self.setDefaultProperty("template", None)
		self.setDefaultProperty("output", None)

	##
	# Implementation specific
	##
	def _getSummaryVariables(self):
		"""
		Analyses the available log model, builds a list
		of dict usable for a summary template formatting.
		
		Provides the following template variables:
		
		for each testcase:
		ats-id, testcase-id, testcase-title, testcase-verdict
		
		summary/counts:
		ats-count, {pass,fail,inconc,none,error}-{count,ratio}
		"""
		count = 0
		counts = {}
		for s in ['pass', 'fail', 'inconc', 'none', 'error']:
			counts[s] = 0
		atsCount = 0

		for ats in self.getModel().getAtses():
			atsCount += 1
			for testcase in (x for x in ats.getTestCases() if x.getRole() == "testcase"):
				if testcase.isComplete():
					v = testcase.getVerdict()
					if v in counts:
						counts[v] += 1
					count += 1

		summary = {
			'testcase_count': count,
			'ats_count': atsCount,
			'pass_count': counts['pass'],
			'fail_count': counts['fail'],
			'inconc_count': counts['inconc'],
			'none_count': counts['none'],
			'error_count': counts['error'],
			'pass_ratio': count and '%2.2f' % (float(counts['pass'])/float(count)*100.0) or '100',
			'fail_ratio': count and '%2.2f' % (float(counts['fail'])/float(count)*100.0) or '0',
			'inconc_ratio': count and '%2.2f' % (float(counts['inconc'])/float(count)*100.0) or '0',
			'none_ratio': count and '%2.2f' % (float(counts['none'])/float(count)*100.0) or '0',
			'error_ratio': count and '%2.2f' % (float(counts['error'])/float(count)*100.0) or '0',
		}
		return summary

	def _getTestCasesVariables(self):
		"""
		Returns a list of testcases variables
		"""
		ret = []
		for ats in self.getModel().getAtses():
			for testcase in ats.getTestCases():
				if testcase.isComplete():
					ret.append(TestCaseVariables(testcase))
		return ret

	def _getAtsesVariables(self):
		"""
		Returns a list of atses variables
		"""
		ret = []
		for ats in self.getModel().getAtses():
			ret.append(AtsVariables(ats))
		return ret

	def _applyTemplate(self, templateFilename, context):
		"""
		Load the configured template and apply it.
		"""
		try:
			f = open(templateFilename)
			content = f.read().decode('utf-8')
			f.close()
			template = airspeed.Template(content)
		except Exception, e:
			raise Exception("Unable to read template file %s: %s" % (templateFilename, unicode(e)))

		html = self["html"]
		if not html or html.lower() in ["false", "0"]:
			xform = None
		else:
			xform = TemplateManagement.html_escape
			
		try:
			return template.merge(context, xform = xform)
		except Exception, e:
			raise Exception("Unable to apply template file %s: %s" % (templateFilename, unicode(e)))

	##
	# Plugin.Exporter reimplementation
	##
	def export(self):
		"""
		Exports the injected model with the injected parameters.
		"""
		# Adjust filenames with absolute paths
		templateFilename = os.path.realpath(self['template']) # mandatory
		outputFilename = self['output'] and os.path.realpath(self['output']) or None # optional output parameter
		
		summary = self._getSummaryVariables()
		testcases = self._getTestCasesVariables()
		atses = self._getAtsesVariables()
		context = { 
			'summary': summary, 
			'testcases': testcases,
			'atses': atses,
			'html_escape': TemplateManagement.html_escape
		}
		output = self._applyTemplate(templateFilename, context)
		
		if not outputFilename:
			print output
		else:
			try:
				f = open(outputFilename, 'w')
				f.write(output.encode('utf-8'))
				f.close()
			except Exception, e:
				raise Exception("Unable to save output file file %s: %s" % (outputFilename, unicode(e)))
				
		return True
		
		


PluginManager.registerPluginClass("Simple Exporter", PLUGIN_ID, pluginClass = ReportExporter, configurationClass = None, version = VERSION, description = DESCRIPTION)

