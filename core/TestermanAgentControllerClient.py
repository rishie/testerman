##
# This file is part of Testerman, a test automation system.
# Copyright (c) 2008-2009 Sebastien Lefevre and other contributors
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
# -*- coding: utf-8 -*-
# Uri-centric: probe addressing is performed using URI only.
# 
##

import TestermanMessages as Messages
import TestermanNodes as Nodes

import threading

class TaccException(Exception): pass

class DummyLogger:
	def warning(self, txt):
		pass

	def debug(self, txt):
		pass

	def info(self, txt):
		pass

	def error(self, txt):
		pass

	def critical(self, txt):
		pass

class IaClient(Nodes.ConnectingNode):
	def __init__(self, name):
		Nodes.ConnectingNode.__init__(self, name, "IaClient")
		self.receivedNotificationCallback = None # on TRI-ENQUEUE-MSG
		self.logNotificationCallback = None # on LOG
		self.probeNotificationCallback = None # on PROBE
		self._logger = DummyLogger()
		self._subscriptions =[]
		self._mutex = threading.RLock()
		self._connected = False
	
	def lock(self):
		self._mutex.acquire()
	
	def unlock(self):
		self._mutex.release()
	
	def setLogger(self, logger):
		self._logger = logger

	def getLogger(self):
		return self._logger
	
	def trace(self, txt):
		"""
		Reimplemented from Nodes.ConnectingNode
		"""
		self.getLogger().debug(txt)

	def onConnection(self, channel):
		"""
		Reimplemented from Nodes.ConnectingNode
		
		Automatic resubscription on reconnection.
		"""
		self.lock()
		try:
			for uri in self._subscriptions:
				notification = Messages.Notification("SUBSCRIBE", uri, "Ia", "1.0")
				self.sendNotification(channel, notification)
		except:
			pass
		self._connected = True
		self.unlock()
	
	def onDisconnection(self, channel):
		self.lock()
		self._connected = False
		self.unlock()
	
	def isConnected(self):
		self.lock()
		ret = self._connected
		self.unlock()
		return ret
	
	def onRequest(self, channel, transactionId, request):
		self.getLogger().warning("Unexpected request received, discarding.")
		self.sendResponse(channel, transactionId, Messages.Response(505, "Ai Protocol Error"))
	
	def onNotification(self, channel, notification):
		self.getLogger().debug("Received a notification")
		if notification.getMethod() == "TRI-ENQUEUE-MSG" and self.receivedNotificationCallback:
			self.receivedNotificationCallback(notification.getUri(), notification.getApplicationBody(), notification.getHeader("SUT-Address"))
		elif notification.getMethod() == "LOG" and self.logNotificationCallback:
			self.logNotificationCallback(notification.getUri(), notification.getHeader('Log-Class'), notification.getApplicationBody())
		elif notification.getMethod() == "PROBE-EVENT" and self.probeNotificationCallback:
			self.probeNotificationCallback(notification)
	
	def onResponse(self, channel, transactionId, response):
		self.getLogger().warning("Unexpected asynchronous response received, discarding.")
		
	def setLogNotificationCallback(self, cb):
		self.logNotificationCallback = cb

	def setReceivedNotificationCallback(self, cb):
		self.receivedNotificationCallback = cb

	def setProbeNotificationCallback(self, cb):
		self.probeNotificationCallback = cb

	# High level functions callable from an IaClient
	
	def triSend(self, probeUri, message, sutAddress, profile = Messages.Message.CONTENT_TYPE_JSON):
		request = Messages.Request("TRI-SEND", probeUri, "Ia", "1.0")
		request.setHeader("SUT-Address", sutAddress)
		request.setApplicationBody(message, profile)
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			raise TaccException("Unable to send message through %s: %d %s\n%s" % (probeUri, response.getStatusCode(), response.getReasonPhrase(), response.getBody()))
	
	def triSAReset(self, probeUri):
		request = Messages.Request("TRI-SA-RESET", probeUri, "Ia", "1.0")
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False

	def triMap(self, probeUri):
		request = Messages.Request("TRI-MAP", probeUri, "Ia", "1.0")
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False

	def triUnmap(self, probeUri):
		request = Messages.Request("TRI-UNMAP", probeUri, "Ia", "1.0")
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False

	def triExecuteTestCase(self, probeUri, parameters = {}, profile = Messages.Message.CONTENT_TYPE_JSON):
		request = Messages.Request("TRI-EXECUTE-TESTCASE", probeUri, "Ia", "1.0")
		request.setApplicationBody(parameters, profile = profile)
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False
	
	def subscribe(self, uri):
		"""
		Subscribes to events for an uri.
		"""
		self.lock()
		try:
			if not uri in self._subscriptions:
				if self._connected:
					notification = Messages.Notification("SUBSCRIBE", uri, "Ia", "1.0")
					self.sendNotification(0, notification)
				# keep track of the subscription to enable auto-subscription on reconnection
				self._subscriptions.append(uri)
		except:
			pass
		self.unlock()
		return True
	
	def unsubscribe(self, uri):
		self.lock()
		try:
			if uri in self._subscriptions:
				if self._connected:
					notification = Messages.Notification("SUBSCRIBE", uri, "Ia", "1.0")
					self.sendNotification(0, notification)
				self._subscriptions.remove(uri)
		except:
			pass
		self.unlock()
		return True

	def lockProbe(self, probeUri):
		"""
		Locks a probe.
		
		Since LOCK operation on TACS also includes a free SUBSCRIBE, so no need to do a subscribe.
		
		@type  probeUri: string
		@param probeUri: the URI of the probe to lock.
		
		@rtype: bool
		@returns: True if correctly locked (or relocked), False otherwise.
		"""
		request = Messages.Request("LOCK", "system:tacs", "Ia", "1.0")
		request.setHeader("Probe-Uri", probeUri)
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			# Keep track of the subscription
			self.lock()
			if not probeUri in self._subscriptions:
				self._subscriptions.append(probeUri)
			self.unlock()
			return True
		else:
			return False
	
	def unlockProbe(self, probeUri):
		"""
		Unlocks a probe.
		The UNLOCK operation on TACS alo includes a free UNSUBSCRIBE.

		@type  probeUri: string
		@param probeUri: the URI of the probe to lock.
		
		@rtype: bool
		@returns: True if correctly unlocked, False otherwise.
		"""
		request = Messages.Request("UNLOCK", "system:tacs", "Ia", "1.0")
		request.setHeader("Probe-Uri", probeUri)
		response = self.executeRequest(0, request)
		# Anyway, we remove the local subscription.
		self.lock()
		if probeUri in self._subscriptions:
			self._subscriptions.remove(probeUri)
		self.unlock()
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False
	
	# Some agent-related methods
	# ...
	
	# Some agent-controller related methods
	def getRegisteredProbes(self):
		request = Messages.Request("GET-PROBES", "system:tacs", "Ia", "1.0")
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			ret = response.getApplicationBody()
			return ret
		else:
			return []

	def getRegisteredAgents(self):
		request = Messages.Request("GET-AGENTS", "system:tacs", "Ia", "1.0")
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			ret = response.getApplicationBody()
			return ret
		else:
			return []
	
	def deployProbe(self, probeUri, probeType):
		"""
		@throws: TaccException in case of an error
		"""
		# Extracts agent URI and probe name from the probeUri
		uri = Messages.Uri(probeUri)
		probeName = uri.getUser()
		agentUri = "agent:%s" % uri.getDomain()
		
		request = Messages.Request("DEPLOY", str(agentUri), "Ia", "1.0")
		request.setApplicationBody({'probe-name': probeName, 'probe-type': probeType})
		request.setHeader('Agent-Uri', str(agentUri))
		response = self.executeRequest(0, request)
		if not response:
			raise TaccException('Timeout')
		if response.getStatusCode() != 200:
			raise TaccException('Unable to deploy probe: %s' % response.getApplicationBody())
		# In all other cases, that's OK.
		return True

	def undeployProbe(self, probeUri):
		"""
		@throws: TaccException in case of an error
		"""
		# Extracts agent URI and probe name from the probeUri
		uri = Messages.Uri(probeUri)
		probeName = uri.getUser()
		agentUri = "agent:%s" % uri.getDomain()

		request = Messages.Request("UNDEPLOY", str(agentUri), "Ia", "1.0")
		request.setApplicationBody({'probe-name': probeName})
		request.setHeader('Agent-Uri', str(agentUri))
		response = self.executeRequest(0, request)
		if not response:
			raise TaccException('Timeout')
		if response.getStatusCode() != 200:
			raise TaccException('Unable to undeploy probe: %s' % response.getApplicationBody())
		# In all other cases, that's OK.
		return True

	def getProbeInfo(self, probeUri):
		"""
		@rtype: dict, or None
		@returns: None if the probe was not found, or a dict containing:
		 uri: string
		 contact: string
		 lock: bool
		 type: string
		"""
		request = Messages.Request("GET-PROBE", "system:tacs", "Ia", "1.0")
		request.setHeader('Probe-Uri', probeUri)
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			ret = response.getApplicationBody()
			return ret
		else:
			return None
	
	def restartAgent(self, agentUri):
		request = Messages.Request("RESTART", agentUri, "Ia", "1.0")
		request.setHeader('Agent-Uri', str(agentUri))
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False

	def updateAgent(self, agentUri):
		request = Messages.Request("UPDATE", agentUri, "Ia", "1.0")
		request.setHeader('Agent-Uri', str(agentUri))
		response = self.executeRequest(0, request)
		if response and response.getStatusCode() == 200:
			return True
		else:
			return False

	def getCounter(self, path):
		return 0
	#...
		

TheIaClient = None

def instance():
	return TheIaClient

def initialize(name, serverAddress):
	global TheIaClient
	TheIaClient = IaClient(name)
	instance().initialize(serverAddress)
	instance().start()

def finalize():
	instance().stop()
	instance().finalize()



# Some basic tests

if __name__ == "__main__":
	initialize("test", ("127.0.0.1", 8087))
	print "Getting registered probes..."
	print str(instance().getRegisteredProbes())
	finalize()
	
