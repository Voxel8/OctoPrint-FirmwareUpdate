# coding=utf-8
from __future__ import absolute_import

__author__ = "Kevin Murphy <kevin@voxel8.co>"
__license__ = "GNU Affero General Public License http://www.gnu.org/licenses/agpl.html"
__copyright__ = "Copyright (C) 2015 Kevin Murphy - Released under terms of the AGPLv3 License"

import octoprint.plugin
from octoprint.util import RepeatedTimer
import flask
import os
from subprocess import Popen, call
import signal
import linecache
import psutil
import time
import requests
import json
import urllib

class FirmwareUpdatePlugin(octoprint.plugin.StartupPlugin,
                       octoprint.plugin.TemplatePlugin,
                       octoprint.plugin.AssetPlugin,
                       octoprint.plugin.SettingsPlugin,
                       octoprint.plugin.SimpleApiPlugin):

    def __init__(self):
        self.isUpdating = False
        self._checkTimer = None
        self.updatePID = None

    def get_assets(self):
        return {
            "js": ["js/firmwareupdate.js"]
        }

    def startTimer(self, interval):
        self._checkTimer = RepeatedTimer(interval, self.checkStatus, run_first=True, condition=self.checkStatus)
        self._checkTimer.start()

    def checkStatus(self):
        update_result = open('/home/pi/Marlin/.build_log').read()
        if 'No device matching following was found' in update_result:
    	    self._logger.info("Failed update...")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="A connected device was not found."))
    	    return False
    	elif 'FAILED' in update_result:
    	    self._logger.info("Failed update...")
            self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed"))
    	    return False
    	elif 'bytes of flash verified' in update_result and 'successfully' in update_result :
            self._logger.info("Successful update!")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="completed"))
    	    return False
    	elif 'ReceiveMessage(): timeout' in update_result:
    	    self._logger.info("Update timed out. Check if port is already in use!")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Device timed out. Please check that the port is not in use!"))
    	    p = psutil.Process(self.updatePID)
    	    for child in p.children(recursive=True):
        	    child.kill()
    	    p.kill()
    	    return False
    	elif 'error:' in update_result:
    	    error_list = []
            with open('/home/pi/Marlin/.build_log') as myFile:
    		for num, line in enumerate(myFile, 1):
    		    if 'error:' in line:
    			    error_list.append(line)
    	    compileError = '<pre>' + ''.join(error_list) + '</pre>'
    	    self._logger.info("Update failed. Compiling error.")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason=compileError))
    	    return False
    	elif 'Make failed' in update_result:
    	    self._logger.info("Update failed. Compiling error.")
    	    self.isUpdating = False
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="failed", reason="Build failed."))
    	    return False
    	else:
    	    self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, status="continue"))
    	    return True

    def get_update_information(self):
        return dict(
            firmwareupdate_plugin=dict(
                displayName="FirmwareUpdate Plugin",
                displayVersion=self._plugin_version,
                type="github_commit",
                user="Voxel8",
                repo="OctoPrint-FirmwareUpdate",
                current=self._plugin_version,
                pip="https://github.com/Voxel8/OctoPrint-FirmwareUpdate/archive/{target_version}.zip"
            )
        )

    def get_api_commands(self):
        return dict(
            update_firmware=[],
	        check_is_updating=[]
        )

    def on_api_command(self, command, data):
    	if command == "update_firmware":
            r = requests.get('https://api.github.com/repos/Voxel8/Marlin/releases/latest')
            rjson = r.json()
            firmware_file = os.path.join(os.path.expanduser('~'), 'Marlin/firmware.hex')
            urllib.urlretrieve(rjson['assets'][0]['browser_download_url'], firmware_file)
            if os.path.isfile(firmware_file):
                # File exists, continue updating
            else:
                self._logger.info("Failed update... Release firmware was not downloaded")
                
    	elif command == "check_is_updating":
    	    if self.isUpdating == True:
    	        self._logger.info("Setting isUpdating to " + str(self.isUpdating))
    	        self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, createPopup="yes"))
    	    else:
    	        self._logger.info("Setting isUpdating to " + str(self.isUpdating))
    	        self._plugin_manager.send_plugin_message(self._identifier, dict(isupdating=self.isUpdating, deletePopup="yes"))
    	else:
    	    self._logger.info("Uknown command.")

    def on_api_get(self, request):
        return flask.make_response("Not found", 404)

    def get_template_configs(self):
        return [
            dict(type="settings", name="Firmware Update", data_bind="visible: loginState.isAdmin()"),
	    ]

__plugin_name__ = "Firmware Update Plugin"

def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = FirmwareUpdatePlugin()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
